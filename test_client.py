import asyncio
import json
import logging
from websockets.asyncio.client import connect

logging.basicConfig(level=logging.INFO, format="[Client] %(message)s")


async def test_client():
    uri = "ws://127.0.0.1:8765"

    async with connect(uri) as client_a, connect(uri) as client_b:
        print("\n--- Testing 'msg' (Text) ---")
        msg_payload = {
            "type": "msg",
            "body": {
                "text": "Hello from Client A!"
            }
        }
        await client_a.send(json.dumps(msg_payload))
        received_on_b = await client_b.recv()
        print(f"Client B received: {received_on_b}")
        parsed_b = json.loads(received_on_b)
        assert parsed_b["type"] == "msg"
        assert parsed_b["body"]["text"] == "Hello from Client A!"

        print("\n--- Testing 'call' (Audio) ---")
        call_payload = {
            "type": "call",
            "body": {
                "audio": "UklGRiQAAABXQVZFZm10IBAAAAABAAEAQB8AAEAfAAABAAgAZGF0YQAAAAA="
            }
        }
        await client_b.send(json.dumps(call_payload))
        received_on_a = await client_a.recv()
        print(f"Client A received: {received_on_a}")
        parsed_a = json.loads(received_on_a)
        assert parsed_a["type"] == "call"
        assert parsed_a["body"]["audio"].startswith("UklGR")

        print("\n--- Testing Error Handling (Invalid Payload) ---")
        invalid_payload = {"type": "unknown_type", "body": {}}
        await client_a.send(json.dumps(invalid_payload))
        error_resp = await client_a.recv()
        print(f"Client A received error: {error_resp}")
        assert json.loads(error_resp)["type"] == "error"

        print("\nAll tests passed successfully!")


if __name__ == "__main__":
    asyncio.run(test_client())
