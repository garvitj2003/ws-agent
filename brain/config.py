from __future__ import annotations

import os

TYPESAFE_API_KEY = os.getenv("TYPESAFE_API_KEY", "").strip()
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "").strip()
GROQ_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-20b").strip()
DEBUG_STREAM = os.getenv("DEBUG_STREAM", "true").lower() in ("true", "1", "yes")

def has_typesafe_api_key() -> bool:
    return bool(TYPESAFE_API_KEY)

def has_groq_api_key() -> bool:
    return bool(GROQ_API_KEY)
