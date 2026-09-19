from __future__ import annotations

import logging
from typing import Any

from actions.dispatcher import register_action
from db.repository import create_event, delete_event, list_events
from db.session import get_db_session
from models import Envelope

logger = logging.getLogger("action_events")


@register_action("event.create")
async def handle_create_event(envelope: Envelope, data: dict[str, Any]) -> dict[str, Any]:
    title = data.get("title")
    if not title:
        raise ValueError("Field 'title' is required for event.create")

    start_time = data.get("startTime") or data.get("start_time")
    if not start_time:
        raise ValueError("Field 'startTime' is required for event.create")

    end_time = data.get("endTime") or data.get("end_time")
    description = data.get("description")
    location = data.get("location")

    async with get_db_session() as session:
        event = await create_event(
            session=session,
            title=title,
            start_time=start_time,
            end_time=end_time,
            description=description,
            location=location,
            metadata=data.get("metadata", {}),
        )
        return {
            "id": str(event.id),
            "title": event.title,
            "description": event.description,
            "startTime": event.start_time.isoformat(),
            "endTime": event.end_time.isoformat() if event.end_time else None,
            "location": event.location,
        }


@register_action("event.list")
async def handle_list_events(envelope: Envelope, data: dict[str, Any]) -> dict[str, Any]:
    limit = int(data.get("limit", 50))
    async with get_db_session() as session:
        events = await list_events(session, limit=limit)
        return {
            "count": len(events),
            "events": [
                {
                    "id": str(e.id),
                    "title": e.title,
                    "description": e.description,
                    "startTime": e.start_time.isoformat(),
                    "endTime": e.end_time.isoformat() if e.end_time else None,
                    "location": e.location,
                }
                for e in events
            ],
        }


@register_action("event.delete")
async def handle_delete_event(envelope: Envelope, data: dict[str, Any]) -> dict[str, Any]:
    event_id = data.get("id")
    if not event_id:
        raise ValueError("Field 'id' is required for event.delete")

    async with get_db_session() as session:
        deleted = await delete_event(session, event_id)
        return {"id": event_id, "deleted": deleted}
