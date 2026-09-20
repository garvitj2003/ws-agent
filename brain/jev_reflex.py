from __future__ import annotations

import datetime
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from typesafe_sdk import AsyncTypeSafeClient, Choice, Noul, Score

from brain.config import TYPESAFE_API_KEY, has_typesafe_api_key
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
    Evaluates input through Jev System 1:
    - Decides generic operation (create, search, update, delete, overview)
    - Decides entity table (reminders, tasks, events, memories, none)
    - Evaluates safety & urgency in <40ms.
    """
    start_t = time.perf_counter()
    if not has_typesafe_api_key():
        logger.info("TYPESAFE_API_KEY not found in environment; using dynamic heuristic reflex.")
        dec = _heuristic_dynamic_reflex(user_input, source_device)
        dec.latency_ms = round((time.perf_counter() - start_t) * 1000, 2)
        return dec

    try:
        async with AsyncTypeSafeClient(api_key=TYPESAFE_API_KEY) as client:
            state = {
                "user_message": user_input,
                "source_device": source_device,
                "current_time": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                "available_entities": dynamic_repo.get_available_entities(),
                "context": context or {},
            }

            response = await client.system_one(
                state=state,
                questions={
                    # 1. Operation Decision
                    "operation": Choice(
                        instructions="What fundamental operation is the user requesting?",
                        criteria={
                            "create": "User wants to create, save, remember, schedule, or add new data",
                            "search": "User wants to look up, recall, find, ask about, or query existing data",
                            "update": "User wants to modify, cancel, dismiss, reschedule, complete, or mark data",
                            "delete": "User wants to permanently delete or remove a specific record",
                            "overview": "User is asking for daily briefing, what's on their plate, or schedule summary",
                            "device_action": "User wants to execute a terminal command on laptop or server",
                            "general_chat": "Casual greeting, chit-chat, or general knowledge question",
                        },
                    ),
                    # 2. Entity Selection (Dynamically mapped to database tables)
                    "entity": Choice(
                        instructions="Which entity/table does this request relate to?",
                        criteria={
                            "reminders": "Time-based notifications, alarms, meeting reminders, calls",
                            "tasks": "Todo items, work tickets, action checklists",
                            "events": "Calendar events, schedule appointments",
                            "memories": "Personal facts, user preferences, notes, saved information",
                            "none": "Not related to any specific stored database entity",
                        },
                    ),
                    # 3. Target Device Selection
                    "target_device": Choice(
                        instructions="Which device should handle or receive this action?",
                        criteria={
                            "server": "Server handles database storage, agenda, or agent reasoning",
                            "mobile": "Mobile phone",
                            "laptop": "User's laptop/MacBook",
                            "broadcast": "All connected devices",
                        },
                    ),
                    # 4. Safety Gate
                    "is_destructive": Noul(
                        instructions="Does this action permanently delete files, drop database tables, or destroy data?"
                    ),
                    # 5. Urgency Scoring
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
                urgency_str = urgency_labels[idx]
            except Exception:
                urgency_str = "routine"

            params = _extract_dynamic_parameters(user_input, operation, entity)

            latency_ms = round((time.perf_counter() - start_t) * 1000, 2)
            logger.info(f"⚡ [Jev Dynamic] Op='{operation}', Entity='{entity}', Target='{target_device}', Destructive={is_destructive} ({latency_ms}ms)")

            return JevDecision(
                operation=operation,
                entity=entity,
                target_device=target_device,
                is_destructive=is_destructive,
                urgency=urgency_str,
                parameters=params,
                confidence=1.0,
                latency_ms=latency_ms,
            )

    except Exception as exc:
        logger.error(f"Error evaluating with Jev API: {exc}. Falling back to dynamic heuristic reflex.", exc_info=True)
        dec = _heuristic_dynamic_reflex(user_input, source_device)
        dec.latency_ms = round((time.perf_counter() - start_t) * 1000, 2)
        return dec


def _extract_dynamic_parameters(text: str, operation: str, entity: str) -> Dict[str, Any]:
    """Dynamically parses parameters into structured dictionary."""
    params: Dict[str, Any] = {"raw_text": text}
    lower = text.lower()
    now = datetime.datetime.now(datetime.timezone.utc)

    # Timeframe extraction
    if "tomorrow" in lower or "tmrw" in lower:
        params["timeframe"] = "tomorrow"
    elif "today" in lower:
        params["timeframe"] = "today"
    else:
        params["timeframe"] = "any"

    # Search Query / Entity extraction
    # e.g. "cancel my meeting with Harvard", "who is the vet of my dog", "what is my dog's name"
    if operation == "search":
        cleaned_search = re.sub(r"^(who is|what is|whats|whos|where is|when is|tell me|show me|find|search for|about|can you tell me)\s+(?:the\s+|my\s+)?", "", text, flags=re.IGNORECASE).strip()
        params["search_query"] = cleaned_search if cleaned_search else text.strip()
    else:
        match = re.search(r"(?:meeting with|remember that|remember|about|cancel|for|find|search|regarding)\s+(?:the\s+|my\s+)?([a-zA-Z0-9_\s'-]+)", text, flags=re.IGNORECASE)
        if match:
            params["search_query"] = match.group(1).strip()
        else:
            params["search_query"] = text.strip()

    # Create / Data extraction
    if operation == "create":
        data: Dict[str, Any] = {}
        cleaned = re.sub(r"^(hey friday|friday|remind me to|remind me|create task to|add task|remember that|remember)\s*", "", text, flags=re.IGNORECASE).strip()

        if entity == "reminders":
            data["title"] = cleaned if cleaned else text
            # Calculate time
            if params["timeframe"] == "tomorrow":
                scheduled_time = (now + datetime.timedelta(days=1)).replace(hour=13, minute=0, second=0, microsecond=0)
            else:
                scheduled_time = now + datetime.timedelta(hours=1)
            data["scheduled_at"] = scheduled_time.isoformat()
            data["status"] = "pending"

        elif entity == "tasks":
            data["title"] = cleaned if cleaned else text
            data["priority"] = "high" if any(k in lower for k in ("high", "urgent", "asap")) else "medium"
            data["status"] = "pending"

        elif entity == "memories":
            data["content"] = cleaned if cleaned else text
            data["category"] = "preference" if any(k in lower for k in ("like", "prefer", "favorite", "love")) else "general"

        params["data"] = data

    elif operation == "update":
        if any(k in lower for k in ("cancel", "cancelled", "ditch", "clear", "dismiss")):
            params["updates"] = {"status": "cancelled"}
        elif any(k in lower for k in ("done", "finish", "finished", "complete", "completed")):
            params["updates"] = {"status": "completed"}
        else:
            params["updates"] = {}

    return params


def _heuristic_dynamic_reflex(text: str, source_device: str) -> JevDecision:
    """Fallback rule-based reflex when API key is not configured."""
    lower = text.lower()

    # 1. Operation & Entity Detection
    if any(k in lower for k in ("on my plate", "daily briefing", "my schedule", "agenda", "whats on my", "what do i have")):
        operation = "overview"
        entity = "reminders"
    elif any(k in lower for k in ("remember that", "remember", "my dog", "my birthday", "favorite", "my car")):
        if any(k in lower for k in ("what", "where", "who", "when", "tell me")):
            operation = "search"
        else:
            operation = "create"
        entity = "memories"
    elif any(k in lower for k in ("cancel", "clear meeting", "cancelled", "ditch")):
        operation = "update"
        entity = "reminders"
    elif any(k in lower for k in ("meeting", "remind", "reminder", "alarm")):
        operation = "create"
        entity = "reminders"
    elif any(k in lower for k in ("todo", "task", "buy", "fix", "implement")):
        operation = "create"
        entity = "tasks"
    elif any(k in lower for k in ("run build", "git", "terminal", "docker")):
        operation = "device_action"
        entity = "none"
    else:
        operation = "general_chat"
        entity = "none"

    target_device = "laptop" if operation == "device_action" else "server"
    is_destructive = bool(re.search(r"\b(drop table|rm -rf|delete from|killall)\b", lower))
    urgency = "emergency" if any(k in lower for k in ("urgent", "emergency", "crash", "critical")) else "routine"

    return JevDecision(
        operation=operation,
        entity=entity,
        target_device=target_device,
        is_destructive=is_destructive,
        urgency=urgency,
        parameters=_extract_dynamic_parameters(text, operation, entity),
    )
