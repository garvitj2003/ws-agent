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

        # 2. Register Laptop
        laptop_reg = Envelope.create(
            type="register",
            source="laptop:garvit-macbook",
            target="server",
            body=RegisterBody(client_type="laptop", device_name="MacBook Pro", capabilities=["cli", "terminal"]),
        )
        await laptop_ws.send(laptop_reg.to_json())
        ack_laptop = await laptop_ws.recv()
        logging.info(f"Laptop registered: {ack_laptop}")

        # 3. Phone sends message to Laptop (Direct Routing)
        direct_msg = Envelope.create(
            type="msg",
            source="mobile:garvit-phone",
            target="laptop:garvit-macbook",
            body=MsgBody(text="Run build on laptop"),
        )
        await phone_ws.send(direct_msg.to_json())
        recv_on_laptop = await laptop_ws.recv()
        logging.info(f"Laptop received direct msg: {recv_on_laptop}")
        parsed_laptop = Envelope.from_json(recv_on_laptop)
        assert parsed_laptop.body["text"] == "Run build on laptop"
        assert parsed_laptop.source == "mobile:garvit-phone"

        # 4. Laptop sends call to Mobile role (Role Targeting)
        call_msg = Envelope.create(
            type="call",
            source="laptop:garvit-macbook",
            target="mobile",
            body=CallBody(audio="UklGRiQAAABXQVZFZm10IBAAAAABAAEAQB8AAEAfAAABAAgAZGF0YQAAAAA="),
        )
        await laptop_ws.send(call_msg.to_json())
        recv_on_phone = await phone_ws.recv()
        logging.info(f"Phone received call from laptop: {recv_on_phone}")
        parsed_phone = Envelope.from_json(recv_on_phone)
        assert parsed_phone.type == "call"
        assert parsed_phone.source == "laptop:garvit-macbook"

        # 5. Phone sends message to Server (Agent Processing)
        server_msg = Envelope.create(
            type="msg",
            source="mobile:garvit-phone",
            target="server",
            body=MsgBody(text="What is my server status?"),
        )
        await phone_ws.send(server_msg.to_json())
        recv_agent_reply = await phone_ws.recv()
        logging.info(f"Phone received Agent reply: {recv_agent_reply}")
        parsed_reply = Envelope.from_json(recv_agent_reply)
        assert parsed_reply.source == "server:core-agent"

        logging.info("✅ All envelope & routing tests passed!")


if __name__ == "__main__":
    asyncio.run(run_tests())
