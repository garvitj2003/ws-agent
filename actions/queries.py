from __future__ import annotations

import logging
from typing import Any

from actions.dispatcher import register_action
from db.sandbox import execute_safe_query
from db.session import get_db_session
from models import Envelope

logger = logging.getLogger("action_queries")


@register_action("query.sql")
async def handle_query_sql(envelope: Envelope, data: dict[str, Any]) -> dict[str, Any]:
    query_str = data.get("query")
    if not query_str:
        raise ValueError("Field 'query' is required for query.sql")

    max_rows = int(data.get("maxRows", 50))

    async with get_db_session() as session:
        result = await execute_safe_query(session, query_str=query_str, max_rows=max_rows)
        return result
