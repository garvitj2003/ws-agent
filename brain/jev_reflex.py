from __future__ import annotations

import datetime
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from groq import AsyncGroq
from typesafe_sdk import AsyncTypeSafeClient, Choice, Noul, Score

from brain.config import GROQ_API_KEY, TYPESAFE_API_KEY, has_groq_api_key, has_typesafe_api_key
from db.dynamic_repo import dynamic_repo

logger = logging.getLogger("jev_reflex")


@dataclass
class JevDecision:
    operation: str  # "create", "search", "update", "delete", "overview", "device_action", "general_chat"
    entity: str  # "reminders", "tasks", "events", "memories", "none"
    target_device: str  # "server", "mobile", "laptop", "broadcast"
    is_destructive: bool
    urgency: str  # "routine", "important", "emergency"
    parameters: Dict[str, Any] = field(default_factory=dict)
    confidence: float = 1.0
    latency_ms: float = 0.0


async def evaluate_intent_with_jev(
    user_input: str,
    source_device: str = "mobile",
    context: Optional[Dict[str, Any]] = None,
) -> JevDecision:
    """
    100% Dynamic Semantic Pipeline (System 1 Reflex + Dynamic Parameter Extraction):
    1. Fast Safety & Intent Classification via Jev / TypeSafe AI.
    2. Dynamic Semantic Parameter Extraction via Fast LLM (Zero hardcoded regexes/keywords).
    """
    start_t = time.perf_counter()
    now_utc = datetime.datetime.now(datetime.timezone.utc)
    now_iso = now_utc.strftime("%Y-%m-%dT%H:%M:%SZ (%A)")

    operation = "general_chat"
    entity = "none"
    target_device = "server"
    is_destructive = False
    urgency = "routine"

    # Step 1: System 1 Classification via TypeSafe (or fast LLM if TypeSafe key not present)
    if has_typesafe_api_key():
        try:
            async with AsyncTypeSafeClient(api_key=TYPESAFE_API_KEY) as client:
                state = {
                    "user_message": user_input,
                    "source_device": source_device,
                    "current_time": now_iso,
                    "available_entities": dynamic_repo.get_available_entities(),
                    "context": context or {},
                }

                response = await client.system_one(
                    state=state,
                    questions={
                        "operation": Choice(
                            instructions="What fundamental operation is the user requesting?",
                            criteria={
                                "create": "User wants to create, save, remember, schedule, or add new data/reminder/task",
                                "search": "User wants to look up, recall, find, ask about, or query existing data/memory/note",
                                "update": "User wants to modify, cancel, dismiss, reschedule, complete, or mark data",
                                "delete": "User wants to permanently delete or remove a specific record",
                                "overview": "User is asking for schedule summary, daily briefing, or what is planned/scheduled for today/tomorrow",
                                "device_action": "User wants to execute a terminal command on laptop or server",
                                "general_chat": "Casual greeting, chit-chat, or general knowledge question",
                            },
                        ),
                        "entity": Choice(
                            instructions="Which database entity collection does this request relate to?",
                            criteria={
                                "reminders": "Time-based reminders, alarms, calls, notifications",
                                "tasks": "Todo items, work tickets, action items",
                                "events": "Calendar events, schedule appointments",
                                "memories": "Personal facts, preferences, user knowledge, stored notes",
                                "none": "Not related to any specific database entity",
                            },
                        ),
                        "target_device": Choice(
                            instructions="Which device should handle or receive this action?",
                            criteria={
                                "server": "Server handles database storage, agenda, or agent reasoning",
                                "mobile": "Mobile phone",
                                "laptop": "User's laptop/MacBook",
                                "broadcast": "All connected devices",
                            },
                        ),
                        "is_destructive": Noul(
                            instructions="Does this action permanently delete files, drop database tables, or destroy critical data?"
                        ),
                        "urgency": Score(
                            instructions="How urgent is this event/request?",
                            criteria=["routine", "important", "emergency"],
                        ),
                    },
                )

                operation = response.choices["operation"].choice
                entity = response.choices["entity"].choice
                target_device = response.choices["target_device"].choice

                raw_destructive = response.nouls["is_destructive"].noul
                is_destructive = bool(float(raw_destructive) > 0.65) if raw_destructive is not None else False

                urgency_score = response.scores["urgency"].score
                urgency_labels = ["routine", "important", "emergency"]
                try:
                    score_val = float(urgency_score) if urgency_score is not None else 0.0
                    idx = min(max(int(round(score_val)), 0), len(urgency_labels) - 1)
                    urgency = urgency_labels[idx]
                except Exception:
                    urgency = "routine"

        except Exception as exc:
            logger.error(f"TypeSafe API error: {exc}. Using dynamic fallback extraction.", exc_info=True)

    # Step 2: Dynamic Semantic Parameter Extraction (0 regexes, 0 hardcoded keyword lists)
    parameters = await _extract_semantic_parameters(
        user_input=user_input,
        operation=operation,
        entity=entity,
        current_time_iso=now_iso,
    )

    # If operation/entity was ambiguous or TypeSafe was not used, accept extracted operation
    if operation == "general_chat" and parameters.get("operation") and parameters.get("operation") != "general_chat":
        operation = parameters["operation"]
        entity = parameters.get("entity", entity)

    latency_ms = round((time.perf_counter() - start_t) * 1000, 2)
    logger.info(f"⚡ [Dynamic Semantic Reflex] Op='{operation}', Entity='{entity}', Timeframe='{parameters.get('timeframe', 'any')}' ({latency_ms}ms)")

    return JevDecision(
        operation=operation,
        entity=entity,
        target_device=target_device,
        is_destructive=is_destructive,
        urgency=urgency,
        parameters=parameters,
        confidence=1.0,
        latency_ms=latency_ms,
    )


