from __future__ import annotations

import logging
from typing import Any, Dict

from brain.groq_voice import generate_friday_reply
from brain.jev_reflex import evaluate_intent_with_jev
from db.dynamic_repo import dynamic_repo
from db.session import get_db_session
from models import Envelope, MsgBody

logger = logging.getLogger("brain_orchestrator")


async def process_user_interaction(envelope: Envelope, server_instance=None) -> Envelope:
    """
    Universal metadata-driven execution pipeline:
    1. Jev System 1: Determines operation ('create', 'search', 'update', 'delete', 'overview') and entity ('reminders', 'tasks', 'memories', etc.).
    2. Dynamic Repository: Executes strongly-typed ORM operations on PostgreSQL.
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

    # Step 1: Jev System 1 Dynamic Evaluation (<40ms)
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
    action_data: Dict[str, Any] = {}

    # Step 3: Dynamic Universal Execution Layer
    try:
        async with get_db_session() as session:
            # A. Agenda / Schedule Overview
            if decision.operation == "overview":
                overview = await dynamic_repo.get_agenda_overview(session)
                action_data = overview

                reminders = [r.get("title", "") for r in overview["reminders"]]
                tasks = [t.get("title", "") for t in overview["tasks"]]
                events = [e.get("title", "") for e in overview["events"]]

                if overview["total_items"] == 0:
                    action_summary = "Your schedule is completely clear for today. No pending reminders, tasks, or events."
                else:
                    parts = []
                    if events:
                        parts.append(f"Events: {', '.join(events)}")
                    if reminders:
                        parts.append(f"Reminders: {', '.join(reminders)}")
                    if tasks:
                        parts.append(f"Pending tasks: {', '.join(tasks)}")
                    action_summary = f"Agenda overview: {'; '.join(parts)}."

            # B. Universal Create (reminders, tasks, memories, events, etc.)
            elif decision.operation == "create" and decision.entity != "none":
                data = decision.parameters.get("data") or {"title": user_text}
                created_record = await dynamic_repo.create(session, decision.entity, data)
                action_data = created_record
                item_label = created_record.get("title") or created_record.get("content") or decision.entity
                action_summary = f"Created new {decision.entity[:-1] if decision.entity.endswith('s') else decision.entity}: '{item_label}'."

            # C. Universal Search (recall memories, search tasks/reminders)
            elif decision.operation == "search" and decision.entity != "none":
                search_query = decision.parameters.get("search_query", user_text)
                timeframe = decision.parameters.get("timeframe", "any")
                results = await dynamic_repo.search(
                    session=session,
                    entity=decision.entity,
                    query=search_query,
                    timeframe=timeframe,
                    limit=5,
                )
                action_data = {"count": len(results), "results": results}
                if results:
                    found_items = [r.get("content") or r.get("title") for r in results]
                    action_summary = f"Found matching {decision.entity}: {', '.join(str(x) for x in found_items)}."
                else:
                    action_summary = f"No matching records found in {decision.entity} for query '{search_query}'."

            # D. Universal Update (e.g. cancel meeting, complete task)
            elif decision.operation == "update" and decision.entity != "none":
                search_query = decision.parameters.get("search_query", "")
                timeframe = decision.parameters.get("timeframe", "any")
                updates = decision.parameters.get("updates", {})

                res = await dynamic_repo.search_and_update(
                    session=session,
                    entity=decision.entity,
                    search_query=search_query,
                    timeframe=timeframe,
                    updates=updates,
                )
                action_data = res
                if res.get("found"):
                    updated_rec = res.get("record", {})
                    item_label = updated_rec.get("title") or updated_rec.get("content") or "record"
                    new_status = updates.get("status", "updated")
                    action_summary = f"Updated {decision.entity[:-1] if decision.entity.endswith('s') else decision.entity} '{item_label}' to status '{new_status}'."
                else:
                    action_summary = f"Could not find any matching {decision.entity} to update for '{search_query}'."

            # E. Device Action
            elif decision.operation == "device_action":
                if server_instance:
                    target_device = decision.target_device if decision.target_device != "server" else "laptop"
                    laptop_envelope = Envelope.create(
                        type="action",
                        source=envelope.source,
                        target=target_device,
                        body={"action": "exec", "command": user_text},
                    )
                    recipients = server_instance.registry.resolve_targets(target_device)
                    if recipients:
                        await server_instance.route_envelope(None, laptop_envelope)
                        action_summary = f"Dispatched execution command to {target_device}."
                    else:
                        action_summary = f"{target_device.capitalize()} is currently offline."

            else:
                action_summary = "Conversational chat."

    except Exception as exc:
        logger.error(f"Error executing dynamic action: {exc}", exc_info=True)
        action_summary = f"Attempted operation on {decision.entity} but encountered: {exc}"

    # Step 4: Generate Friday's Voice Response via Groq (openai/gpt-oss-20b)
    friday_speech = await generate_friday_reply(
        user_input=user_text,
        action_summary=action_summary,
        context={
            "operation": decision.operation,
            "entity": decision.entity,
            "urgency": decision.urgency,
            "action_data": action_data,
        },
    )

    # Step 5: Package and Deliver Response Envelope
    return Envelope.create(
        type="msg",
        source="server:friday-agent",
        target=envelope.source,
        body=MsgBody(text=friday_speech),
    )
