from __future__ import annotations

import asyncio
import json
import logging
import uuid
from typing import Set

from websockets.asyncio.server import ServerConnection, serve

from actions import dispatch_action, set_server_instance
from db.session import init_db
from models import AckBody, Envelope, MsgBody
from registry import DeviceRegistry

logger = logging.getLogger("ws_server")


class WebSocketServer:
    def __init__(self, host: str = "0.0.0.0", port: int = 8765):
        self.host = host
        self.port = port
        self.registry = DeviceRegistry()
        self.server_id = "server:core-agent"
        set_server_instance(self)

    async def handle_register(self, websocket: ServerConnection, envelope: Envelope) -> None:
        client_type = envelope.body.get("client_type") or "unknown"
        device_name = envelope.body.get("device_name") or f"Device-{envelope.source}"
        capabilities = envelope.body.get("capabilities") or []

        # Register in device registry
        session = self.registry.register(
            websocket=websocket,
            device_id=envelope.source,
            device_type=client_type,
            device_name=device_name,
            capabilities=capabilities,
        )

        # Send ACK back to registering client
        ack_envelope = Envelope.create(
            type="ack",
            source=self.server_id,
            target=session.device_id,
            body=AckBody(
                reply_to=envelope.id,
                status="ok",
                details=f"Registered as {session.device_id} ({session.device_type})",
            ),
        )
        await websocket.send(ack_envelope.to_json())

    async def handle_server_target(self, websocket: ServerConnection, envelope: Envelope) -> None:
        """Handles messages directed to 'server' or 'agent'."""
        if envelope.type == "action":
            # Execute registered action (reminder.*, task.*, event.*, query.sql, etc.)
            result_envelope = await dispatch_action(envelope, self)
            await websocket.send(result_envelope.to_json())

        elif envelope.type == "msg":
            text = envelope.body.get("text", "")
            logger.info(f"🤖 [Agent Core] Processing message from {envelope.source}: '{text}'")

            # Echo / agent acknowledgment response back to source
            response_text = f"Agent received: '{text}'"
            reply_envelope = Envelope.create(
                type="msg",
                source=self.server_id,
                target=envelope.source,
                body={"text": response_text},
            )
            await websocket.send(reply_envelope.to_json())

        elif envelope.type == "call":
            logger.info(f"🤖 [Agent Core] Received call stream from {envelope.source}")
            ack = Envelope.create(
                type="ack",
                source=self.server_id,
                target=envelope.source,
                body=AckBody(reply_to=envelope.id, status="call_received"),
            )
            await websocket.send(ack.to_json())

        elif envelope.type == "ping":
            pong = Envelope.create(
                type="pong",
                source=self.server_id,
                target=envelope.source,
                body={"reply_to": envelope.id},
            )
            await websocket.send(pong.to_json())

    async def route_envelope(self, websocket: ServerConnection, envelope: Envelope) -> None:
        """Routes envelope to matching connected client(s)."""
        recipients = self.registry.resolve_targets(envelope.target, sender_socket=websocket)

        if not recipients:
            logger.warning(
                f"No active recipients found for target '{envelope.target}' (Envelope {envelope.id} from {envelope.source})"
            )
            return

        payload = envelope.to_json()
        logger.info(
            f"⚡ Routing envelope [{envelope.id[:8]}] ({envelope.type}) {envelope.source} -> {envelope.target} ({len(recipients)} recipients)"
        )
        await asyncio.gather(*(client.send(payload) for client in recipients), return_exceptions=True)

    async def handle_message(self, websocket: ServerConnection, raw_message: str | bytes) -> None:
        """Validates, parses envelope, and routes/processes message."""
        self.registry.touch(websocket)

        try:
            envelope = Envelope.from_json(raw_message)
        except ValueError as err:
            logger.warning(f"Validation error from {websocket.remote_address}: {err}")
            err_envelope = Envelope.create(
                type="error",
                source=self.server_id,
                target="unknown",
                body={"error": str(err)},
            )
            await websocket.send(err_envelope.to_json())
            return

        logger.info(
            f"📨 Received [{envelope.id[:8]}] type='{envelope.type}' from='{envelope.source}' to='{envelope.target}'"
        )

        # Handle Registration
        if envelope.type == "register":
            await self.handle_register(websocket, envelope)
            return

        # Ensure socket has a default registration if not explicitly registered
        if not self.registry.get_session(websocket):
            inferred_type = "mobile" if "mobile" in envelope.source else "client"
            self.registry.register(
                websocket=websocket,
                device_id=envelope.source,
                device_type=inferred_type,
                device_name=envelope.source,
            )

        # Direct server processing or action execution
        if envelope.target in ("server", "agent", self.server_id) or envelope.type == "action":
            await self.handle_server_target(websocket, envelope)
        else:
            # Route to target devices (or broadcast)
            await self.route_envelope(websocket, envelope)

    async def handler(self, websocket: ServerConnection) -> None:
        # Temporary registration on connect
        temp_id = f"client:{uuid.uuid4().hex[:8]}"
        self.registry.register(
            websocket=websocket,
            device_id=temp_id,
            device_type="client",
            device_name=str(websocket.remote_address),
        )

        try:
            async for raw_message in websocket:
                await self.handle_message(websocket, raw_message)
        except Exception as e:
            logger.debug(f"Connection ended with {websocket.remote_address}: {e}")
        finally:
            self.registry.unregister(websocket)

    async def run(self) -> None:
        # Initialize database tables on startup
        try:
            logger.info("Initializing database tables...")
            await init_db()
            logger.info("Database initialized successfully.")
        except Exception as e:
            logger.warning(f"Database initialization warning (will retry on operations): {e}")

        async with serve(self.handler, self.host, self.port) as server:
            logger.info(f"WebSocket Agent Hub running on ws://{self.host}:{self.port}")
            await server.serve_forever()
