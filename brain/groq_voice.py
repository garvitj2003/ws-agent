from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from groq import AsyncGroq

from brain.config import GROQ_API_KEY, GROQ_MODEL, has_groq_api_key

logger = logging.getLogger("groq_voice")

FRIDAY_SYSTEM_PROMPT = """You are Friday, an ultra-fast, intelligent, and highly capable personal AI assistant (inspired by Iron Man's FRIDAY / JARVIS).
Your communication style:
- Charismatic, polite, warm, concise, and slightly witty when appropriate.
- Refer to the user respectfully (e.g. 'sir' or by context).
- Keep responses short and impactful (1 to 2 sentences max).
- Confidently acknowledge actions completed by the system (e.g., reminders set, tasks created, meetings cancelled).
- If the user is disappointed (e.g., client ditched), be empathetic, supportive, and encouraging.
"""


async def generate_friday_reply(
    user_input: str,
    action_summary: str,
    context: Optional[Dict[str, Any]] = None,
) -> str:
    """
    Generates a natural, conversational Friday response based on the completed action.
    """
    if not has_groq_api_key():
        logger.info("GROQ_API_KEY not found in environment; using template fallback.")
        return _fallback_reply(user_input, action_summary)

    try:
        groq_client = AsyncGroq(api_key=GROQ_API_KEY)
        messages = [
            {"role": "system", "content": FRIDAY_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    f"User Message: '{user_input}'\n"
                    f"Action Completed by System: {action_summary}\n"
                    f"Context: {context or {}}\n"
                    "Respond to the user naturally, acknowledging what you did."
                ),
            },
        ]

        response = await groq_client.chat.completions.create(
            model=GROQ_MODEL,
            messages=messages,
            temperature=0.7,
            max_tokens=100,
        )

        reply = response.choices[0].message.content.strip()
        logger.info(f"🗣️ [Friday Voice/Groq] Generated reply: '{reply}'")
        return reply

    except Exception as exc:
        logger.error(f"Error calling Groq API: {exc}. Using fallback response.", exc_info=True)
        return _fallback_reply(user_input, action_summary)


def _fallback_reply(user_input: str, action_summary: str) -> str:
    """Natural fallback templates when API key is not configured."""
    lower = user_input.lower()
    if any(k in lower for k in ("ditched", "cancel", "cancelled", "clear")):
        return "Oh, sorry to hear that sir! But no worries, we'll get another one. I have cleared the meeting from your schedule."
    elif any(k in lower for k in ("meeting", "remind", "reminder")):
        return f"Understood, sir. I have scheduled that reminder for you and will notify you ahead of time."
    elif any(k in lower for k in ("task", "todo", "add")):
        return "Done, sir. I've added that task to your work list."
    else:
        return f"Right away, sir. {action_summary}"
