"""Centralised application configuration.

All configuration is loaded from environment variables (optionally via a
local ``.env`` file).  A missing required variable fails fast at import time
so the application never runs in a half-configured state.
"""

import os

from dotenv import load_dotenv

load_dotenv()


def _required_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(
            f"{name} is not configured. "
            "Copy .env.example to .env and fill in the value."
        )
    return value


# --- Service dependencies -------------------------------------------------
DATABASE_URL = _required_env("DATABASE_URL")
REDIS_URL = _required_env("REDIS_URL")

# --- Authentication -------------------------------------------------------
JWT_SECRET = _required_env("JWT_SECRET")
JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
JWT_EXPIRE_MINUTES = int(os.getenv("JWT_EXPIRE_MINUTES", "30"))

# --- LLM provider ---------------------------------------------------------
# The API key is optional at import time so the server can still start;
# calls to the LLM will fail with a clear error when it is missing.
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.5-flash")
