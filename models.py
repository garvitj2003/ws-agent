from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from typing import Any, Literal


@dataclass
class MsgBody:
    text: str


@dataclass
class CallBody:
    audio: str  # Base64-encoded audio or audio stream chunk/URL


@dataclass
class WsMessage:
    type: Literal["msg", "call"]
    body: MsgBody | CallBody

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> WsMessage:
        msg_type = data.get("type")
        if msg_type not in ("msg", "call"):
            raise ValueError(f"Invalid message type '{msg_type}'. Expected 'msg' or 'call'.")

        # Support payload in 'body', 'data', or top-level fields
        raw_body = data.get("body") or data.get("data") or data

        if msg_type == "msg":
            text = raw_body.get("text")
            if text is None or not isinstance(text, str):
                raise ValueError("Message of type 'msg' must have a string 'text' field in its body.")
            return cls(type="msg", body=MsgBody(text=text))

        elif msg_type == "call":
            audio = raw_body.get("audio")
            if audio is None or not isinstance(audio, str):
                raise ValueError("Message of type 'call' must have a string 'audio' field (e.g. base64/URL) in its body.")
            return cls(type="call", body=CallBody(audio=audio))

        raise ValueError(f"Unsupported message type: {msg_type}")

    @classmethod
    def from_json(cls, raw_json: str | bytes) -> WsMessage:
        try:
            data = json.loads(raw_json)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid JSON format: {exc.msg}") from exc

        if not isinstance(data, dict):
            raise ValueError("Message payload must be a JSON object.")

        return cls.from_dict(data)

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "body": asdict(self.body),
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict())
