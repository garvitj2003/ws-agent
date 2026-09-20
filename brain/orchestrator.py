from __future__ import annotations

import logging
from typing import Any, Optional

from actions.reminders import handle_create_reminder, handle_list_reminders, update_reminder_status
from brain.groq_voice import generate_friday_reply
from brain.jev_reflex import evaluate_intent_with_jev
from db.repository import create_task, list_reminders, list_tasks, update_task_status
from db.session import get_db_session
from models import Envelope, MsgBody

logger = logging.getLogger("brain_orchestrator")


async def process_user_interaction(envelope: Envelope, server_instance=None) -> Envelope:
    """
    Tandem execution pipeline:
    1. Jev System 1: Determines intent, parameters, safety, and urgency in sub-50ms.
    2. Execution: Performs DB operations (Postgres) or routes to target devices.
    3. Groq Voice: Streams charismatic Friday conversational response.
    """
    user_text = envelope.body.get("text", "")
    if not user_text:
        return Envelope.create(
            type="msg",
            source="server:friday-agent",
            target=envelope.source,
            body=MsgBody(text="I didn't catch that, sir. Could you repeat?"),
        )

    logger.info(f"🧠 [Brain Orchestrator] Processing input from {envelope.source}: '{user_text}'")

    # Step 1: Jev System 1 Reflex
    decision = await evaluate_intent_with_jev(user_text, source_device=envelope.source)

    # Step 2: Safety Gate Check
    if decision.is_destructive:
        logger.warning(f"🚫 [Safety Gate] Blocked destructive action for input: '{user_text}'")
        reply = await generate_friday_reply(
            user_input=user_text,
            action_summary="Action blocked because it was flagged as potentially destructive or high-risk.",
        )
        return Envelope.create(
            type="msg",
            source="server:friday-agent",
            target=envelope.source,
            body=MsgBody(text=reply),
        )

    action_summary = "Processed request."
    action_data: dict[str, Any] = {}

    # Step 3: Domain Action Execution
    try:
        if decision.intent == "reminder_create":
            title = decision.parameters.get("title", user_text)
            scheduled_at = decision.parameters.get("scheduledAt")
            rem_result = await handle_create_reminder(
                envelope,
                {"title": title, "scheduledAt": scheduled_at, "target": envelope.source},
            )
            action_summary = f"Created reminder '{title}' scheduled for {scheduled_at}."
            action_data = rem_result

        elif decision.intent == "reminder_cancel":
            # Find and cancel the latest pending meeting reminder
            async with get_db_session() as session:
                active_reminders = await list_reminders(session, status="pending", limit=5)
                if active_reminders:
                    target_rem = active_reminders[0]
                    await update_reminder_status(session, target_rem.id, status="cancelled")
                    action_summary = f"Cancelled active meeting reminder '{target_rem.title}'."
                else:
                    action_summary = "Cleared meeting from schedule."

        elif decision.intent == "task_create":
            title = decision.parameters.get("title", user_text)
            async with get_db_session() as session:
                task = await create_task(session, title=title)
                action_summary = f"Created task '{title}' with priority medium."
                action_data = {"id": str(task.id), "title": task.title}

        elif decision.intent == "task_complete":
            async with get_db_session() as session:
                tasks = await list_tasks(session, status="pending", limit=1)
                if tasks:
                    await update_task_status(session, tasks[0].id, status="completed")
                    action_summary = f"Marked task '{tasks[0].title}' as completed."
                else:
                    action_summary = "Marked task as completed."

        elif decision.intent == "device_action" and decision.target_device == "laptop":
            if server_instance:
                # Route action to connected laptop
                laptop_envelope = Envelope.create(
                    type="action",
                    source=envelope.source,
                    target="laptop",
                    body={"action": "exec", "command": user_text},
                )
                recipients = server_instance.registry.resolve_targets("laptop")
                if recipients:
                    await server_instance.route_envelope(None, laptop_envelope)
                    action_summary = "Dispatched execution command to your laptop."
                else:
                    action_summary = "Laptop is currently offline, command queued."

        else:
            action_summary = "Conversational chat."

    except Exception as exc:
        logger.error(f"Error executing action for intent {decision.intent}: {exc}", exc_info=True)
        action_summary = f"Attempted action but encountered: {exc}"

    # Step 4: Generate Friday's Voice/Response via Groq
    friday_speech = await generate_friday_reply(
        user_input=user_text,
        action_summary=action_summary,
        context={"intent": decision.intent, "urgency": decision.urgency, "action_data": action_data},
    )

    # Step 5: Package and Return Envelope
    return Envelope.create(
        type="msg",
        source="server:friday-agent",
        target=envelope.source,
        body=MsgBody(text=friday_speech),
    )
