#!/usr/bin/env python3
"""
Utility script for the Server / Agent to send messages or calls to mobile devices.
Usage:
    uv run python agent_notify.py msg "Your server backup completed successfully."
    uv run python agent_notify.py call
    uv run python agent_notify.py msg --target "mobile:friday-ios-123" "Direct message to specific phone"
"""

import argparse
import asyncio
import sys
from websockets.asyncio.client import connect
from models import Envelope, MsgBody, CallBody


async def notify_mobile(
    event_type: str,
    text: str = "",
    audio: str = "",
    target: str = "mobile",
    server_uri: str = "ws://64.227.176.104:8765",
    source: str = "server:core-agent",
):
    print(f"Connecting to {server_uri} as '{source}'...")
    async with connect(server_uri) as ws:
        if event_type == "msg":
            envelope = Envelope.create(
                type="msg",
                source=source,
                target=target,
                body=MsgBody(text=text),
            )
            print(f"🚀 Sending [MSG] to '{target}': {text}")
        elif event_type == "call":
            envelope = Envelope.create(
                type="call",
                source=source,
                target=target,
                body=CallBody(
                    audio=audio or "UklGRiQAAABXQVZFZm10IBAAAAABAAEAQB8AAEAfAAABAAgAZGF0YQAAAAA=",
                    action="stream",
                ),
            )
            print(f"📞 Triggering [CALL] to '{target}'...")
        else:
            print(f"Unknown event type: {event_type}")
            return

        await ws.send(envelope.to_json())
        print("✅ Delivered envelope to Agent Hub.")


def main():
    parser = argparse.ArgumentParser(description="Server/Agent -> Mobile Notification Dispatcher")
    parser.add_argument("type", choices=["msg", "call"], help="Type of event ('msg' or 'call')")
    parser.add_argument("text", nargs="?", default="Hello from Server Agent!", help="Text message content (for 'msg')")
    parser.add_argument("--target", default="mobile", help="Target device (default: 'mobile', or specific device ID)")
    parser.add_argument("--source", default="server:core-agent", help="Source ID (default: 'server:core-agent')")
    parser.add_argument("--host", default="ws://64.227.176.104:8765", help="WebSocket server URL")
    parser.add_argument("--audio", default="", help="Audio data for call (optional)")

    args = parser.parse_args()

    asyncio.run(
        notify_mobile(
            event_type=args.type,
            text=args.text,
            audio=args.audio,
            target=args.target,
            server_uri=args.host,
            source=args.source,
        )
    )


if __name__ == "__main__":
    main()
