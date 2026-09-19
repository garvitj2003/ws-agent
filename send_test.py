import argparse
import asyncio
import json
import sys
from websockets.asyncio.client import connect
from models import Envelope, MsgBody, CallBody


async def send_envelope(server_uri: str, envelope: Envelope):
    async with connect(server_uri) as websocket:
        await websocket.send(envelope.to_json())
        print(f"Sent [{envelope.type.upper()}] from '{envelope.source}' to '{envelope.target}':")
        print(json.dumps(envelope.to_dict(), indent=2))
        try:
            reply = await asyncio.wait_for(websocket.recv(), timeout=3.0)
            print("Received reply:", reply)
        except asyncio.TimeoutError:
            pass


def main():
    parser = argparse.ArgumentParser(description="Send test envelope to WebSocket server")
    parser.add_argument("--host", default="ws://64.227.176.104:8765", help="WebSocket server URL")
    parser.add_argument("--type", choices=["msg", "call", "both"], default="both", help="Event type")
    parser.add_argument("--source", default="laptop:garvit-macbook", help="Source device ID")
    parser.add_argument("--target", default="mobile", help="Target device ID or role (mobile, laptop, *, server)")
    parser.add_argument("--text", default="Hello Friday! Testing new envelope.", help="Text content for msg")
    parser.add_argument(
        "--audio",
        default="UklGRiQAAABXQVZFZm10IBAAAAABAAEAQB8AAEAfAAABAAgAZGF0YQAAAAA=",
        help="Audio content for call",
    )

    args = parser.parse_args()

    async def run():
        if args.type in ("msg", "both"):
            msg_env = Envelope.create(
                type="msg",
                source=args.source,
                target=args.target,
                body=MsgBody(text=args.text),
            )
            await send_envelope(args.host, msg_env)

        if args.type == "both":
            await asyncio.sleep(2)

        if args.type in ("call", "both"):
            call_env = Envelope.create(
                type="call",
                source=args.source,
                target=args.target,
                body=CallBody(audio=args.audio),
            )
            await send_envelope(args.host, call_env)

    asyncio.run(run())


if __name__ == "__main__":
    main()
