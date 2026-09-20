from __future__ import annotations

import datetime
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from typesafe_sdk import AsyncTypeSafeClient, Choice, Noul, Score

from brain.config import TYPESAFE_API_KEY, has_typesafe_api_key

logger = logging.getLogger("jev_reflex")


@dataclass
class JevDecision:
    intent: str  # "reminder_create", "reminder_cancel", "task_create", "task_complete", "device_action", "general_chat", "query_sql"
    target_device: str  # "server", "mobile", "laptop", "broadcast"
    is_destructive: bool
    urgency: str  # "routine", "important", "emergency"
    parameters: Dict[str, Any] = field(default_factory=dict)
    confidence: float = 1.0


async def evaluate_intent_with_jev(
    user_input: str,
    source_device: str = "mobile",
    context: Optional[Dict[str, Any]] = None,
) -> JevDecision:
    """
    Evaluates input through Jev (System 1) to determine intent, device routing,
    urgency, and safety gating in a single parallel pass.
    """
    if not has_typesafe_api_key():
        logger.info("TYPESAFE_API_KEY not found in environment; using heuristic fallback reflex.")
        return _heuristic_fallback_reflex(user_input, source_device)

    try:
        async with AsyncTypeSafeClient(api_key=TYPESAFE_API_KEY) as client:
            state = {
                "user_message": user_input,
                "source_device": source_device,
                "current_time": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                "context": context or {},
            }

            response = await client.system_one(
                state=state,
                questions={
                    # 1. Intent Classification
                    "intent": Choice(
                        instructions="What is the user's primary intended action?",
                        criteria={
                            "reminder_create": "User wants to create, schedule, or set a reminder or meeting",
                            "reminder_cancel": "User wants to cancel, ditch, clear, or remove an existing meeting or reminder",
                            "task_create": "User wants to create or add a new task, todo, or work item",
                            "task_complete": "User wants to mark a task as completed or done",
                            "device_action": "User wants to execute a command or check status on laptop or server",
                            "query_sql": "User is asking for database analytics or records",
                            "general_chat": "General greeting, conversational question, or casual chat",
                        },
                    ),
                    # 2. Target Device Selection
                    "target_device": Choice(
                        instructions="Which device should execute or receive this action?",
                        criteria={
                            "server": "Server handles database, agent reasoning, or schedule storage",
                            "mobile": "Mobile phone (e.g. notify, ring, or mobile action)",
                            "laptop": "User's laptop/MacBook (e.g. code, terminal, git, build)",
                            "broadcast": "All connected devices",
                        },
                    ),
                    # 3. Safety Gate
                    "is_destructive": Noul(
                        instructions="Does this action permanently delete files, drop tables, or perform dangerous operations?"
                    ),
                    # 4. Urgency Scoring
                    "urgency": Score(
                        instructions="How urgent is this event/request?",
                        criteria=["routine", "important", "emergency"],
                    ),
                },
            )

            intent = response.choices["intent"].choice
            target_device = response.choices["target_device"].choice
            is_destructive = response.nouls["is_destructive"].noul
            urgency_score = response.scores["urgency"].score

            # Map score to label
            urgency_labels = ["routine", "important", "emergency"]
            urgency_str = urgency_labels[min(max(urgency_score, 0), len(urgency_labels) - 1)]

            # Extract basic parameters based on classified intent
            params = _extract_parameters(user_input, intent)

            logger.info(f"⚡ [Jev System 1] Intent='{intent}', Target='{target_device}', Destructive={is_destructive}, Urgency='{urgency_str}'")

            return JevDecision(
                intent=intent,
                target_device=target_device,
                is_destructive=is_destructive,
                urgency=urgency_str,
                parameters=params,
                confidence=1.0,
            )

    except Exception as exc:
        logger.error(f"Error evaluating with Jev API: {exc}. Falling back to heuristic reflex.", exc_info=True)
        return _heuristic_fallback_reflex(user_input, source_device)


def _extract_parameters(text: str, intent: str) -> Dict[str, Any]:
    """Helper to extract structured parameters like title, date, priority from natural text."""
    params: Dict[str, Any] = {}
    lower_text = text.lower()

    if intent in ("reminder_create", "task_create"):
        # Extract title
        cleaned = re.sub(r"^(hey friday|friday|remind me to|remind me|create task to|add task)\s*", "", text, flags=re.IGNORECASE).strip()
        params["title"] = cleaned if cleaned else text

        # Default schedule time: 1 hour from now or next day
        now = datetime.datetime.now(datetime.timezone.utc)
        if "tomorrow" in lower_text or "tmrw" in lower_text:
            scheduled_time = now + datetime.timedelta(days=1)
            # Default to 1:00 PM if "1pm" or "1:00" mentioned
            if "1pm" in lower_text or "1 pm" in lower_text or "1:00" in lower_text:
                scheduled_time = scheduled_time.replace(hour=13, minute=0, second=0, microsecond=0)
            elif "12:50" in lower_text or "12.50" in lower_text:
                scheduled_time = scheduled_time.replace(hour=12, minute=50, second=0, microsecond=0)
        else:
            scheduled_time = now + datetime.timedelta(hours=1)

        params["scheduledAt"] = scheduled_time.isoformat()

    elif intent == "reminder_cancel":
        params["action"] = "cancel_latest_meeting"
        params["reason"] = text

    return params


def _heuristic_fallback_reflex(text: str, source_device: str) -> JevDecision:
    """Fallback rule-based reflex when API key is not yet set."""
    lower = text.lower()

    if any(k in lower for k in ("ditched", "cancel meeting", "clear meeting", "cancel reminder", "remove meeting")):
        intent = "reminder_cancel"
    elif any(k in lower for k in ("meeting", "remind", "reminder", "schedule", "appointment")):
        intent = "reminder_create"
    elif any(k in lower for k in ("todo", "task", "buy", "fix", "implement")):
        intent = "task_create"
    elif any(k in lower for k in ("run build", "git", "terminal", "docker")):
        intent = "device_action"
    elif any(k in lower for k in ("select", "show me all reminders", "list tasks", "query")):
        intent = "query_sql"
    else:
        intent = "general_chat"

    target_device = "laptop" if intent == "device_action" else "server"
    is_destructive = bool(re.search(r"\b(drop table|rm -rf|delete from|killall)\b", lower))
    urgency = "emergency" if any(k in lower for k in ("urgent", "emergency", "crash", "down", "critical")) else "routine"

    return JevDecision(
        intent=intent,
        target_device=target_device,
        is_destructive=is_destructive,
        urgency=urgency,
        parameters=_extract_parameters(text, intent),
    )
