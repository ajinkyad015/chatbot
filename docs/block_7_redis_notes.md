# Block 7 --- Redis: Rate Limiting and Simple Caching

## 1. What We Added

Before Redis, the main conversational flow was:

``` text
Client
  ↓
JWT Authentication
  ↓
FastAPI
  ↓
PostgreSQL conversation storage
  ↓
Context Builder
  ↓
LLM Harness
  ↓
LLM Provider
```

Redis adds **fast, shared, temporary state** without replacing
PostgreSQL.

``` text
                    FastAPI
                   /       \
                  ↓         ↓
               Redis    PostgreSQL
                 │          │
          temporary state   durable data
                 │          │
          rate limits       conversations
          cache entries     messages
```

The key architectural distinction is:

-   **PostgreSQL = durable source of truth**
-   **Redis = fast, temporary/shared state**

If Redis data disappears, the application should not lose its durable
conversation history.

------------------------------------------------------------------------

# 2. Redis vs PostgreSQL

## PostgreSQL

PostgreSQL stores information that must survive application restarts and
should not disappear automatically.

In our application, this includes:

``` text
Conversation
├── user_id
└── messages
    ├── user message
    ├── assistant message
    └── ...
```

This is **durable state**.

If the application restarts, we still expect these records to exist.

## Redis

Redis is useful for information that needs to be:

-   very fast to access
-   shared between application instances
-   temporary
-   automatically expirable

Examples from this block:

``` text
rate_limit:alice → 4
```

and:

``` text
llm_cache:<hash> → cached LLM response
```

These values do not need to live forever.

This is **ephemeral/temporary state**.

------------------------------------------------------------------------

# 3. Why Redis Is Shared State

A Python dictionary belongs to one Python process.

Imagine two FastAPI instances:

``` text
FastAPI A

alice → 3 requests
```

and:

``` text
FastAPI B

alice → 2 requests
```

They do not automatically share memory.

Therefore neither instance knows that Alice has actually made 5
requests.

With Redis:

``` text
FastAPI A ──┐
            ├── Redis
FastAPI B ──┘
```

both instances access:

``` text
rate_limit:alice → 5
```

Redis becomes a shared location for temporary operational state.

> Important: our current in-memory authentication `users` dictionary is
> still process-local. We did not redesign authentication in this block.

------------------------------------------------------------------------

# 4. Redis Connection

Redis runs as a separate server.

The Python `redis` package is only the **client library** used by
FastAPI to communicate with that server.

Conceptually:

``` text
FastAPI
   │
   │ Redis client
   ↓
Redis Server
```

Our Redis URL is kept in `.env`, for example:

``` text
REDIS_URL=redis://localhost:6379/0
```

We verified the connection using:

``` text
PING
```

Successful Redis response:

``` text
PONG
```

This proves that the application can communicate with Redis.

------------------------------------------------------------------------

# 5. Rate Limiting

## Goal

Our learning rate limit is:

``` text
5 requests per user
per 60 seconds
```

The authenticated JWT identity is used to identify the user.

For example:

``` text
JWT
 ↓
authenticated user
 ↓
username = alice
```

Redis then uses a key such as:

``` text
rate_limit:alice
```

------------------------------------------------------------------------

# 6. Rate-Limit Request Flow

The important flow is:

``` text
Authenticated request
        ↓
Redis counter
        ↓
increment counter
        ↓
within limit?
   ↙            ↘
 yes             no
  ↓               ↓
continue         HTTP 429
  ↓
PostgreSQL
  ↓
Context
  ↓
LLM
```

The rate-limit check happens **before the expensive LLM call**.

This protects:

-   LLM/provider quota
-   API cost
-   infrastructure capacity
-   the service from abuse

If the user has exceeded the limit, there is no reason to spend
resources building context and calling the provider.

------------------------------------------------------------------------

# 7. INCR

Redis provides an atomic increment operation:

``` text
INCR rate_limit:alice
```

Suppose the key does not exist.

The first increment produces:

``` text
rate_limit:alice = 1
```

Next request:

``` text
rate_limit:alice = 2
```

Then:

``` text
rate_limit:alice = 3
```

and so on.

Our application allows:

``` text
1 → allowed
2 → allowed
3 → allowed
4 → allowed
5 → allowed
6 → rejected
```

The sixth request receives:

``` text
HTTP 429 Too Many Requests
```

Most importantly:

``` text
request 6
 ↓
Redis detects limit
 ↓
HTTP 429
 ↓
STOP
```

The LLM is **not called**.

------------------------------------------------------------------------

# 8. Why Atomic INCR Matters

Multiple FastAPI instances might increment the same counter at nearly
the same time.

Redis performs `INCR` atomically.

Conceptually, Redis safely changes:

``` text
4 → 5
```

