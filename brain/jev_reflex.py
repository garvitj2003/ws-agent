from __future__ import annotations

import datetime
import json
import logging
import re
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


def _clean_entity_payload(
    user_input: str,
    entity: str,
    scheduled_dt: datetime.datetime,
) -> Dict[str, Any]:
    """
    Extracts clean, human-readable title, description, and metadata from conversational user input.
    Eliminates conversational clutter, lead-ins, and temporal phrases from database fields.
    """
    text = user_input.strip()

    # 1. Strip conversational lead-ins/prefixes
    lead_in_pattern = re.compile(
        r"^(?:please\s+)?(?:can\s+you\s+)?(?:"
        r"remind\s+me\s+to|remind\s+me|reminder\s+to|set\s+a\s+reminder\s+for|set\s+a\s+reminder\s+to|create\s+a\s+reminder\s+to|"
        r"add\s+a\s+task\s+to|add\s+task\s+to|create\s+a\s+task\s+to|create\s+task\s+to|add\s+a\s+task|add\s+task|task\s+to|todo\s+to|add\s+to\s+do|"
        r"schedule\s+an\s+event\s+for|schedule\s+a\s+meeting\s+with|schedule\s+an|schedule\s+a|schedule|create\s+an\s+event\s+for|create\s+event\s+for|"
        r"we\s+do\s+have\s+a|we\s+have\s+a|we\s+have|there\s+is\s+a|i\s+have\s+a|let\'s\s+have\s+a|lets\s+have\s+a|"
        r"remember\s+that|note\s+that|save\s+that|keep\s+in\s+mind\s+that|dont\s+forget\s+that|don\'t\s+forget\s+that|remember\s+to|dont\s+forget\s+to|don\'t\s+forget\s+to|"
        r"remember|save|note"
        r")\s+",
        re.IGNORECASE,
    )
    cleaned = lead_in_pattern.sub("", text).strip()
    if not cleaned:
        cleaned = text

    # If entity is memories:
    if entity == "memories":
        formatted_content = cleaned[0].upper() + cleaned[1:] if cleaned else cleaned
        return {
            "content": formatted_content,
            "title": formatted_content,
            "category": "general",
            "metadata_json": {},
        }

    # 2. Extract description if there is an explanatory clause ("about", "regarding", "re:", "details:")
    description: Optional[str] = None
    split_parts = re.split(r"\s+(?:about|regarding|re:|details:)\s+", cleaned, maxsplit=1, flags=re.IGNORECASE)
    if len(split_parts) == 2:
        title_part, desc_part = split_parts
        desc_cleaned = desc_part.strip()
        if desc_cleaned:
            description = desc_cleaned[0].upper() + desc_cleaned[1:]
    else:
        title_part = cleaned

    # 3. Strip temporal / scheduling phrases from the title
    time_phrase_pattern = re.compile(
        r"\b(?:"
        r"(?:in\s+the\s+|at\s+)?(?:noon|morning|afternoon|evening|night|midnight)|"
        r"tonight|today|tomorrow|tommorrow|tmrw|tmrow|next\s+week|this\s+week|this\s+weekend|"
        r"by\s+(?:tomorrow|today|next\s+week|tonight)|"
        r"(?:at\s+)?\d{1,2}(?::\d{2})?\s*(?:am|pm|a\.m\.|p\.m\.)"
        r")\b",
        re.IGNORECASE,
    )
    cleaned_title = time_phrase_pattern.sub("", title_part)
    cleaned_title = re.sub(r"\s+", " ", cleaned_title).strip()
    cleaned_title = re.sub(r"\s+(?:at|on|for|by|in|with)$", "", cleaned_title, flags=re.IGNORECASE).strip()

    if not cleaned_title:
        cleaned_title = title_part.strip() or text

    formatted_title = cleaned_title[0].upper() + cleaned_title[1:] if cleaned_title else cleaned_title

    payload: Dict[str, Any] = {
        "title": formatted_title,
        "content": formatted_title,
        "description": description,
        "scheduled_at": scheduled_dt.isoformat(),
        "start_time": scheduled_dt.isoformat(),
        "status": "pending",
        "priority": "medium",
        "category": "general",
    }
    return payload


