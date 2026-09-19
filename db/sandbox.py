from __future__ import annotations

import logging
from typing import Any

import sqlparse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger("sql_sandbox")

DISALLOWED_KEYWORDS = {
    "INSERT",
    "UPDATE",
    "DELETE",
    "DROP",
    "ALTER",
    "TRUNCATE",
    "GRANT",
    "REVOKE",
    "CREATE",
    "REPLACE",
    "EXECUTE",
    "CALL",
    "VACUUM",
    "REINDEX",
    "LOCK",
}


def validate_sql_safety(query_str: str) -> None:
    """Validates that query is purely a read-only SELECT statement."""
    parsed = sqlparse.parse(query_str)
    if not parsed:
        raise ValueError("Empty SQL query provided.")

    if len(parsed) > 1:
        raise ValueError("Multiple SQL statements are not permitted in sandboxed execution.")

    statement = parsed[0]
    first_token = statement.get_type().upper()

    if first_token not in ("SELECT", "UNKNOWN"):
        # Unknown can be CTE (WITH ... SELECT)
        normalized = query_str.strip().upper()
        if not (normalized.startswith("SELECT") or normalized.startswith("WITH")):
            raise ValueError(f"Only SELECT queries are allowed. Attempted statement type: {first_token}")

    for token in statement.flatten():
        val = token.value.upper()
        if val in DISALLOWED_KEYWORDS:
            raise ValueError(f"Disallowed keyword detected in query: '{val}'")


async def execute_safe_query(
    session: AsyncSession,
    query_str: str,
    max_rows: int = 50,
) -> dict[str, Any]:
    """Executes a validated read-only query safely with timeout and row limits."""
    validate_sql_safety(query_str)

    # Set statement timeout to 3000ms for safety
    await session.execute(text("SET LOCAL statement_timeout = '3000ms'"))

    result = await session.execute(text(query_str))
    rows = result.fetchmany(max_rows)
    columns = list(result.keys())

    formatted_rows = [
        {col: val.isoformat() if hasattr(val, "isoformat") else str(val) if val is not None else None for col, val in zip(columns, row)}
        for row in rows
    ]

    return {
        "columns": columns,
        "row_count": len(formatted_rows),
        "truncated": len(formatted_rows) == max_rows,
        "rows": formatted_rows,
    }
