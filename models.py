from __future__ import annotations

import datetime
import json
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, Literal


def current_iso_timestamp() -> str:
    """Returns current UTC timestamp in ISO 8601 format."""
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


@dataclass
class MsgBody:
    text: str
    format: str = "text"  # "text" | "markdown" | "json"


@dataclass
class CallBody:
    audio: str  # Base64-encoded audio or audio stream chunk/URL
    call_id: str | None = None
    action: str = "stream"  # "offer" | "stream" | "answer" | "hangup"


@dataclass
class RegisterBody:
    client_type: str  # "mobile" | "laptop" | "server" | "web" | "agent"
    device_name: str
    capabilities: list[str] = field(default_factory=list)


@dataclass
class AckBody:
    reply_to: str
    status: str = "ok"
    details: str | None = None


@dataclass
class Envelope:
    id: str
    type: str
    timestamp: str
    source: str
    target: str
    body: dict[str, Any]

    @classmethod
    def create(
        cls,
        type: str,
        source: str,
        target: str,
        body: dict[str, Any] | MsgBody | CallBody | RegisterBody | AckBody,
        id: str | None = None,
        timestamp: str | None = None,
    ) -> Envelope:
        if id is None:
            id = str(uuid.uuid4())
        if timestamp is None:
            timestamp = current_iso_timestamp()

        raw_body: dict[str, Any]
        if isinstance(body, (MsgBody, CallBody, RegisterBody, AckBody)):
            raw_body = asdict(body)
        elif isinstance(body, dict):
            raw_body = body
        else:
            raw_body = {"data": body}

        return cls(
            id=id,
            type=type,
            timestamp=timestamp,
            source=source,
            target=target,
            body=raw_body,
        )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Envelope:
        if not isinstance(data, dict):
            raise ValueError("Envelope payload must be a JSON object.")

        msg_id = data.get("id") or str(uuid.uuid4())
        msg_type = data.get("type")
        if not msg_type or not isinstance(msg_type, str):
            raise ValueError("Field 'type' is required and must be a string.")

        timestamp = data.get("timestamp") or current_iso_timestamp()
        source = data.get("source") or "unknown"
        target = data.get("target") or "*"
        
        # Support payload under 'body' or top-level fallback
        body = data.get("body")
        if body is None:
            # Check if fields were sent at root or under 'data'
            body = data.get("data") or {k: v for k, v in data.items() if k not in ("id", "type", "timestamp", "source", "target")}

        if not isinstance(body, dict):
            body = {"data": body}

        return cls(
            id=str(msg_id),
            type=str(msg_type),
            timestamp=str(timestamp),
            source=str(source),
            target=str(target),
            body=body,
        )

    @classmethod
    def from_json(cls, raw_json: str | bytes) -> Envelope:
        try:
            data = json.loads(raw_json)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid JSON format: {exc.msg}") from exc

        return cls.from_dict(data)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "type": self.type,
            "timestamp": self.timestamp,
            "source": self.source,
            "target": self.target,
            "body": self.body,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict())

    def get_msg_body(self) -> MsgBody:
        text = self.body.get("text")
        if text is None:
            raise ValueError(f"Envelope '{self.id}' of type 'msg' missing 'text' in body.")
        return MsgBody(text=str(text), format=self.body.get("format", "text"))

    def get_call_body(self) -> CallBody:
        audio = self.body.get("audio")
        if audio is None:
            raise ValueError(f"Envelope '{self.id}' of type 'call' missing 'audio' in body.")
        return CallBody(
            audio=str(audio),
            call_id=self.body.get("call_id"),
            action=self.body.get("action", "stream"),
        )
