from __future__ import annotations

import asyncio
import datetime
import logging
from typing import Any

from actions.dispatcher import register_action
from db.repository import (
    create_reminder,
    delete_reminder,
    get_reminder,
    list_reminders,
    update_reminder_status,
)
from db.session import get_db_session
from models import Envelope, MsgBody

logger = logging.getLogger("action_reminders")

# Reference to the active server instance for routing triggers
_server_instance = None


def set_server_instance(server):
    global _server_instance
    _server_instance = server


async def _schedule_reminder_trigger(reminder_id: str, scheduled_at: datetime.datetime, title: str, target: str):
    """Schedules background task to trigger notification when scheduled_at arrives."""
    now = datetime.datetime.now(datetime.timezone.utc)
    delay = (scheduled_at - now).total_seconds()

    if delay > 0:
        logger.info(f"⏰ Reminder '{title}' [{reminder_id}] scheduled in {delay:.1f}s for target '{target}'")
        await asyncio.sleep(delay)

    # Check if reminder is still pending
    async with get_db_session() as session:
        rem = await get_reminder(session, reminder_id)
        if not rem or rem.status != "pending":
            logger.info(f"Reminder [{reminder_id}] was cancelled or updated (status: {rem.status if rem else 'deleted'}). Skipping trigger.")
            return

        # Mark as triggered
        await update_reminder_status(session, reminder_id, status="triggered")

    logger.info(f"🔔 Triggering reminder: '{title}' [{reminder_id}] to target '{target}'")

    if _server_instance:
        notification_envelope = Envelope.create(
            type="msg",
            source="server:reminder-service",
            target=target,
            body=MsgBody(text=f"⏰ Reminder: {title}"),
        )
        recipients = _server_instance.registry.resolve_targets(target)
        if recipients:
            payload = notification_envelope.to_json()
            await asyncio.gather(*(c.send(payload) for c in recipients), return_exceptions=True)


@register_action("reminder.create")
async def handle_create_reminder(envelope: Envelope, data: dict[str, Any]) -> dict[str, Any]:
    title = data.get("title")
    if not title:
        raise ValueError("Field 'title' is required for reminder.create")

    scheduled_at = data.get("scheduledAt") or data.get("scheduled_at")
    if not scheduled_at:
        raise ValueError("Field 'scheduledAt' is required for reminder.create")

    description = data.get("description")
    target = data.get("target") or envelope.source if envelope.source.startswith("mobile") else "mobile"

    async with get_db_session() as session:
        reminder = await create_reminder(
            session=session,
            title=title,
            scheduled_at=scheduled_at,
            description=description,
            target_device=target,
            action_payload=data,
        )

        reminder_id_str = str(reminder.id)
        scheduled_dt = reminder.scheduled_at

        # Spawn background trigger task
        asyncio.create_task(
            _schedule_reminder_trigger(
                reminder_id=reminder_id_str,
                scheduled_at=scheduled_dt,
                title=title,
                target=target,
            )
        )

        return {
            "id": reminder_id_str,
            "title": reminder.title,
            "description": reminder.description,
            "scheduledAt": reminder.scheduled_at.isoformat(),
            "status": reminder.status,
            "target": reminder.target_device,
        }


@register_action("reminder.get")
async def handle_get_reminder(envelope: Envelope, data: dict[str, Any]) -> dict[str, Any]:
    reminder_id = data.get("id")
    if not reminder_id:
        raise ValueError("Field 'id' is required for reminder.get")

    async with get_db_session() as session:
        reminder = await get_reminder(session, reminder_id)
        if not reminder:
            raise ValueError(f"Reminder with id '{reminder_id}' not found.")

        return {
            "id": str(reminder.id),
            "title": reminder.title,
            "description": reminder.description,
            "scheduledAt": reminder.scheduled_at.isoformat(),
            "status": reminder.status,
            "target": reminder.target_device,
        }


@register_action("reminder.list")
async def handle_list_reminders(envelope: Envelope, data: dict[str, Any]) -> dict[str, Any]:
    status = data.get("status")
    limit = int(data.get("limit", 50))

    async with get_db_session() as session:
        reminders = await list_reminders(session, status=status, limit=limit)
        return {
            "count": len(reminders),
            "reminders": [
                {
                    "id": str(r.id),
                    "title": r.title,
                    "description": r.description,
                    "scheduledAt": r.scheduled_at.isoformat(),
                    "status": r.status,
                    "target": r.target_device,
                }
                for r in reminders
            ],
        }


@register_action("reminder.dismiss")
async def handle_dismiss_reminder(envelope: Envelope, data: dict[str, Any]) -> dict[str, Any]:
    reminder_id = data.get("id")
    if not reminder_id:
        raise ValueError("Field 'id' is required for reminder.dismiss")

    async with get_db_session() as session:
        reminder = await update_reminder_status(session, reminder_id, status="dismissed")
        if not reminder:
            raise ValueError(f"Reminder with id '{reminder_id}' not found.")
        return {"id": str(reminder.id), "status": reminder.status}


@register_action("reminder.complete")
async def handle_complete_reminder(envelope: Envelope, data: dict[str, Any]) -> dict[str, Any]:
    reminder_id = data.get("id")
    if not reminder_id:
        raise ValueError("Field 'id' is required for reminder.complete")

    async with get_db_session() as session:
        reminder = await update_reminder_status(session, reminder_id, status="completed")
        if not reminder:
            raise ValueError(f"Reminder with id '{reminder_id}' not found.")
        return {"id": str(reminder.id), "status": reminder.status}


@register_action("reminder.delete")
async def handle_delete_reminder(envelope: Envelope, data: dict[str, Any]) -> dict[str, Any]:
    reminder_id = data.get("id")
    if not reminder_id:
        raise ValueError("Field 'id' is required for reminder.delete")

    async with get_db_session() as session:
        deleted = await delete_reminder(session, reminder_id)
        return {"id": reminder_id, "deleted": deleted}