async def evaluate_intent_with_jev(
    user_input: str,
    source_device: str = "mobile",
    context: Optional[Dict[str, Any]] = None,
) -> JevDecision:
    """
    Ultra-Fast Single-Pass Jev System 1 Reflex:
    1. Single TypeSafe API evaluation for operation, entity, timeframe, time_of_day, device, safety, and urgency.
    2. Zero intermediate LLM round-trips — eliminates 500-1000ms latency overhead.
    3. Direct deterministic timestamp and clean payload synthesis.
    """
    start_t = time.perf_counter()
    now_utc = datetime.datetime.now(datetime.timezone.utc)
    now_iso = now_utc.strftime("%Y-%m-%dT%H:%M:%SZ (%A)")

    operation = "general_chat"
    entity = "none"
    timeframe = "any"
    time_of_day = "default"
    target_device = "server"
    is_destructive = False
    urgency = "routine"

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
                                "create": "User wants to create, save, remember, schedule, or add new data/reminder/task/memory",
                                "search": "User wants to look up, recall, find, ask about, or query existing data/memory/note",
                                "update": "User wants to modify, cancel, dismiss, reschedule, complete, or mark data",
                                "delete": "User wants to permanently delete or remove a specific record",
                                "overview": "User is asking for schedule summary, daily briefing, what's on their plate, or what is planned/scheduled for today/tomorrow",
                                "device_action": "User wants to execute a terminal command on laptop or server",
                                "general_chat": "Casual greeting, chit-chat, or general knowledge question",
                            },
                        ),
                        "entity": Choice(
                            instructions="Which database entity collection does this request relate to?",
                            criteria={
                                "reminders": "Time-based reminders, alarms, calls, notifications, meetings",
                                "tasks": "Todo items, work tickets, action items",
                                "events": "Calendar events, schedule appointments",
                                "memories": "Personal facts, preferences, user knowledge, stored notes",
                                "none": "Not related to any specific database entity",
                            },
                        ),
                        "timeframe": Choice(
                            instructions="What timeframe does this request target?",
                            criteria={
                                "today": "Targeting today, tonight, right now, or current day",
                                "tomorrow": "Targeting tomorrow, next day, tomorrow morning/noon/night",
                                "this_week": "Targeting this week, upcoming days",
                                "past_week": "Targeting past week, yesterday, previous days",
                                "any": "No specific timeframe mentioned or anytime",
                            },
                        ),
                        "time_of_day": Choice(
                            instructions="What specific time of day is requested for scheduled actions/reminders?",
                            criteria={
                                "noon": "Noon, midday, 12 pm, lunch time",
                                "morning": "Morning, 9 am, breakfast time",
                                "evening": "Evening, 6 pm",
                                "night": "Night, 8 pm, dinner, bedtime",
                                "default": "No specific hour mentioned (+1 hour default)",
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
                timeframe = response.choices["timeframe"].choice
                time_of_day = response.choices["time_of_day"].choice
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
            logger.error(f"TypeSafe API error: {exc}. Using deterministic fallback.", exc_info=True)

    if operation == "general_chat" and not has_typesafe_api_key():
        lower = user_input.lower()
        if any(w in lower for w in ("schedule", "agenda", "plate", "briefing", "planned", "overview")):
            operation = "overview"
            entity = "reminders"
        elif any(w in lower for w in ("remind", "reminder", "call", "alarm", "meeting")):
            operation = "create"
            entity = "reminders"
        elif any(w in lower for w in ("remember", "dog", "vet", "favorite", "fact")):
            operation = "search" if any(w in lower for w in ("who", "what", "where", "when")) else "create"
            entity = "memories"

        if "today" in lower or "tonight" in lower:
            timeframe = "today"
        elif any(w in lower for w in ("tomorrow", "tommorrow", "tmrw", "tmrow", "tmr")):
            timeframe = "tomorrow"

        if "noon" in lower or "12 pm" in lower or "midday" in lower:
            time_of_day = "noon"
        elif "morning" in lower or "9 am" in lower:
            time_of_day = "morning"
        elif "evening" in lower or "6 pm" in lower:
            time_of_day = "evening"
        elif "night" in lower or "8 pm" in lower:
            time_of_day = "night"

    # Safety fallback: if timeframe is still "any" but user explicitly mentioned today/tomorrow
    lower_raw = user_input.lower()
    if timeframe == "any":
        if "today" in lower_raw or "tonight" in lower_raw:
            timeframe = "today"
        elif any(w in lower_raw for w in ("tomorrow", "tommorrow", "tmrw", "tmrow", "tmr")):
            timeframe = "tomorrow"

    # Step 2: Instant Deterministic Parameter Resolution (<1ms, zero LLM calls)
    hour_map = {"noon": 12, "morning": 9, "evening": 18, "night": 20, "default": 13}
    target_hour = hour_map.get(time_of_day, 13)

    if timeframe == "tomorrow":
        scheduled_dt = (now_utc + datetime.timedelta(days=1)).replace(hour=target_hour, minute=0, second=0, microsecond=0)
    elif timeframe == "today":
        if time_of_day != "default":
            scheduled_dt = now_utc.replace(hour=target_hour, minute=0, second=0, microsecond=0)
        else:
            scheduled_dt = now_utc + datetime.timedelta(hours=1)
    else:
        scheduled_dt = now_utc + datetime.timedelta(hours=1)

    # Clean search query (strip question preambles)
    cleaned_query = user_input.strip()
    if operation == "search":
        for prefix in ["who is", "what is", "where is", "when is", "tell me about", "find", "search for", "do we have", "is there"]:
            if cleaned_query.lower().startswith(prefix):
                cleaned_query = cleaned_query[len(prefix):].strip()
                break

    # Determine updates
    updates = {}
    if operation == "update":
        lower_input = user_input.lower()
        if any(w in lower_input for w in ("cancel", "cancelled", "dismiss", "ditch", "clear", "delete", "remove")):
            updates = {"status": "cancelled"}
        elif any(w in lower_input for w in ("done", "finish", "finished", "complete", "completed")):
            updates = {"status": "completed"}

    # Deterministically extract clean title, description, and entity payload
    clean_data = _clean_entity_payload(user_input, entity, scheduled_dt)

    parameters = {
        "raw_text": user_input,
        "operation": operation,
        "entity": entity,
        "timeframe": timeframe,
        "search_query": cleaned_query,
        "data": clean_data,
        "updates": updates,
    }

    latency_ms = round((time.perf_counter() - start_t) * 1000, 2)
    logger.info(f"⚡ [Jev System 1 Single-Pass] Op='{operation}', Entity='{entity}', Timeframe='{timeframe}', TimeOfDay='{time_of_day}' ({latency_ms}ms)")

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