async def _extract_semantic_parameters(
    user_input: str,
    operation: str,
    entity: str,
    current_time_iso: str,
) -> Dict[str, Any]:
    """
    Dynamic Semantic Parameter Extractor via fast LLM JSON completion.
    Resolves natural language dates, clean titles, keyword targets, and updates dynamically.
    """
    if has_groq_api_key():
        try:
            groq_client = AsyncGroq(api_key=GROQ_API_KEY)
            system_prompt = (
                "You are an ultra-fast semantic parser. Extract structured database parameters from user queries.\n"
                f"Current UTC Time: {current_time_iso}\n"
                "Available database entities: ['reminders', 'tasks', 'events', 'memories', 'none'].\n"
                "Available operations: ['create', 'search', 'update', 'delete', 'overview', 'device_action', 'chat'].\n\n"
                "Output ONLY a JSON object with this exact schema:\n"
                "{\n"
                '  "operation": "create" | "search" | "update" | "delete" | "overview" | "device_action" | "chat",\n'
                '  "entity": "reminders" | "tasks" | "events" | "memories" | "none",\n'
                '  "timeframe": "today" | "tomorrow" | "this_week" | "past_week" | "any",\n'
                '  "search_query": "clean target keywords for fuzzy search (or empty string)",\n'
                '  "data": {\n'
                '    "title": "clean concise title",\n'
                '    "content": "clean content for memory/note",\n'
                '    "scheduled_at": "ISO-8601 UTC timestamp computed relative to Current UTC Time (or null)",\n'
                '    "category": "general" | "preference" | "contact" | "work",\n'
                '    "status": "pending"\n'
                "  },\n"
                '  "updates": {\n'
                '    "status": "cancelled" | "completed"\n'
                "  }\n"
                "}"
            )

            res = await groq_client.chat.completions.create(
                model="llama-3.1-8b-instant",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": f"User Request: '{user_input}'\nHinted Op: {operation}, Entity: {entity}"},
                ],
                response_format={"type": "json_object"},
                temperature=0.0,
                max_tokens=300,
            )

            raw_json = res.choices[0].message.content or "{}"
            parsed = json.loads(raw_json)
            parsed["raw_text"] = user_input
            return parsed

        except Exception as exc:
            logger.error(f"Semantic parser error: {exc}. Using raw input fallback.", exc_info=True)

    # Clean generic fallback when no LLM API is available
    return {
        "raw_text": user_input,
        "operation": operation,
        "entity": entity,
        "timeframe": "any",
        "search_query": user_input.strip(),
        "data": {
            "title": user_input.strip(),
            "content": user_input.strip(),
            "status": "pending",
            "category": "general",
        },
        "updates": {},
    }
