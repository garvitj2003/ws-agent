from __future__ import annotations

import logging
from typing import Any, Callable, Dict, Tuple

from sqlalchemy.ext.asyncio import AsyncSession

from db.dynamic_repo import dynamic_repo
from models import Envelope

logger = logging.getLogger("dynamic_executor")


class DynamicOperationExecutor:
    """
    Dynamic Strategy Dispatcher (Command Registry Pattern):
    Eliminates all procedural if/elif/else branching in the orchestrator.
    Dispatches operations dynamically via dictionary registry lookup.
    """

    def __init__(self):
        self._registry: Dict[str, Callable] = {
            "overview": self._exec_overview,
            "create": self._exec_create,
            "search": self._exec_search,
            "update": self._exec_update,
            "delete": self._exec_delete,
            "device_action": self._exec_device_action,
            "general_chat": self._exec_chat,
            "chat": self._exec_chat,
        }

    async def execute(
        self,
        session: AsyncSession,
        decision: Any,
        user_text: str,
        server_instance: Any = None,
        envelope: Any = None,
    ) -> Tuple[str, Dict[str, Any]]:
        """Polymorphic execution entry point - 0 if/else statements."""
        handler = self._registry.get(decision.operation, self._exec_chat)
        return await handler(
            session=session,
            decision=decision,
            user_text=user_text,
            server_instance=server_instance,
            envelope=envelope,
        )

    # -------------------------------------------------------------
    # Dynamic Operation Strategies
    # -------------------------------------------------------------

    async def _exec_overview(
        self, session: AsyncSession, decision: Any, user_text: str, **kwargs
    ) -> Tuple[str, Dict[str, Any]]:
        overview = await dynamic_repo.get_agenda_overview(session)
        reminders = [r.get("title", "") for r in overview["reminders"]]
        tasks = [t.get("title", "") for t in overview["tasks"]]
        events = [e.get("title", "") for e in overview["events"]]

        if overview["total_items"] == 0:
            summary = "Your schedule is completely clear for today. No pending reminders, tasks, or events."
        else:
            parts = []
            if events:
                parts.append(f"Events: {', '.join(events)}")
            if reminders:
                parts.append(f"Reminders: {', '.join(reminders)}")
            if tasks:
                parts.append(f"Pending tasks: {', '.join(tasks)}")
            summary = f"Agenda overview: {'; '.join(parts)}."

        return summary, overview

    async def _exec_create(
        self, session: AsyncSession, decision: Any, user_text: str, **kwargs
    ) -> Tuple[str, Dict[str, Any]]:
        if decision.entity == "none":
            return "No target entity specified for creation.", {}

        data = decision.parameters.get("data") or {"title": user_text}
        created = await dynamic_repo.create(session, decision.entity, data)
        item_label = created.get("title") or created.get("content") or decision.entity
        entity_name = decision.entity[:-1] if decision.entity.endswith("s") else decision.entity
        summary = f"Created new {entity_name}: '{item_label}'."
        return summary, created

    async def _exec_search(
        self, session: AsyncSession, decision: Any, user_text: str, **kwargs
    ) -> Tuple[str, Dict[str, Any]]:
        if decision.entity == "none":
            return "No target entity specified for search.", {}

        query = decision.parameters.get("search_query", user_text)
        timeframe = decision.parameters.get("timeframe", "any")
        results = await dynamic_repo.search(
            session=session,
            entity=decision.entity,
            query=query,
            timeframe=timeframe,
            limit=5,
        )
        if results:
            found = [r.get("content") or r.get("title") for r in results]
            summary = f"Found matching {decision.entity}: {', '.join(str(x) for x in found)}."
        else:
            summary = f"No matching records found in {decision.entity} for query '{query}'."

        return summary, {"count": len(results), "results": results}

    async def _exec_update(
        self, session: AsyncSession, decision: Any, user_text: str, **kwargs
    ) -> Tuple[str, Dict[str, Any]]:
        if decision.entity == "none":
            return "No target entity specified for update.", {}

        query = decision.parameters.get("search_query", "")
        timeframe = decision.parameters.get("timeframe", "any")
        updates = decision.parameters.get("updates", {})

        res = await dynamic_repo.search_and_update(
            session=session,
            entity=decision.entity,
            search_query=query,
            timeframe=timeframe,
            updates=updates,
        )
        if res.get("found"):
            rec = res.get("record", {})
            item_label = rec.get("title") or rec.get("content") or "record"
            new_status = updates.get("status", "updated")
            entity_name = decision.entity[:-1] if decision.entity.endswith("s") else decision.entity
            summary = f"Updated {entity_name} '{item_label}' to status '{new_status}'."
        else:
            summary = f"Could not find any matching {decision.entity} to update for '{query}'."

        return summary, res

    async def _exec_delete(
        self, session: AsyncSession, decision: Any, user_text: str, **kwargs
    ) -> Tuple[str, Dict[str, Any]]:
        if decision.entity == "none":
            return "No target entity specified for delete.", {}

        target_id = decision.parameters.get("id")
        if not target_id:
            return "No record ID provided for deletion.", {}

        deleted = await dynamic_repo.delete(session, decision.entity, target_id)
        entity_name = decision.entity[:-1] if decision.entity.endswith("s") else decision.entity
        summary = f"Deleted {entity_name} '{target_id}'." if deleted else f"Record '{target_id}' not found."
        return summary, {"deleted": deleted}

    async def _exec_device_action(
        self, session: AsyncSession, decision: Any, user_text: str, server_instance: Any = None, envelope: Any = None, **kwargs
    ) -> Tuple[str, Dict[str, Any]]:
        if not server_instance or not envelope:
            return "Server routing not available.", {}

        target_device = decision.target_device if decision.target_device != "server" else "laptop"
        act_env = Envelope.create(
            type="action",
            source=envelope.source,
            target=target_device,
            body={"action": "exec", "command": user_text},
        )
        recipients = server_instance.registry.resolve_targets(target_device)
        if recipients:
            await server_instance.route_envelope(None, act_env)
            return f"Dispatched execution command to {target_device}.", {"target": target_device, "command": user_text}
        return f"{target_device.capitalize()} is currently offline.", {"target": target_device, "status": "offline"}

    async def _exec_chat(
        self, session: AsyncSession, decision: Any, user_text: str, **kwargs
    ) -> Tuple[str, Dict[str, Any]]:
        return "Conversational chat.", {}


executor = DynamicOperationExecutor()
