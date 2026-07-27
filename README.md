# chatbot

This repository is for learning AI concepts and building with them in parallel.

## AI System Design Learning Project --- Blocks 1--8

## Block 1 --- Basic LLM Call ([notes](docs/block_1_notes.md))

**Built:** CLI → Python → LLM API

**Learned:** - LLM request/response flow - System/user/assistant
messages - Input and output tokens - Latency and API keys - LLM calls
are stateless by default

**Key idea:** The application sends context to the LLM; the model does
not automatically remember previous API calls.

------------------------------------------------------------------------

## Block 2 --- LLM Harness ([notes](docs\block_2_llm_harness_revision_notes.md))

**Built:** Application → LLM Harness → LLM Provider

**Added:** - Timeouts - Retry policy - Exponential backoff - Error
handling - Token and latency information

**Key idea:** An LLM provider is an external dependency and can fail.
The harness isolates provider-specific reliability logic from
application code.

------------------------------------------------------------------------

## Block 3 --- FastAPI Service ([notes](docs\block_3_notes.md))

**Built:** Client → FastAPI → LLM Harness → LLM

**Learned:** - HTTP endpoints - GET/POST - JSON request/response -
Pydantic validation - HTTP status codes - Basic async I/O - API
contracts

**Key idea:** The API layer handles HTTP concerns while the LLM harness
handles model-provider concerns.

------------------------------------------------------------------------

## Block 4 --- JWT Authentication ([notes](docs\block_4_authentication_detailed_notes.md))

**Built:** Client → JWT Authentication → FastAPI → LLM Harness

**Learned:** - Login and JWT access tokens - Bearer tokens - `sub` and
token expiration - Authentication vs authorization

**Key idea:** Authenticate the user before allowing expensive or
protected operations such as LLM calls.

------------------------------------------------------------------------

## Block 5 --- Conversation Context ([notes](docs\block_5_conversation_context_notes.md))

**Built:** User → API → Conversation History → Context → LLM

**Learned:** - Conversation state - Resending previous messages -
Context windows - Token growth - Per-user context isolation - Limiting
conversation history

**Key idea:** LLM memory is usually created by the surrounding
application constructing and resending relevant context.

------------------------------------------------------------------------

## Block 6 --- PostgreSQL Persistence ([notes](docs\block_6_postgresql_persistence_revision_notes.md))

**Built:** FastAPI → PostgreSQL → Context → LLM

**Added:** - Conversations - Messages - Persistent history -
Conversation ownership - Authorization checks

**Key idea:** PostgreSQL is the durable source of truth. Conversation
data survives application restarts and can be shared by multiple API
instances.

------------------------------------------------------------------------

## Block 7 --- Redis ([notes](docs\block_7_redis_notes.md))

**Built:** Redis alongside PostgreSQL.

**Used Redis for:** - Per-user rate limiting - TTL/expiration - Simple
caching - Cache hit/miss handling

**Key idea:** PostgreSQL stores durable truth; Redis is useful for fast,
temporary, shared state.

------------------------------------------------------------------------

## Block 8 --- Observability ([notes](docs\block_8_observability_revision_notes.md))

**Built:** Structured operational logging for the AI request lifecycle.

**Added:** - Request IDs - Structured logs - Log files and rotation -
LLM and total latency - Token usage - Cache/retry information - Error
logging - Cost awareness

**Logs:** `logs/app.log`

**Key idea:** A production AI system must make requests traceable so
failures, latency, token usage, retries, and system behavior can be
investigated.

------------------------------------------------------------------------

## Current Architecture 

``` text
Client
  ↓
JWT Authentication
  ↓
FastAPI
  ↓
Redis ───────── Rate Limiting / Cache
  ↓
PostgreSQL ─── Conversations / Messages
  ↓
Context Builder
  ↓
LLM Harness ── Timeout / Retry / Backoff / Metrics
  ↓
LLM Provider

Across request flow:
  ↓
Structured Logs → logs/app.log
```

## Core Mental Model

- **FastAPI** → service/API boundary
-   **JWT** → identity
-   **PostgreSQL** → durable state
-   **Redis** → fast temporary/shared state
-   **Context Builder** → decides what the LLM sees
-   **LLM Harness** → reliable model-provider boundary
-   **Logs** → understand what happened in production

The project has progressed from a simple LLM API call into a small
production-style AI backend while adding one system-design concern at a
time.