without two application instances independently reading `4` and
incorrectly overwriting each other's update.

For this block, remember:

> `INCR` safely increments a Redis counter.

------------------------------------------------------------------------

# 9. TTL and EXPIRE

Rate-limit counters should not exist forever.

We want:

``` text
rate_limit:alice
```

to disappear automatically after the rate-limit window.

We therefore use expiration.

Conceptually:

``` text
INCR rate_limit:alice
EXPIRE rate_limit:alice 60
```

`EXPIRE` means:

> Automatically delete this key after the specified number of seconds.

Redis can report the remaining lifetime using TTL:

``` text
TTL rate_limit:alice
```

Example:

``` text
42
```

means approximately 42 seconds remain.

After expiration:

``` text
GET rate_limit:alice
```

returns nothing because Redis removed the key.

The next request starts a new window:

``` text
rate_limit:alice = 1
```

------------------------------------------------------------------------

# 10. Why We Set Expiration on the First Increment

The simplified pattern is:

``` text
INCR key

if count == 1:
    EXPIRE key 60
```

We do not intentionally reset the TTL after every request.

Otherwise repeated requests could keep moving the expiration into the
future.

The learning model is:

``` text
first request
 ↓
counter = 1
 ↓
start 60-second expiration

additional requests
 ↓
increment same counter

TTL reaches 0
 ↓
Redis deletes key
```

------------------------------------------------------------------------

# 11. Fixed-Window Rate Limiting

Our implementation is a simple **fixed-window rate limiter**.

Example:

``` text
60-second window

request 1 → allowed
request 2 → allowed
request 3 → allowed
request 4 → allowed
request 5 → allowed
request 6 → rejected
```

When the key expires, a new window begins.

This is intentionally simple.

Production systems may use algorithms such as:

-   sliding window
-   token bucket

Those solve limitations of fixed windows and can provide smoother rate
limiting.

They are outside the scope of this block.

------------------------------------------------------------------------

# 12. HTTP 429

When the user exceeds the rate limit, the API returns:

``` text
429 Too Many Requests
```

This communicates:

> The request itself may be valid, but the client is sending requests
> too frequently according to the service's limit.

This is different from:

``` text
401 → authentication problem
403 → authorization problem
404 → resource not found
429 → rate limit exceeded
```

------------------------------------------------------------------------

# 13. Simple Caching

Rate limiting answers:

> Should this request be allowed?

Caching answers:

> Have we already computed this result recently?

Without caching:

``` text
request
 ↓
LLM
 ↓
response

same request
 ↓
LLM again
 ↓
response
```

The same computation may be repeated.

With caching:

``` text
request
 ↓
Redis lookup
 ↓
HIT or MISS
```

------------------------------------------------------------------------

# 14. Cache Miss

A **cache miss** means Redis does not currently contain a result for the
effective input.

Flow:

``` text
request
 ↓
create cache key
 ↓
Redis GET
 ↓
nothing found
 ↓
CACHE MISS
 ↓
LLM call
 ↓
response
 ↓
Redis SET + TTL
 ↓
return response
```

The first request therefore still pays the LLM cost.

------------------------------------------------------------------------

# 15. Cache Hit

A **cache hit** means Redis already contains a usable result.

``` text
same effective request
 ↓
same cache key
 ↓
Redis GET
 ↓
cached response found
 ↓
CACHE HIT
 ↓
return response
```

The LLM is not called.

This can reduce:

-   latency
-   LLM cost
-   provider requests
-   infrastructure work

------------------------------------------------------------------------

# 16. Cache Keys

The central caching idea is:

> Same effective input → same cache key → potentially reuse the
> response.

Instead of storing a long message directly in the Redis key, we can hash
it.

Conceptually:

``` text
"Explain Redis in one sentence"
              ↓
            SHA-256
              ↓
          abc123...
```

Redis key:

``` text
llm_cache:abc123...
```

Hashing gives us a predictable compact key.

However:

> Hashing does NOT automatically make a cache correct.

Correctness depends on whether the key represents **all inputs that can
affect the output**.

------------------------------------------------------------------------

# 17. Why We Used a Stateless Demo Endpoint

Our real `/chat` endpoint is conversational.

Its LLM input is not only the current message.

Example:

``` text
Conversation A

User: My name is Sam.
Assistant: Nice to meet you.
User: What is my name?
```

The answer should depend on the previous conversation.

Another conversation:

``` text
Conversation B

User: My name is Alex.
Assistant: Nice to meet you.
User: What is my name?
```

Both current messages are:

``` text
"What is my name?"
```

but the correct answers are different.

Therefore this would be unsafe:

``` text
cache key = hash(current message)
```

because both conversations would produce the same key.

The application could accidentally return:

``` text
Sam
```

inside Alex's conversation.

------------------------------------------------------------------------

# 18. Effective Input in Conversational AI

