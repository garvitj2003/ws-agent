import asyncio
import json
import logging
from websockets.asyncio.client import connect
from models import Envelope, MsgBody, CallBody, RegisterBody

logging.basicConfig(level=logging.INFO, format="[Test] %(message)s")


async def run_tests():
    uri = "ws://127.0.0.1:8765"

    async with connect(uri) as phone_ws:
        # 1. Register Phone
        phone_reg = Envelope.create(
            type="register",
            source="mobile:garvit-phone",
            target="server",
            body=RegisterBody(client_type="mobile", device_name="iPhone 15", capabilities=["audio", "notifications"]),
        )
        await phone_ws.send(phone_reg.to_json())
        ack_phone = await phone_ws.recv()
        logging.info(f"Phone registered: {ack_phone}")

        # 2. Schedule meeting with Harvard
        logging.info("\n--- 1. Scheduling Meeting with Harvard ---")
        msg1 = Envelope.create(
            type="msg",
            source="mobile:garvit-phone",
            target="server",
            body=MsgBody(text="Hey Friday, schedule a meeting with Harvard for tomorrow at 1pm"),
        )
        await phone_ws.send(msg1.to_json())
        reply1 = await phone_ws.recv()
        logging.info(f"Friday Replied: {Envelope.from_json(reply1).body['text']}")

        # 3. Ask what's on my plate
        logging.info("\n--- 2. Asking 'What is on my plate today?' ---")
        msg2 = Envelope.create(
            type="msg",
            source="mobile:garvit-phone",
            target="server",
            body=MsgBody(text="Hey Friday, what's on my plate today?"),
        )
        await phone_ws.send(msg2.to_json())
        reply2 = await phone_ws.recv()
        logging.info(f"Friday Replied: {Envelope.from_json(reply2).body['text']}")

        # 4. Cancel meeting with Harvard
        logging.info("\n--- 3. Cancelling Meeting with Harvard due tomorrow ---")
        msg3 = Envelope.create(
            type="msg",
            source="mobile:garvit-phone",
            target="server",
            body=MsgBody(text="Hey Friday, cancel my meeting with Harvard due tomorrow"),
        )
        await phone_ws.send(msg3.to_json())
        reply3 = await phone_ws.recv()
        logging.info(f"Friday Replied: {Envelope.from_json(reply3).body['text']}")

        # 5. Ask what's on my plate again to confirm it's cleared
        logging.info("\n--- 4. Checking agenda again ---")
        msg4 = Envelope.create(
            type="msg",
            source="mobile:garvit-phone",
            target="server",
            body=MsgBody(text="What is on my plate now?"),
        )
        await phone_ws.send(msg4.to_json())
        reply4 = await phone_ws.recv()
        logging.info(f"Friday Replied: {Envelope.from_json(reply4).body['text']}")

        logging.info("\n✅ All Harvard meeting & Daily Agenda tests completed successfully!")


if __name__ == "__main__":
    asyncio.run(run_tests())
