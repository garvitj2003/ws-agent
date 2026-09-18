from __future__ import annotations

import asyncio
import json
import logging
from typing import Set

from websockets.asyncio.server import ServerConnection, serve

from models import CallBody, MsgBody, WsMessage

logger = logging.getLogger("ws_server")


class WebSocketServer:
    def __init__(self, host: str = "0.0.0.0", port: int = 8765):
        self.host = host
        self.port = port
        self.clients: Set[ServerConnection] = set()

    async def register(self, websocket: ServerConnection) -> None:
        self.clients.add(websocket)
        logger.info(f"Client connected: {websocket.remote_address} (Total: {len(self.clients)})")

    async def unregister(self, websocket: ServerConnection) -> None:
        self.clients.discard(websocket)
        logger.info(f"Client disconnected: {websocket.remote_address} (Total: {len(self.clients)})")

    async def broadcast(self, message: WsMessage, sender: ServerConnection | None = None) -> None:
        """Broadcasts a validated WsMessage to connected clients."""
        payload = message.to_json()
        recipients = [client for client in self.clients if client != sender]
        if recipients:
            await asyncio.gather(*(client.send(payload) for client in recipients), return_exceptions=True)

    async def handle_message(self, websocket: ServerConnection, raw_message: str | bytes) -> None:
        """Parses and handles incoming msg/call objects."""
        try:
            ws_msg = WsMessage.from_json(raw_message)
        except ValueError as err:
            logger.warning(f"Validation error from {websocket.remote_address}: {err}")
            error_response = json.dumps({"type": "error", "message": str(err)})
            await websocket.send(error_response)
            return

        if ws_msg.type == "msg":
            body: MsgBody = ws_msg.body  # type: ignore
            logger.info(f"[MSG] Received from {websocket.remote_address}: text='{body.text}'")
            # Broadcast text message to all other connected clients
            await self.broadcast(ws_msg, sender=websocket)

        elif ws_msg.type == "call":
            body: CallBody = ws_msg.body  # type: ignore
            audio_preview = body.audio[:30] + "..." if len(body.audio) > 30 else body.audio
            logger.info(f"[CALL] Received from {websocket.remote_address}: audio='{audio_preview}' ({len(body.audio)} chars)")
            # Broadcast audio call chunk to all other connected clients
            await self.broadcast(ws_msg, sender=websocket)

    async def handler(self, websocket: ServerConnection) -> None:
        """Handles an individual client websocket lifecycle."""
        await self.register(websocket)
        try:
            async for raw_message in websocket:
                await self.handle_message(websocket, raw_message)
        except Exception as e:
            logger.debug(f"Connection ended with {websocket.remote_address}: {e}")
        finally:
            await self.unregister(websocket)

    async def run(self) -> None:
        """Starts the WebSocket server and keeps running."""
        async with serve(self.handler, self.host, self.port) as server:
            logger.info(f"WebSocket server running on ws://{self.host}:{self.port}")
            await server.serve_forever()
