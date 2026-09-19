from __future__ import annotations

import datetime
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

from websockets.asyncio.server import ServerConnection

logger = logging.getLogger("device_registry")


@dataclass
class DeviceSession:
    websocket: ServerConnection
    device_id: str  # e.g. "mobile:garvit-iphone" or "laptop:macbook"
    device_type: str  # e.g. "mobile", "laptop", "server", "web"
    device_name: str
    capabilities: List[str] = field(default_factory=list)
    connected_at: str = field(
        default_factory=lambda: datetime.datetime.now(datetime.timezone.utc).isoformat()
    )
    last_seen: str = field(
        default_factory=lambda: datetime.datetime.now(datetime.timezone.utc).isoformat()
    )


class DeviceRegistry:
    def __init__(self):
        # Map websocket to DeviceSession
        self._socket_to_session: Dict[ServerConnection, DeviceSession] = {}
        # Map device_id to ServerConnection
        self._device_id_to_socket: Dict[str, ServerConnection] = {}
        # Map device_type to set of ServerConnections
        self._type_to_sockets: Dict[str, Set[ServerConnection]] = {}

    def register(
        self,
        websocket: ServerConnection,
        device_id: str,
        device_type: str,
        device_name: str,
        capabilities: Optional[List[str]] = None,
    ) -> DeviceSession:
        # Clean up any existing mapping for this socket or device_id
        self.unregister(websocket)
        if device_id in self._device_id_to_socket:
            old_socket = self._device_id_to_socket[device_id]
            if old_socket != websocket:
                self.unregister(old_socket)

        session = DeviceSession(
            websocket=websocket,
            device_id=device_id,
            device_type=device_type.lower(),
            device_name=device_name,
            capabilities=capabilities or [],
        )

        self._socket_to_session[websocket] = session
        self._device_id_to_socket[device_id] = websocket

        if session.device_type not in self._type_to_sockets:
            self._type_to_sockets[session.device_type] = set()
        self._type_to_sockets[session.device_type].add(websocket)

        logger.info(
            f"Registered device: id='{device_id}', type='{session.device_type}', name='{device_name}' (Total active: {len(self._socket_to_session)})"
        )
        return session

    def unregister(self, websocket: ServerConnection) -> Optional[DeviceSession]:
        session = self._socket_to_session.pop(websocket, None)
        if session:
            self._device_id_to_socket.pop(session.device_id, None)
            if session.device_type in self._type_to_sockets:
                self._type_to_sockets[session.device_type].discard(websocket)
                if not self._type_to_sockets[session.device_type]:
                    del self._type_to_sockets[session.device_type]
            logger.info(f"Unregistered device: id='{session.device_id}' (Remaining: {len(self._socket_to_session)})")
        return session

    def touch(self, websocket: ServerConnection) -> None:
        session = self._socket_to_session.get(websocket)
        if session:
            session.last_seen = datetime.datetime.now(datetime.timezone.utc).isoformat()

    def get_session(self, websocket: ServerConnection) -> Optional[DeviceSession]:
        return self._socket_to_session.get(websocket)

    def get_session_by_id(self, device_id: str) -> Optional[DeviceSession]:
        ws = self._device_id_to_socket.get(device_id)
        if ws:
            return self._socket_to_session.get(ws)
        return None

    def resolve_targets(
        self,
        target: str,
        sender_socket: Optional[ServerConnection] = None,
    ) -> List[ServerConnection]:
        """
        Resolves target expression to a list of active WebSocket connections:
        - "*" or "all": All connected clients except the sender
        - "mobile" / "laptop" / "server" / "web": All clients matching that device_type
        - "mobile:device123": Specific device by exact device_id
        """
        target = target.strip()

        # Broadcast to all except sender
        if target in ("*", "all"):
            return [ws for ws in self._socket_to_session.keys() if ws != sender_socket]

        # Match exact device ID (e.g. "mobile:friday-01")
        if target in self._device_id_to_socket:
            ws = self._device_id_to_socket[target]
            if ws != sender_socket:
                return [ws]
            return []

        # Match role / device_type (e.g. "mobile" or "laptop")
        target_lower = target.lower()
        if target_lower in self._type_to_sockets:
            return [ws for ws in self._type_to_sockets[target_lower] if ws != sender_socket]

        # Check prefix match (e.g. "mobile:*" -> all mobile devices)
        if ":" in target_lower:
            prefix, rest = target_lower.split(":", 1)
            if rest in ("*", "all") and prefix in self._type_to_sockets:
                return [ws for ws in self._type_to_sockets[prefix] if ws != sender_socket]

        return []

    def list_devices(self) -> List[Dict[str, Any]]:
        return [
            {
                "device_id": s.device_id,
                "device_type": s.device_type,
                "device_name": s.device_name,
                "capabilities": s.capabilities,
                "connected_at": s.connected_at,
                "last_seen": s.last_seen,
            }
            for s in self._socket_to_session.values()
        ]
