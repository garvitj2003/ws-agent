from __future__ import annotations

import datetime
import uuid
from typing import Any

from sqlalchemy import delete, desc, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import ActionLog, Device, Event, Reminder, Task


def parse_iso_datetime(dt_str: str) -> datetime.datetime:
    """Parses ISO string to UTC datetime object."""
    try:
        dt = datetime.datetime.fromisoformat(dt_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=datetime.timezone.utc)
        return dt
    except Exception:
        return datetime.datetime.now(datetime.timezone.utc)


# =========================================================
# Reminder Repository
# =========================================================
async def create_reminder(
    session: AsyncSession,
    title: str,
    scheduled_at: str | datetime.datetime,
    description: str | None = None,
    target_device: str = "mobile",
    action_payload: dict[str, Any] | None = None,
) -> Reminder:
    if isinstance(scheduled_at, str):
        scheduled_dt = parse_iso_datetime(scheduled_at)
    else:
        scheduled_dt = scheduled_at

    reminder = Reminder(
        title=title,
        description=description,
        scheduled_at=scheduled_dt,
        status="pending",
        target_device=target_device,
        action_payload=action_payload or {},
    )
    session.add(reminder)
    await session.flush()
    await session.refresh(reminder)
    return reminder


async def get_reminder(session: AsyncSession, reminder_id: str | uuid.UUID) -> Reminder | None:
    if isinstance(reminder_id, str):
        reminder_id = uuid.UUID(reminder_id)
    return await session.get(Reminder, reminder_id)


async def list_reminders(
    session: AsyncSession,
    status: str | None = None,
    limit: int = 50,
) -> list[Reminder]:
    stmt = select(Reminder).order_by(Reminder.scheduled_at.asc()).limit(limit)
    if status:
        stmt = stmt.where(Reminder.status == status)
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def update_reminder_status(
    session: AsyncSession,
    reminder_id: str | uuid.UUID,
    status: str,  # 'pending', 'triggered', 'completed', 'dismissed', 'cancelled'
) -> Reminder | None:
    if isinstance(reminder_id, str):
        reminder_id = uuid.UUID(reminder_id)

    reminder = await session.get(Reminder, reminder_id)
    if reminder:
        reminder.status = status
        reminder.updated_at = datetime.datetime.now(datetime.timezone.utc)
        await session.flush()
        await session.refresh(reminder)
    return reminder


async def delete_reminder(session: AsyncSession, reminder_id: str | uuid.UUID) -> bool:
    if isinstance(reminder_id, str):
        reminder_id = uuid.UUID(reminder_id)

    stmt = delete(Reminder).where(Reminder.id == reminder_id)
    res = await session.execute(stmt)
    return (res.rowcount or 0) > 0


# =========================================================
# Task Repository
# =========================================================
async def create_task(
    session: AsyncSession,
    title: str,
    description: str | None = None,
    priority: str = "medium",
    due_date: str | datetime.datetime | None = None,
    metadata: dict[str, Any] | None = None,
) -> Task:
    due_dt = parse_iso_datetime(due_date) if isinstance(due_date, str) else due_date

    task = Task(
        title=title,
        description=description,
        priority=priority,
        status="pending",
        due_date=due_dt,
        metadata_json=metadata or {},
    )
    session.add(task)
    await session.flush()
    await session.refresh(task)
    return task


async def get_task(session: AsyncSession, task_id: str | uuid.UUID) -> Task | None:
    if isinstance(task_id, str):
        task_id = uuid.UUID(task_id)
    return await session.get(Task, task_id)


async def list_tasks(
    session: AsyncSession,
    status: str | None = None,
    priority: str | None = None,
    limit: int = 50,
) -> list[Task]:
    stmt = select(Task).order_by(desc(Task.created_at)).limit(limit)
    if status:
        stmt = stmt.where(Task.status == status)
    if priority:
        stmt = stmt.where(Task.priority == priority)
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def update_task_status(
    session: AsyncSession,
    task_id: str | uuid.UUID,
    status: str,
) -> Task | None:
    if isinstance(task_id, str):
        task_id = uuid.UUID(task_id)

    task = await session.get(Task, task_id)
    if task:
        task.status = status
        task.updated_at = datetime.datetime.now(datetime.timezone.utc)
        await session.flush()
        await session.refresh(task)
    return task


async def delete_task(session: AsyncSession, task_id: str | uuid.UUID) -> bool:
    if isinstance(task_id, str):
        task_id = uuid.UUID(task_id)

    stmt = delete(Task).where(Task.id == task_id)
    res = await session.execute(stmt)
    return (res.rowcount or 0) > 0


# =========================================================
# Event Repository
# =========================================================
async def create_event(
    session: AsyncSession,
    title: str,
    start_time: str | datetime.datetime,
    end_time: str | datetime.datetime | None = None,
    description: str | None = None,
    location: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> Event:
    start_dt = parse_iso_datetime(start_time) if isinstance(start_time, str) else start_time
    end_dt = parse_iso_datetime(end_time) if isinstance(end_time, str) else end_time

    event = Event(
        title=title,
        description=description,
        start_time=start_dt,
        end_time=end_dt,
        location=location,
        metadata_json=metadata or {},
    )
    session.add(event)
    await session.flush()
    await session.refresh(event)
    return event


async def list_events(
    session: AsyncSession,
    limit: int = 50,
) -> list[Event]:
    stmt = select(Event).order_by(Event.start_time.asc()).limit(limit)
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def delete_event(session: AsyncSession, event_id: str | uuid.UUID) -> bool:
    if isinstance(event_id, str):
        event_id = uuid.UUID(event_id)

    stmt = delete(Event).where(Event.id == event_id)
    res = await session.execute(stmt)
    return (res.rowcount or 0) > 0


# =========================================================
# Action Logger
# =========================================================
async def log_action(
    session: AsyncSession,
    action: str,
    source: str,
    target: str,
    status: str,
    envelope_id: str | None = None,
    payload: dict[str, Any] | None = None,
    error_message: str | None = None,
) -> ActionLog:
    log_entry = ActionLog(
        envelope_id=envelope_id,
        action=action,
        source=source,
        target=target,
        status=status,
        payload=payload or {},
        error_message=error_message,
    )
    session.add(log_entry)
    await session.flush()
    return log_entry
