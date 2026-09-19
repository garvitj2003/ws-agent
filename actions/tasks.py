from __future__ import annotations

import logging
from typing import Any

from actions.dispatcher import register_action
from db.repository import (
    create_task,
    delete_task,
    get_task,
    list_tasks,
    update_task_status,
)
from db.session import get_db_session
from models import Envelope

logger = logging.getLogger("action_tasks")


@register_action("task.create")
async def handle_create_task(envelope: Envelope, data: dict[str, Any]) -> dict[str, Any]:
    title = data.get("title")
    if not title:
        raise ValueError("Field 'title' is required for task.create")

    description = data.get("description")
    priority = data.get("priority", "medium")
    due_date = data.get("dueDate") or data.get("due_date")

    async with get_db_session() as session:
        task = await create_task(
            session=session,
            title=title,
            description=description,
            priority=priority,
            due_date=due_date,
            metadata=data.get("metadata", {}),
        )
        return {
            "id": str(task.id),
            "title": task.title,
            "description": task.description,
            "priority": task.priority,
            "status": task.status,
            "dueDate": task.due_date.isoformat() if task.due_date else None,
        }


@register_action("task.get")
async def handle_get_task(envelope: Envelope, data: dict[str, Any]) -> dict[str, Any]:
    task_id = data.get("id")
    if not task_id:
        raise ValueError("Field 'id' is required for task.get")

    async with get_db_session() as session:
        task = await get_task(session, task_id)
        if not task:
            raise ValueError(f"Task '{task_id}' not found.")
        return {
            "id": str(task.id),
            "title": task.title,
            "description": task.description,
            "priority": task.priority,
            "status": task.status,
            "dueDate": task.due_date.isoformat() if task.due_date else None,
        }


@register_action("task.list")
async def handle_list_tasks(envelope: Envelope, data: dict[str, Any]) -> dict[str, Any]:
    status = data.get("status")
    priority = data.get("priority")
    limit = int(data.get("limit", 50))

    async with get_db_session() as session:
        tasks = await list_tasks(session, status=status, priority=priority, limit=limit)
        return {
            "count": len(tasks),
            "tasks": [
                {
                    "id": str(t.id),
                    "title": t.title,
                    "description": t.description,
                    "priority": t.priority,
                    "status": t.status,
                    "dueDate": t.due_date.isoformat() if t.due_date else None,
                }
                for t in tasks
            ],
        }


@register_action("task.complete")
async def handle_complete_task(envelope: Envelope, data: dict[str, Any]) -> dict[str, Any]:
    task_id = data.get("id")
    if not task_id:
        raise ValueError("Field 'id' is required for task.complete")

    async with get_db_session() as session:
        task = await update_task_status(session, task_id, status="completed")
        if not task:
            raise ValueError(f"Task '{task_id}' not found.")
        return {"id": str(task.id), "status": task.status}


@register_action("task.delete")
async def handle_delete_task(envelope: Envelope, data: dict[str, Any]) -> dict[str, Any]:
    task_id = data.get("id")
    if not task_id:
        raise ValueError("Field 'id' is required for task.delete")

    async with get_db_session() as session:
        deleted = await delete_task(session, task_id)
        return {"id": task_id, "deleted": deleted}
