from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any, Dict

from db.repository import log_action
from db.session import get_db_session
from models import Envelope

logger = logging.getLogger("action_dispatcher")

ActionHandler = Callable[[Envelope, Dict[str, Any]], Awaitable[Dict[str, Any]]]

_HANDLERS: Dict[str, ActionHandler] = {}


def register_action(action_name: str):
    """Decorator to register an action handler function."""
    def decorator(func: ActionHandler) -> ActionHandler:
        _HANDLERS[action_name] = func
        return func
    return decorator


async def dispatch_action(envelope: Envelope, server_instance=None) -> Envelope:
    """Dispatches incoming action envelope to registered handler and returns result envelope."""
    action_name = envelope.body.get("action")
    action_data = envelope.body.get("data") or {}

    if not action_name:
        return Envelope.create(
            type="action_result",
            source="server:action-dispatcher",
            target=envelope.source,
            body={
                "request_id": envelope.id,
                "status": "error",
                "error": "Field 'action' is required in action envelope body.",
            },
        )

    handler = _HANDLERS.get(action_name)
    if not handler:
        logger.warning(f"Unknown action requested: '{action_name}' from '{envelope.source}'")
        return Envelope.create(
            type="action_result",
            source="server:action-dispatcher",
            target=envelope.source,
            body={
                "action": action_name,
                "request_id": envelope.id,
                "status": "error",
                "error": f"Action '{action_name}' is not recognized.",
            },
        )

    try:
        result_data = await handler(envelope, action_data)
        status = "success"
        error_msg = None

        # Log action to DB
        async with get_db_session() as session:
            await log_action(
                session=session,
                action=action_name,
                source=envelope.source,
                target=envelope.target,
                status=status,
                envelope_id=envelope.id,
                payload=action_data,
            )

        return Envelope.create(
            type="action_result",
            source="server:action-dispatcher",
            target=envelope.source,
            body={
                "action": action_name,
                "request_id": envelope.id,
                "status": "success",
                "data": result_data,
            },
        )

    except Exception as exc:
        logger.error(f"Error executing action '{action_name}': {exc}", exc_info=True)
        status = "error"
        error_msg = str(exc)

        async with get_db_session() as session:
            await log_action(
                session=session,
                action=action_name,
                source=envelope.source,
                target=envelope.target,
                status=status,
                envelope_id=envelope.id,
                payload=action_data,
                error_message=error_msg,
            )

        return Envelope.create(
            type="action_result",
            source="server:action-dispatcher",
            target=envelope.source,
            body={
                "action": action_name,
                "request_id": envelope.id,
                "status": "error",
                "error": error_msg,
            },
        )