For a conversational LLM, the effective input may include:

``` text
system instruction
+
model/configuration
+
conversation history
+
current user message
```

Therefore a safer conceptual conversational cache key would need to
represent all relevant inputs:

``` text
effective LLM input
       ↓
      hash
       ↓
cache key
```

Different histories then produce different keys.

Example:

``` text
Sam conversation context
        ↓
      hash A
```

versus:

``` text
Alex conversation context
        ↓
      hash B
```

We intentionally did **not** implement this complexity in Block 7.

Instead, we used a stateless demonstration endpoint.

------------------------------------------------------------------------

# 19. What the Stateless Cache Endpoint Is

The stateless endpoint exists only to make exact-match caching easy to
observe.

Its flow is:

``` text
Client
 ↓
JWT Authentication
 ↓
Stateless endpoint
 ↓
Redis cache
 ↓
HIT?
 ├── yes → return cached response
 │
 └── no
      ↓
     LLM
      ↓
   Redis SET
      ↓
    response
```

It still uses JWT authentication.

But it deliberately does **not** use:

-   conversation ID
-   PostgreSQL conversation lookup
-   PostgreSQL message history
-   Context Builder
-   conversation persistence

This does **not replace** the real `/chat` endpoint.

It is a learning/demo path for understanding caching safely.

------------------------------------------------------------------------

# 20. Real `/chat` vs Stateless Cache Demo

## Real conversational endpoint

``` text
Client
 ↓
JWT
 ↓
/chat
 ↓
Redis rate limit
 ↓
PostgreSQL conversation
 ↓
load message history
 ↓
build context
 ↓
LLM
 ↓
save messages to PostgreSQL
```

This is the actual conversation architecture.

## Stateless caching demo

``` text
Client
 ↓
JWT
 ↓
/chat/stateless
 ↓
Redis cache lookup
 ↓
HIT ─────────────→ return
 ↓ MISS
LLM
 ↓
Redis cache SET
 ↓
return
```

The second endpoint exists to demonstrate caching without introducing
conversational cache correctness problems.

------------------------------------------------------------------------

# 21. Cache TTL

Cached responses should normally not live forever.

Conceptually Redis supports:

``` text
SET key value EX 60
```

Meaning:

``` text
store this value
+
automatically expire it after 60 seconds
```

Example:

``` text
llm_cache:abc123 → "Redis is..."
TTL → 60 seconds
```

After the TTL expires:

``` text
llm_cache:abc123
```

is automatically removed.

The next equivalent request becomes a cache miss and calls the LLM
again.

------------------------------------------------------------------------

# 22. Why Cache Entries Expire

Caches can become stale.

Possible changes include:

-   model behavior
-   prompts/system instructions
-   underlying application data
-   business rules
-   configuration

Expiration also prevents temporary cached data from accumulating
forever.

Therefore:

> Cache data is reusable optimization data, not permanent truth.

------------------------------------------------------------------------

# 23. Cache Test Mental Model

First request:

``` text
Input A
 ↓
cache key A
 ↓
Redis GET
 ↓
MISS
 ↓
LLM called
 ↓
Redis SET
 ↓
cache_hit = false
```

Second identical request:

``` text
Input A
 ↓
same cache key A
 ↓
Redis GET
 ↓
HIT
 ↓
LLM NOT called
 ↓
cache_hit = true
```

After TTL expires:

``` text
Input A
 ↓
Redis GET
 ↓
MISS
 ↓
LLM called again
```

This is the core caching cycle.

------------------------------------------------------------------------

# 24. Rate Limiting and Caching Are Different

Both use Redis, but they solve different problems.

## Rate limiter

Redis remembers:

> How many times has this user made a request recently?

Example:

``` text
rate_limit:alice → 4
```

Purpose:

``` text
protection
```

## Cache

Redis remembers:

> Have we already computed this result recently?

Example:

``` text
llm_cache:abc123 → response
```

Purpose:

``` text
optimization
```

A useful summary:

``` text
Rate limit → protect expensive work

Cache → avoid repeating expensive work
```

------------------------------------------------------------------------

# 25. What If Redis Goes Down?

Redis should not be the only place containing critical durable
conversation data.

PostgreSQL still contains:

``` text
conversations
messages
```

Therefore a Redis failure does not automatically mean conversation data
has been lost.

But Redis-dependent features need a policy.

------------------------------------------------------------------------

# 26. Cache Failure

Caching is an optimization.

A natural degradation strategy is:

``` text
Redis unavailable
 ↓
cannot check cache
 ↓
skip cache
 ↓
call LLM normally
```

The service becomes:

-   slower
-   potentially more expensive

but can remain functionally correct.

This is **graceful degradation**.

------------------------------------------------------------------------

# 27. Rate-Limit Failure

