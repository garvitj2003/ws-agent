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

        # 3. Direct Routing: Phone -> Laptop
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

        # 4. Action Test: reminder.create (pending status)
        rem_create_env = Envelope.create(
            type="action",
            source="mobile:garvit-phone",
            target="server",
            body={
                "action": "reminder.create",
                "data": {
                    "title": "Call Mom",
                    "scheduledAt": "2026-09-20T20:00:00+05:30",
                    "description": "Weekly catchup call",
                },
            },
        )
        await phone_ws.send(rem_create_env.to_json())
        recv_rem_res = await phone_ws.recv()
        logging.info(f"Phone received reminder.create result: {recv_rem_res}")
        parsed_rem_res = Envelope.from_json(recv_rem_res)
        assert parsed_rem_res.type == "action_result"
        assert parsed_rem_res.body["status"] == "success"
        reminder_id = parsed_rem_res.body["data"]["id"]
        assert parsed_rem_res.body["data"]["status"] == "pending"

        # 5. Action Test: reminder.dismiss
        rem_dismiss_env = Envelope.create(
            type="action",
            source="mobile:garvit-phone",
            target="server",
            body={
                "action": "reminder.dismiss",
                "data": {"id": reminder_id},
            },
        )
        await phone_ws.send(rem_dismiss_env.to_json())
        recv_dismiss_res = await phone_ws.recv()
        logging.info(f"Phone received reminder.dismiss result: {recv_dismiss_res}")
        parsed_dismiss = Envelope.from_json(recv_dismiss_res)
        assert parsed_dismiss.body["data"]["status"] == "dismissed"

        # 6. Action Test: task.create & task.complete
        task_create_env = Envelope.create(
            type="action",
            source="laptop:garvit-macbook",
            target="server",
            body={
                "action": "task.create",
                "data": {
                    "title": "Review pull request #42",
                    "priority": "high",
                },
            },
        )
        await laptop_ws.send(task_create_env.to_json())
        recv_task_res = await laptop_ws.recv()
        logging.info(f"Laptop received task.create result: {recv_task_res}")
        parsed_task = Envelope.from_json(recv_task_res)
        assert parsed_task.body["status"] == "success"
        task_id = parsed_task.body["data"]["id"]

        # 7. Action Test: safe SQL query
        sql_env = Envelope.create(
            type="action",
            source="laptop:garvit-macbook",
            target="server",
            body={
                "action": "query.sql",
                "data": {
                    "query": "SELECT id, title, status FROM reminders LIMIT 5",
                },
            },
        )
        await laptop_ws.send(sql_env.to_json())
        recv_sql_res = await laptop_ws.recv()
        logging.info(f"Laptop received query.sql result: {recv_sql_res}")
        parsed_sql = Envelope.from_json(recv_sql_res)
        assert parsed_sql.body["status"] == "success"

        # 8. Action Test: unsafe SQL query boundary check
        unsafe_sql_env = Envelope.create(
            type="action",
            source="laptop:garvit-macbook",
            target="server",
            body={
                "action": "query.sql",
                "data": {
                    "query": "DROP TABLE reminders",
                },
            },
        )
        await laptop_ws.send(unsafe_sql_env.to_json())
        recv_unsafe_res = await laptop_ws.recv()
        logging.info(f"Laptop received unsafe query rejection: {recv_unsafe_res}")
        parsed_unsafe = Envelope.from_json(recv_unsafe_res)
        assert parsed_unsafe.body["status"] == "error"
        assert "Disallowed keyword" in parsed_unsafe.body["error"] or "Only SELECT" in parsed_unsafe.body["error"]

        logging.info("✅ All Action & Database integration tests passed successfully!")


if __name__ == "__main__":
    asyncio.run(run_tests())
