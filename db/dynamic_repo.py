from __future__ import annotations

import datetime
import logging
import time
from typing import Any, Dict, List, Optional, Type

from sqlalchemy import DateTime, Integer, String, Text, delete, desc, or_, select, update
from sqlalchemy.dialects import postgresql
from sqlalchemy.dialects.postgresql import JSONB, UUID as PgUUID
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import ActionLog, Base, Device, Event, Memory, Reminder, Task

logger = logging.getLogger("dynamic_repo")


def compile_statement(stmt) -> Dict[str, Any]:
    """Compiles a SQLAlchemy statement into formatted SQL string and bound parameters."""
    try:
        compiled = stmt.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"render_postcompile": True}
        )
        params = {}
        for k, v in (compiled.params or {}).items():
            if isinstance(v, (datetime.datetime, datetime.date)):
                params[k] = v.isoformat()
            elif isinstance(v, uuid.UUID):
                params[k] = str(v)
            else:
                params[k] = v
        return {"sql": str(compiled), "params": params}
    except Exception as e:
        return {"sql": str(stmt), "params": {}}


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
        self.last_trace: Dict[str, Any] = {}

    def get_last_trace(self) -> Dict[str, Any]:
        """Returns the most recent database execution telemetry trace."""
        return self.last_trace

    def get_available_entities(self) -> List[str]:
        """Returns unique list of entity collection names."""
        return ["reminders", "tasks", "events", "memories", "devices"]

    def get_model(self, entity_name: str) -> Type[Base]:
        key = entity_name.lower().strip()
        if key not in self._registry:
            raise ValueError(f"Unknown database entity '{entity_name}'. Available: {self.get_available_entities()}")
        return self._registry[key]

    def _auto_cast_fields(self, model_cls: Type[Base], raw_data: Dict[str, Any]) -> Dict[str, Any]:
        """Auto-casts input values to match the column types of the SQLAlchemy model with smart fallback defaults."""
        clean_data: Dict[str, Any] = {}
        table = model_cls.__table__
        now = datetime.datetime.now(datetime.timezone.utc)

        for col in table.columns:
            col_name = col.name
            # Accept camelCase or snake_case
            camel_name = "".join(word.capitalize() if i > 0 else word for i, word in enumerate(col_name.split("_")))
            val = raw_data.get(col_name) if col_name in raw_data else raw_data.get(camel_name)

            # Synonym mappings for polymorphic model fields
            if val is None:
                if col_name == "content":
                    val = raw_data.get("title") or raw_data.get("text") or raw_data.get("raw_text")
                elif col_name == "title":
                    val = raw_data.get("content") or raw_data.get("text") or raw_data.get("raw_text")
                elif col_name in ("scheduled_at", "due_at", "start_time"):
                    val = raw_data.get("scheduled_at") or raw_data.get("due_at") or raw_data.get("time")
                    # If field is non-nullable and no time was provided, auto-default to 1 hour from now
                    if val is None and not col.nullable:
                        val = now + datetime.timedelta(hours=1)
                elif col_name == "status" and not col.nullable:
                    val = "pending"
                elif col_name == "category" and not col.nullable:
                    val = "general"

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
                    elif isinstance(val, (datetime.datetime, datetime.date)):
                        if isinstance(val, datetime.datetime) and val.tzinfo is None:
                            val = val.replace(tzinfo=datetime.timezone.utc)
                        clean_data[col_name] = val
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
        """Universal dynamic insert with trace recording."""
        start_t = time.perf_counter()
        model_cls = self.get_model(entity)
        clean_data = self._auto_cast_fields(model_cls, data)
        table_name = model_cls.__tablename__
        cols = list(clean_data.keys())
        params_str = ", ".join(f":{c}" for c in cols)
        sql_sim = f"INSERT INTO {table_name} ({', '.join(cols)}) VALUES ({params_str}) RETURNING *"

        try:
            instance = model_cls(**clean_data)
            session.add(instance)
            await session.flush()
            await session.refresh(instance)
            serialized = self._serialize_record(instance)
            elapsed_ms = round((time.perf_counter() - start_t) * 1000, 2)

            self.last_trace = {
                "entity": entity,
                "operation": "create",
                "sql_executed": sql_sim,
                "sql_parameters": {k: (v.isoformat() if isinstance(v, (datetime.datetime, datetime.date)) else str(v)) for k, v in clean_data.items()},
                "latency_ms": elapsed_ms,
                "rows_affected": 1,
                "result_summary": f"Created 1 {entity[:-1] if entity.endswith('s') else entity} record",
            }
            return serialized
        except Exception as exc:
            elapsed_ms = round((time.perf_counter() - start_t) * 1000, 2)
            self.last_trace = {
                "entity": entity,
                "operation": "create",
                "sql_executed": sql_sim,
                "sql_parameters": {k: str(v) for k, v in clean_data.items()},
                "latency_ms": elapsed_ms,
                "rows_affected": 0,
                "result_summary": f"Database error: {exc}",
            }
            raise

    async def get(self, session: AsyncSession, entity: str, record_id: str | uuid.UUID) -> Optional[Dict[str, Any]]:
        """Universal dynamic fetch by ID."""
        start_t = time.perf_counter()
        model_cls = self.get_model(entity)
        if isinstance(record_id, str):
            try:
                record_id = uuid.UUID(record_id)
            except ValueError:
                pass
        stmt = select(model_cls).where(getattr(model_cls, "id") == record_id)
        compiled = compile_statement(stmt)
        instance = await session.get(model_cls, record_id)
        elapsed_ms = round((time.perf_counter() - start_t) * 1000, 2)

        self.last_trace = {
            "entity": entity,
            "operation": "get",
            "sql_executed": compiled["sql"],
            "sql_parameters": compiled["params"],
            "latency_ms": elapsed_ms,
            "rows_affected": 1 if instance else 0,
            "result_summary": "Record found" if instance else "Record not found",
        }
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
        start_t = time.perf_counter()
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

        final_stmt = stmt.limit(limit)
        compiled = compile_statement(final_stmt)
        result = await session.execute(final_stmt)
        records = result.scalars().all()
        elapsed_ms = round((time.perf_counter() - start_t) * 1000, 2)

        serialized = [self._serialize_record(r) for r in records]
        self.last_trace = {
            "entity": entity,
            "operation": "search",
            "sql_executed": compiled["sql"],
            "sql_parameters": compiled["params"],
            "latency_ms": elapsed_ms,
            "rows_affected": len(serialized),
            "result_summary": f"Retrieved {len(serialized)} matching {entity} records",
        }
        return serialized

    async def update(
        self,
        session: AsyncSession,
        entity: str,
        record_id: str | uuid.UUID,
        updates: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        """Universal dynamic update by ID."""
        start_t = time.perf_counter()
        model_cls = self.get_model(entity)
        if isinstance(record_id, str):
            try:
                record_id = uuid.UUID(record_id)
            except ValueError:
                pass

        instance = await session.get(model_cls, record_id)
        if not instance:
            self.last_trace = {
                "entity": entity,
                "operation": "update",
                "sql_executed": f"SELECT * FROM {model_cls.__tablename__} WHERE id = '{record_id}'",
                "sql_parameters": {"id": str(record_id)},
                "latency_ms": round((time.perf_counter() - start_t) * 1000, 2),
                "rows_affected": 0,
                "result_summary": "Record not found for update",
            }
            return None

        clean_updates = self._auto_cast_fields(model_cls, updates)
        if hasattr(model_cls, "updated_at"):
            clean_updates["updated_at"] = datetime.datetime.now(datetime.timezone.utc)

        for k, v in clean_updates.items():
            setattr(instance, k, v)

        await session.flush()
        await session.refresh(instance)
        elapsed_ms = round((time.perf_counter() - start_t) * 1000, 2)
        serialized = self._serialize_record(instance)

        set_clauses = ", ".join(f"{k} = :{k}" for k in clean_updates.keys())
        sql_sim = f"UPDATE {model_cls.__tablename__} SET {set_clauses} WHERE id = :id"
        self.last_trace = {
            "entity": entity,
            "operation": "update",
            "sql_executed": sql_sim,
            "sql_parameters": {
                **{k: (v.isoformat() if isinstance(v, (datetime.datetime, datetime.date)) else str(v)) for k, v in clean_updates.items()},
                "id": str(record_id),
            },
            "latency_ms": elapsed_ms,
            "rows_affected": 1,
            "result_summary": f"Updated {entity[:-1] if entity.endswith('s') else entity} '{record_id}'",
        }
        return serialized

    async def search_and_update(
        self,
        session: AsyncSession,
        entity: str,
        search_query: str,
        timeframe: str = "any",
        updates: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Finds matching record by query/timeframe and applies updates."""
        start_t = time.perf_counter()
        matches = await self.search(
            session=session,
            entity=entity,
            query=search_query,
            filters={"status": "pending"} if hasattr(self.get_model(entity), "status") else None,
            timeframe=timeframe,
            limit=1,
        )
        search_trace = dict(self.last_trace)
        if not matches:
            self.last_trace = {
                "entity": entity,
                "operation": "search_and_update",
                "sql_executed": search_trace.get("sql_executed", ""),
                "sql_parameters": search_trace.get("sql_parameters", {}),
                "latency_ms": round((time.perf_counter() - start_t) * 1000, 2),
                "rows_affected": 0,
                "result_summary": f"No pending {entity} matched '{search_query}'",
            }
            return {"found": False, "search_query": search_query, "timeframe": timeframe}

        target_id = matches[0]["id"]
        updated = await self.update(session, entity, target_id, updates or {})
        update_trace = dict(self.last_trace)

        combined_sql = f"{search_trace.get('sql_executed', '')}\n--> {update_trace.get('sql_executed', '')}"
        self.last_trace = {
            "entity": entity,
            "operation": "search_and_update",
            "sql_executed": combined_sql,
            "sql_parameters": {**search_trace.get("sql_parameters", {}), **update_trace.get("sql_parameters", {})},
            "latency_ms": round((time.perf_counter() - start_t) * 1000, 2),
            "rows_affected": 1,
            "result_summary": f"Found & updated 1 {entity[:-1] if entity.endswith('s') else entity} matching '{search_query}'",
        }
        return {"found": True, "record": updated}

    async def delete(self, session: AsyncSession, entity: str, record_id: str | uuid.UUID) -> bool:
        """Universal dynamic delete by ID."""
        start_t = time.perf_counter()
        model_cls = self.get_model(entity)
        if isinstance(record_id, str):
            try:
                record_id = uuid.UUID(record_id)
            except ValueError:
                pass
        stmt = delete(model_cls).where(getattr(model_cls, "id") == record_id)
        compiled = compile_statement(stmt)
        res = await session.execute(stmt)
        elapsed_ms = round((time.perf_counter() - start_t) * 1000, 2)
        rowcount = res.rowcount or 0

        self.last_trace = {
            "entity": entity,
            "operation": "delete",
            "sql_executed": compiled["sql"],
            "sql_parameters": compiled["params"],
            "latency_ms": elapsed_ms,
            "rows_affected": rowcount,
            "result_summary": f"Deleted {rowcount} record(s) from {entity}",
        }
        return rowcount > 0

    async def get_agenda_overview(self, session: AsyncSession) -> Dict[str, Any]:
        """Universal schedule & daily briefing aggregator."""
        start_t = time.perf_counter()
        reminders = await self.search(session, "reminders", filters={"status": "pending"}, limit=10)
        tasks = await self.search(session, "tasks", filters={"status": "pending"}, limit=10)
        events = await self.search(session, "events", limit=10)
        memories = await self.search(session, "memories", limit=5)
        elapsed_ms = round((time.perf_counter() - start_t) * 1000, 2)

        self.last_trace = {
            "entity": "all_agenda_entities",
            "operation": "overview",
            "sql_executed": "SELECT * FROM reminders WHERE status='pending'; SELECT * FROM tasks WHERE status='pending'; SELECT * FROM events; SELECT * FROM memories;",
            "sql_parameters": {"status": "pending"},
            "latency_ms": elapsed_ms,
            "rows_affected": len(reminders) + len(tasks) + len(events),
            "result_summary": f"Aggregated {len(reminders)} reminders, {len(tasks)} tasks, {len(events)} events",
        }

        return {
            "reminders": reminders,
            "tasks": tasks,
            "events": events,
            "recent_memories": memories,
            "total_items": len(reminders) + len(tasks) + len(events),
        }


# Singleton instance
dynamic_repo = DynamicEntityRepository()