Rate limiting is a protection mechanism.

If Redis is unavailable:

``` text
FastAPI
 ↓
cannot read/increment rate-limit counter
```

The system has to choose a policy.

## Fail open

``` text
Redis unavailable
 ↓
allow request
 ↓
continue to LLM
```

Advantage:

``` text
service remains available
```

Disadvantage:

``` text
temporary loss of rate-limit protection
```

## Fail closed

``` text
Redis unavailable
 ↓
reject request
```

Advantage:

``` text
protection remains strict
```

Disadvantage:

``` text
Redis outage can make the endpoint unavailable
```

There is no universal answer.

The choice depends on whether availability or strict protection is more
important for the system.

We did not build complex fallback infrastructure in this block.

------------------------------------------------------------------------

# 28. Durable vs Ephemeral State

This is one of the main architectural lessons from Block 7.

## Durable

Data that should survive and is part of application truth:

``` text
PostgreSQL

conversation
messages
```

## Ephemeral

Temporary data that can be recreated:

``` text
Redis

rate-limit counters
cache entries
```

A useful question when designing storage is:

> If this value disappears, have I lost important user/application data?

If yes, it probably belongs in durable storage.

If it can be recomputed or recreated, Redis may be appropriate depending
on the use case.

------------------------------------------------------------------------

# 29. Final Architecture

After Block 7, the main conversational architecture is:

``` text
Client
  ↓
JWT Authentication
  ↓
FastAPI
  ↓
Redis Rate Limiter
  │
  ├── limit exceeded
  │       ↓
  │    HTTP 429
  │
  └── allowed
          ↓
      PostgreSQL
          ↓
    Conversation History
          ↓
     Context Builder
          ↓
      LLM Harness
          ↓
      LLM Provider
          ↓
      PostgreSQL
      persist messages
```

Redis is alongside the application:

``` text
                     ┌──── Redis
                     │     ├── rate limits
Client → FastAPI ────┤     └── cache
                     │
                     └──── PostgreSQL
                           └── durable conversations
```

------------------------------------------------------------------------

# 30. Block 7 Revision Checklist

You should be able to explain each of these without looking at the
implementation.

### Redis vs PostgreSQL

``` text
PostgreSQL = durable source of truth
Redis      = fast temporary/shared state
```

### Why Redis across multiple API instances?

``` text
FastAPI A ──┐
            ├── Redis shared state
FastAPI B ──┘
```

Local Python memory would not automatically be shared.

### INCR

``` text
INCR key
```

Atomically increments a Redis counter.

### TTL / EXPIRE

``` text
EXPIRE key 60
```

Makes temporary state disappear automatically.

### Why rate limit before LLM?

Because rejected requests should not consume expensive LLM/provider
resources.

### HTTP 429

``` text
Too Many Requests
```

The client exceeded the allowed request rate.

### Cache miss

``` text
Redis has no cached result
→ call LLM
→ store result
```

### Cache hit

``` text
Redis already has result
→ return it
→ do not call LLM
```

### Why cache keys matter

A cache key must represent the effective inputs that determine the
result.

### Why conversational caching is dangerous

The same current message can mean different things depending on
conversation history.

### Why cache TTL exists

Cached information is temporary and may become stale.

### What if Redis goes down?

``` text
PostgreSQL durable data remains.

Cache:
usually degrade gracefully.

Rate limiter:
choose fail open or fail closed based on system requirements.
```

------------------------------------------------------------------------

# 31. One-Minute Revision

If you only have one minute before an interview or revision session,
remember this:

``` text
REDIS
=
FAST + SHARED + TEMPORARY STATE
```

Rate limiting:

``` text
JWT user
 ↓
INCR rate_limit:user
 ↓
TTL
 ↓
count > limit?
 ↓
429 before LLM
```

Caching:

``` text
effective input
 ↓
cache key
 ↓
Redis GET
 ↓
HIT → return
MISS → LLM → Redis SET + TTL
```

Storage responsibilities:

``` text
PostgreSQL
→ conversations/messages
→ durable truth

Redis
→ counters/cache
→ temporary operational state
```

Most important caching rule:

``` text
same effective input
→ same cache key
```

Not necessarily:

``` text
same current message
→ same answer
```

because conversational context can change the meaning and result.

------------------------------------------------------------------------

# 32. What We Intentionally Did NOT Add

Block 7 stops here.

We did not introduce:

-   RAG
-   queues
-   Celery
-   Redis sessions
-   distributed locks
-   pub/sub
-   vector databases
-   Docker
-   Kubernetes
-   advanced rate-limit algorithms
-   semantic caching
-   complex Redis abstractions

The purpose of this block was specifically to understand:

``` text
Redis
├── rate limiting
└── simple exact-match caching
```

while keeping:

``` text
PostgreSQL = durable source of truth
```
