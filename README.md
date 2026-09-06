<div align="center">

# AI Chatbot Backend

A **production-style AI chatbot backend** built deliberately, one system-design
concern at a time. It covers the full path from a single LLM call to a small,
observable, authenticated service — and every learning note is in the repo.

[Python](https://www.python.org/) · [FastAPI](https://fastapi.tiangolo.com/) ·
[PostgreSQL](https://www.postgresql.org/) · [Redis](https://redis.io/) ·
[Google Gemini](https://ai.google.dev/) · [Docker](https://www.docker.com/)

</div>

---

## What this repo shows

| Concern | How it is handled |
| --- | --- |
| **LLM integration** | `google-genai` + a reliability harness with timeouts, retries, and exponential backoff |
| **API layer** | FastAPI, Pydantic validation, JSON contracts, async request handling |
| **Identity** | JWT bearer authentication with password hashing |
| **State** | PostgreSQL stores conversations and messages per user |
| **Fast/shared state** | Redis provides rate limiting and response caching |
| **Observability** | Per-request IDs and structured JSON logs with token/latency/cost-aware metadata |

This is not a toy "single-file chatbot". It is the kind of small backend you
can talk through in an interview: what each layer owns, why it exists, and
where it would break at scale.

## Highlights for recruiters

- **Clean, typed FastAPI code** split into focused modules (API, auth, models,
  LLM harness, config, logging).
- **Real system-design choices**: auth before expensive LLM calls, per-user
  context isolation, rate limiting, response caching, retry/backoff, request
  tracing.
- **Documented learning path**: 8 block notes in [`docs/`](docs/) from the
  first LLM call through observability.
- **Easy to run**: `docker compose` for PostgreSQL/Redis plus a small
  `.env.example`.

## Architecture

```text
Client
  ↓
JWT Authentication
  ↓
FastAPI
  ↓
Redis ────────── Rate limiting / response cache
  ↓
PostgreSQL ──── Conversations / messages
  ↓
Context builder
  ↓
LLM Harness ─── Timeout / retry / backoff / metrics
  ↓
LLM provider
```

Every request is correlated through the `X-Request-ID` header and emits
structured JSON logs to `logs/app.log` (rotated, secret/prompt-safe).

## Quick start

### 1. Clone and prepare

```bash
git clone https://github.com/ajinkyad015/chatbot.git
cd chatbot
cp .env.example .env
```

Fill in `JWT_SECRET` and `GEMINI_API_KEY` in `.env`.

### 2. Start the infrastructure

```bash
docker compose up -d
```

This starts PostgreSQL (`localhost:5432`) and Redis (`localhost:6379`).

### 3. Install and run

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt

uvicorn app:app --reload
```

Open the interactive API docs at <http://localhost:8000/docs>.

### Makefile shortcuts

```bash
make install     # install dev dependencies
make infra       # start PostgreSQL + Redis
make run         # run the FastAPI dev server
make test        # run the test suite
make lint        # run ruff
```

## Example API flow

```bash
# 1. Register
curl -X POST http://localhost:8000/register \
  -H "Content-Type: application/json" \
  -d '{"username":"alice","password":"a-strong-password"}'

# 2. Log in
curl -X POST http://localhost:8000/login \
  -H "Content-Type: application/json" \
  -d '{"username":"alice","password":"a-strong-password"}'

# 3. Create a conversation
curl -X POST http://localhost:8000/conversations \
  -H "Authorization: Bearer <token>"

# 4. Chat
curl -X POST http://localhost:8000/chat \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"conversation_id":1,"message":"Hello!"}'
```

### Endpoints

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/health` | Liveness |
| `GET` | `/health/redis` | Redis health |
| `POST` | `/register` | Create a user |
| `POST` | `/login` | Get a JWT access token |
| `POST` | `/conversations` | Create a new conversation |
| `POST` | `/chat` | Send a message in a conversation |
| `POST` | `/chat/stateless` | One-off message with Redis response caching |

## Project structure

```text
.
├── app.py                  # FastAPI routes + request lifecycle
├── authentication.py       # Password hashing + JWT auth
├── config.py               # Centralised, fail-fast configuration
├── database.py             # SQLAlchemy engine/session
├── models.py               # Conversation + Message tables
├── schema.py               # Pydantic request/response models
├── llm_harness.py          # Timeout/retry/backoff around the LLM call
├── redis_client.py         # Async Redis client
├── logging_config.py       # Structured, rotating JSON logs
├── tests/                  # API/schema smoke tests
├── docs/                   # Learning notes, block by block
├── docker-compose.yml      # PostgreSQL + Redis
├── .env.example            # Template for local configuration
└── Makefile                # Common developer commands
```

## Learning notes (`docs/`)

The repo grows in a clear order, and each block has its own revision notes:

1. [Basic LLM call](docs/block_1_notes.md)
2. [LLM harness](docs/block_2_llm_harness_revision_notes.md)
3. [FastAPI service](docs/block_3_notes.md)
4. [JWT authentication](docs/block_4_authentication_detailed_notes.md)
5. [Conversation context](docs/block_5_conversation_context_notes.md)
6. [PostgreSQL persistence](docs/block_6_postgresql_persistence_revision_notes.md)
7. [Redis](docs/block_7_redis_notes.md)
8. [Observability](docs/block_8_observability_revision_notes.md)

## Honest limitations

This project is intentionally a learning and interview portfolio project, not
a battle-tested production deployment:

- Users live in an **in-memory store**, so they are lost on restart.
- There is no database migration tool yet (tables are created via
  `Base.metadata.create_all`).
- Logs go to a **local rotating file**, not a centralized log service.
- No streaming, RAG, agents, or multi-provider abstraction yet.

Those gaps are deliberate and clearly documented — they are also excellent
"what would you do next?" interview material.

## License

[MIT](LICENSE)
