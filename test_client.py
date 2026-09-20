import asyncio
import json
import logging
from websockets.asyncio.client import connect
from models import Envelope, MsgBody, CallBody, RegisterBody

logging.basicConfig(level=logging.INFO, format="[Test] %(message)s")


async def run_tests():
    uri = "ws://127.0.0.1:8765"

    async with connect(uri) as phone_ws, connect(uri) as laptop_ws:
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

        # 2. Test Conversational Scenario 1: Creating Meeting Reminder via Friday Brain
        logging.info("\n--- Scenario 1: Setting Meeting Reminder ---")
        msg1 = Envelope.create(
            type="msg",
            source="mobile:garvit-phone",
            target="server",
            body=MsgBody(text="Hey Friday, we have a meeting with the client at 1pm tomorrow"),
        )
        await phone_ws.send(msg1.to_json())
        reply1 = await phone_ws.recv()
        logging.info(f"Friday Replied: {reply1}")
        parsed1 = Envelope.from_json(reply1)
        assert parsed1.type == "msg"
        assert len(parsed1.body["text"]) > 0

        # 3. Test Conversational Scenario 2: Cancelling meeting when client ditched
        logging.info("\n--- Scenario 2: Cancelling Meeting on Client Ditch ---")
        msg2 = Envelope.create(
            type="msg",
            source="mobile:garvit-phone",
            target="server",
            body=MsgBody(text="Hey Friday, the client has ditched us."),
        )
        await phone_ws.send(msg2.to_json())
        reply2 = await phone_ws.recv()
        logging.info(f"Friday Replied: {reply2}")
        parsed2 = Envelope.from_json(reply2)
        assert parsed2.type == "msg"
        assert len(parsed2.body["text"]) > 0

        # 4. Direct Action Test: reminder.list to verify DB status
        list_env = Envelope.create(
            type="action",
            source="mobile:garvit-phone",
            target="server",
            body={"action": "reminder.list", "data": {}},
        )
        await phone_ws.send(list_env.to_json())
        list_res = await phone_ws.recv()
        logging.info(f"Reminders in Database: {list_res}")

        logging.info("\n✅ All Brain Orchestrator & Action tests passed successfully!")


if __name__ == "__main__":
    asyncio.run(run_tests())
