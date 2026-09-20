from __future__ import annotations

import datetime
import logging
import uuid
from typing import Any, Dict, List, Optional, Type

from sqlalchemy import DateTime, Integer, String, Text, delete, desc, or_, select, update
from sqlalchemy.dialects.postgresql import JSONB, UUID as PgUUID
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import ActionLog, Base, Device, Event, Memory, Reminder, Task

logger = logging.getLogger("dynamic_repo")


class DynamicEntityRepository:
    def __init__(self):
        # Register all known models and their plural/singular aliases
        self._registry: Dict[str, Type[Base]] = {
            "reminders": Reminder,
            "reminder": Reminder,
            "tasks": Task,
            "task": Task,
            "events": Event,
            "event": Event,
            "memories": Memory,
            "memory": Memory,
            "devices": Device,
            "device": Device,
            "action_logs": ActionLog,
            "action_log": ActionLog,
        }

    def get_available_entities(self) -> List[str]:
        """Returns unique list of entity collection names."""
        return ["reminders", "tasks", "events", "memories", "devices"]

    def get_model(self, entity_name: str) -> Type[Base]:
        key = entity_name.lower().strip()
        if key not in self._registry:
            raise ValueError(f"Unknown database entity '{entity_name}'. Available: {self.get_available_entities()}")
        return self._registry[key]

    def _auto_cast_fields(self, model_cls: Type[Base], raw_data: Dict[str, Any]) -> Dict[str, Any]:
        """Auto-casts input values to match the column types of the SQLAlchemy model."""
        clean_data: Dict[str, Any] = {}
        table = model_cls.__table__

        for col in table.columns:
            col_name = col.name
            # Accept camelCase or snake_case
            camel_name = "".join(word.capitalize() if i > 0 else word for i, word in enumerate(col_name.split("_")))
            val = raw_data.get(col_name) if col_name in raw_data else raw_data.get(camel_name)

            if val is None:
                continue

            # Auto-cast by column type
            try:
                if isinstance(col.type, DateTime):
                    if isinstance(val, str):
                        dt = datetime.datetime.fromisoformat(val)
                        if dt.tzinfo is None:
                            dt = dt.replace(tzinfo=datetime.timezone.utc)
                        clean_data[col_name] = dt
                    else:
                        clean_data[col_name] = val

                elif isinstance(col.type, PgUUID):
                    if isinstance(val, str):
                        clean_data[col_name] = uuid.UUID(val)
                    else:
                        clean_data[col_name] = val

                elif isinstance(col.type, (String, Text)):
                    clean_data[col_name] = str(val)

                elif isinstance(col.type, Integer):
                    clean_data[col_name] = int(val)

                elif isinstance(col.type, JSONB):
                    clean_data[col_name] = val if isinstance(val, (dict, list)) else {"data": val}

                else:
                    clean_data[col_name] = val

            except Exception as e:
                logger.warning(f"Could not auto-cast column '{col_name}' with value '{val}': {e}")
                clean_data[col_name] = val

        return clean_data

    def _serialize_record(self, record: Any) -> Dict[str, Any]:
        """Converts an ORM model instance into a JSON-serializable dictionary."""
        data: Dict[str, Any] = {}
        for col in record.__table__.columns:
            val = getattr(record, col.name, None)
            if isinstance(val, (datetime.datetime, datetime.date)):
                data[col.name] = val.isoformat()
            elif isinstance(val, uuid.UUID):
                data[col.name] = str(val)
            else:
                data[col.name] = val
        return data

    async def create(self, session: AsyncSession, entity: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """Universal dynamic insert."""
        model_cls = self.get_model(entity)
        clean_data = self._auto_cast_fields(model_cls, data)
        instance = model_cls(**clean_data)
        session.add(instance)
        await session.flush()
        await session.refresh(instance)
        return self._serialize_record(instance)

    async def get(self, session: AsyncSession, entity: str, record_id: str | uuid.UUID) -> Optional[Dict[str, Any]]:
        """Universal dynamic fetch by ID."""
        model_cls = self.get_model(entity)
        if isinstance(record_id, str):
            try:
                record_id = uuid.UUID(record_id)
            except ValueError:
                pass
        instance = await session.get(model_cls, record_id)
        return self._serialize_record(instance) if instance else None

    async def search(
        self,
        session: AsyncSession,
        entity: str,
        query: str = "",
        filters: Optional[Dict[str, Any]] = None,
        timeframe: str = "any",
        limit: int = 20,
    ) -> List[Dict[str, Any]]:
        """
        Universal dynamic search:
        - Auto-filters exact column equalities
        - Auto-applies ILIKE across all string/text columns
        - Auto-applies date filtering (today, tomorrow) on DateTime columns
        """
        model_cls = self.get_model(entity)
        table = model_cls.__table__
        stmt = select(model_cls)

        # 1. Apply exact filters
        if filters:
            for key, val in filters.items():
                if hasattr(model_cls, key):
                    stmt = stmt.where(getattr(model_cls, key) == val)

        # 2. Apply timeframe date filter on any DateTime column
        now = datetime.datetime.now(datetime.timezone.utc)
        date_cols = [c for c in table.columns if isinstance(c.type, DateTime) and c.name not in ("created_at", "updated_at")]
        if date_cols and timeframe in ("today", "tomorrow"):
            target_date_col = getattr(model_cls, date_cols[0].name)
            if timeframe == "today":
                start_dt = now.replace(hour=0, minute=0, second=0, microsecond=0)
                end_dt = start_dt + datetime.timedelta(days=1)
                stmt = stmt.where(target_date_col >= start_dt, target_date_col < end_dt)
            elif timeframe == "tomorrow":
                start_dt = (now + datetime.timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
                end_dt = start_dt + datetime.timedelta(days=1)
                stmt = stmt.where(target_date_col >= start_dt, target_date_col < end_dt)

        # 3. Apply Fuzzy Text Search (ILIKE across all string/text columns)
        if query:
            text_cols = [getattr(model_cls, c.name) for c in table.columns if isinstance(c.type, (String, Text))]
            if text_cols:
                pattern = f"%{query.strip()}%"
                stmt = stmt.where(or_(*[col.ilike(pattern) for col in text_cols]))

        # 4. Default ordering
        if hasattr(model_cls, "scheduled_at"):
            stmt = stmt.order_by(getattr(model_cls, "scheduled_at").asc())
        elif hasattr(model_cls, "created_at"):
            stmt = stmt.order_by(getattr(model_cls, "created_at").desc())

        result = await session.execute(stmt.limit(limit))
        records = result.scalars().all()
        return [self._serialize_record(r) for r in records]

    async def update(
        self,
        session: AsyncSession,
        entity: str,
        record_id: str | uuid.UUID,
        updates: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        """Universal dynamic update by ID."""
        model_cls = self.get_model(entity)
        if isinstance(record_id, str):
            try:
                record_id = uuid.UUID(record_id)
            except ValueError:
                pass

        instance = await session.get(model_cls, record_id)
        if not instance:
            return None

        clean_updates = self._auto_cast_fields(model_cls, updates)
        if hasattr(model_cls, "updated_at"):
            clean_updates["updated_at"] = datetime.datetime.now(datetime.timezone.utc)

        for k, v in clean_updates.items():
            setattr(instance, k, v)

        await session.flush()
        await session.refresh(instance)
        return self._serialize_record(instance)

    async def search_and_update(
        self,
        session: AsyncSession,
        entity: str,
        search_query: str,
        timeframe: str = "any",
        updates: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Finds matching record by query/timeframe and applies updates."""
        matches = await self.search(
            session=session,
            entity=entity,
            query=search_query,
            filters={"status": "pending"} if hasattr(self.get_model(entity), "status") else None,
            timeframe=timeframe,
            limit=1,
        )
        if not matches:
            return {"found": False, "search_query": search_query, "timeframe": timeframe}

        target_id = matches[0]["id"]
        updated = await self.update(session, entity, target_id, updates or {})
        return {"found": True, "record": updated}

    async def delete(self, session: AsyncSession, entity: str, record_id: str | uuid.UUID) -> bool:
        """Universal dynamic delete by ID."""
        model_cls = self.get_model(entity)
        if isinstance(record_id, str):
            try:
                record_id = uuid.UUID(record_id)
            except ValueError:
                pass
        stmt = delete(model_cls).where(getattr(model_cls, "id") == record_id)
        res = await session.execute(stmt)
        return (res.rowcount or 0) > 0

    async def get_agenda_overview(self, session: AsyncSession) -> Dict[str, Any]:
        """Universal schedule & daily briefing aggregator."""
        reminders = await self.search(session, "reminders", filters={"status": "pending"}, limit=10)
        tasks = await self.search(session, "tasks", filters={"status": "pending"}, limit=10)
        events = await self.search(session, "events", limit=10)
        memories = await self.search(session, "memories", limit=5)

        return {
            "reminders": reminders,
            "tasks": tasks,
            "events": events,
            "recent_memories": memories,
            "total_items": len(reminders) + len(tasks) + len(events),
        }


# Singleton instance
dynamic_repo = DynamicEntityRepository()
