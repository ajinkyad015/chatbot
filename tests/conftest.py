import os

# Set required config before the application module is imported so the
# test suite does not depend on a local .env file or live services.
os.environ.setdefault("DATABASE_URL", "sqlite:///./test.db")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault(
    "JWT_SECRET", "test-secret-that-is-long-enough-for-hs256"
)
os.environ.setdefault("GEMINI_API_KEY", "")
