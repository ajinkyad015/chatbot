# Block 8 --- Observability Revision Notes

## 1. What is observability?

Observability means having enough information about a running system to
understand **what happened during a request** without guessing.

For our chatbot, the request flow is:

``` text
Client
  ↓
JWT Authentication
  ↓
FastAPI
  ↓
Redis
  ↓
PostgreSQL
  ↓
Context Builder
  ↓
LLM Harness
  ↓
LLM Provider
  ↓
Response
```

Before observability, the application could work, but when something
became slow or failed it was difficult to answer:

-   Which user made the request?
-   Which conversation was involved?
-   Was the user rate limited?
-   Was the cache used?
-   Which model ran?
-   How many tokens were consumed?
-   Did the LLM retry?
-   How long did the LLM take?
-   How long did the complete API request take?
-   Where did the request fail?

Observability gives us operational evidence for answering those
questions.

------------------------------------------------------------------------

## 2. What we implemented

We added a lightweight observability layer using Python's built-in
`logging` module.

Main pieces:

``` text
HTTP Request
    ↓
Request ID generated
    ↓
Application performs work
    ↓
Important events recorded
    ↓
Structured JSON logs
    ↓
logs/app.log
```

We intentionally did **not** add Prometheus, Grafana, OpenTelemetry,
ELK, Datadog, or other infrastructure.

The goal was to learn the fundamentals first.

------------------------------------------------------------------------

## 3. Log files

Instead of relying on `print()`, operational events are written to:

``` text
logs/
└── app.log
```

The logging configuration lives in a small module such as:

``` text
logging_config.py
```

### Why not just `print()`?

`print()` is useful during quick debugging, but production-style
applications need persistent, searchable records.

A log file lets us inspect what happened **after** a request has
finished.

For example:

``` text
request happens
      ↓
something fails
      ↓
client receives an error
      ↓
engineer opens app.log
      ↓
engineer investigates
```

### Logs are operational data

Source code describes how the application behaves.

Logs describe what happened while the application was running.

Therefore:

``` text
source code ≠ runtime logs
```

We add:

``` gitignore
logs/
```

to `.gitignore`.

Logs should normally not be committed to Git.

------------------------------------------------------------------------

## 4. Log rotation

A server may run for days or months. Without rotation:

``` text
app.log
   ↓
grows
   ↓
grows
   ↓
grows forever
```

Eventually this can consume large amounts of disk space.

We used Python's `RotatingFileHandler`.

Conceptually:

``` text
app.log
app.log.1
app.log.2
app.log.3
```

`app.log` is the current log.

When it reaches the configured maximum size, older logs are rotated into
backup files.

A small project might use something like:

``` python
RotatingFileHandler(
    "logs/app.log",
    maxBytes=5 * 1024 * 1024,
    backupCount=3,
)
```

The exact numbers are less important than understanding the principle:

> Log files must have a retention/bounding strategy so they do not grow
> forever.

------------------------------------------------------------------------

## 5. Request IDs

Every incoming HTTP request receives a unique identifier.

Example:

``` text
7af65bf4-82a0-43dd-953b-58c05e28dbd0
```

We generate it in FastAPI middleware.

Conceptually:

``` text
Request arrives
      ↓
request_id generated
      ↓
request.state.request_id
      ↓
application processing
      ↓
logs contain request_id
      ↓
response contains X-Request-ID
```

### Why request IDs matter

Imagine thousands of requests are mixed together inside `app.log`.

Without a request ID:

``` text
user request
database operation
another user's request
LLM failure
cache operation
another request
```

It becomes difficult to determine which records belong together.

With request IDs:

``` text
request_id = abc123
```

we can search:

``` text
abc123
```

and reconstruct the important events associated with that request.

This is called **correlation**.

------------------------------------------------------------------------

## 6. Why middleware is useful for request IDs

Request IDs are HTTP-level behavior, not chatbot business logic.

Middleware sits around request processing:

``` text
HTTP request
     ↓
middleware
     ↓
endpoint
     ↓
middleware
     ↓
HTTP response
```

This makes it a clean place to:

1.  generate the ID,
2.  attach it to `request.state`,
3.  let endpoints use it,
4.  return it in `X-Request-ID`.

The endpoint does not need to generate its own identifier.

------------------------------------------------------------------------

## 7. Structured logging

Bad logging:

``` text
something happened
```

Slightly better:

``` text
chat completed for alice
```

Better production-style logging uses structured fields:

``` json
{
  "event": "chat_request_completed",
  "request_id": "abc123",
  "user_id": "alice",
  "conversation_id": 42,
  "model": "gemini-3.5-flash",
  "input_tokens": 800,
  "output_tokens": 120,
  "llm_latency_ms": 900,
  "total_latency_ms": 1050,
  "cache_hit": false,
  "attempts": 1,
  "rate_limited": false,
  "status": "success"
}
```

### Why structured logs?

Humans can read them, but software can also search and analyze
individual fields.

Instead of searching arbitrary sentences, we can reason using fields
such as:

``` text
event
request_id
user_id
conversation_id
model
status
attempts
```

Structured logs therefore make later querying and centralized logging
much easier.

------------------------------------------------------------------------

## 8. Events, not line-by-line debugging

Observability does **not** mean logging after every line.

That would create noise.

We care about important system behavior.

Examples:

``` text
chat_request_completed
chat_request_failed
chat_request_rate_limited
llm_retry
llm_cache_hit
llm_cache_miss
```

We generally do not care about logs such as:

``` text
Redis INCR called
Redis TTL called
list reversed
message appended
SQLAlchemy object created
```

Those are implementation details unless we are debugging a specific
problem.

A useful rule:

> Log meaningful state transitions and outcomes, not every
> implementation step.

------------------------------------------------------------------------

## 9. Request lifecycle observability

Our conceptual request lifecycle is:

``` text
HTTP request
     ↓
request_id
     ↓
authentication
     ↓
Redis rate limiting
     ↓
PostgreSQL conversation lookup
     ↓
conversation history
     ↓
context construction
     ↓
LLM harness
     ↓
LLM provider
     ↓
message persistence
     ↓
structured completion log
     ↓
HTTP response
```

The final completion event summarizes much of this lifecycle.

This keeps logging useful without making the application noisy.

------------------------------------------------------------------------

## 10. Total latency

Latency means elapsed time.

We measure elapsed durations with:

``` python
time.perf_counter()
```

For example:

``` python
start = time.perf_counter()

# work

elapsed = time.perf_counter() - start
```

We convert seconds to milliseconds:

``` python
latency_ms = round(elapsed * 1000)
```

We consistently use milliseconds in logs.

### Total request latency

Total latency represents the time spent handling the overall API
operation.

Conceptually:

``` text
total request latency
│
├── application work
├── Redis work
├── PostgreSQL work
├── context construction
├── LLM operation
├── message persistence
└── other overhead
```

Example:

``` text
total_latency_ms = 1050
```

------------------------------------------------------------------------

## 11. LLM latency

LLM latency measures the time associated with the LLM operation.

Our LLM harness already measures latency and returns it in:

``` python
LLMResult
```

The application therefore reuses:

``` python
result.latency
```

instead of implementing another copy of LLM timing logic.

Example:

``` text
llm_latency_ms = 900
total_latency_ms = 1050
```

This tells us roughly:

``` text
900 ms  → LLM operation
150 ms  → rest of application
```

This distinction is extremely useful.

If total latency is high but LLM latency is low, investigate the rest of
the application.

If LLM latency itself is high, the provider/retry path is likely
responsible for most of the delay.

------------------------------------------------------------------------

## 12. Important latency nuance in our harness

The harness starts its timer before the retry loop.

Therefore its latency includes:

``` text
provider attempt
+
failed attempts
+
retry backoff
+
successful attempt
```

So our LLM latency really means:

> How long did the complete LLM operation take from the application's
> perspective?

That is a useful metric for this project.

------------------------------------------------------------------------

## 13. LLM metrics

Our `LLMResult` already contains:

``` python
@dataclass
class LLMResult:
    text: str
    model: str
    latency: float
    input_tokens: int
    output_tokens: int
    attempts: int
```

Observability reuses this information.

We log:

``` text
model
input_tokens
output_tokens
attempts
llm_latency_ms
```

### Important design principle

The FastAPI layer should **not duplicate LLM logic**.

Correct separation:

``` text
LLM Harness
   ↓
knows provider/retry/token details
   ↓
returns LLMResult
   ↓
FastAPI
   ↓
logs result metadata
```

The application consumes instrumentation already owned by the component
responsible for the LLM call.

------------------------------------------------------------------------

## 14. Attempts and retries

The harness can retry transient failures.

Examples:

``` text
408 timeout
429 rate limit
5xx provider errors
connection failures
```

If the first attempt succeeds:

``` text
attempts = 1
```

If one retry was necessary:

``` text
attempts = 2
```

If two retries were necessary:

``` text
attempts = 3
```

This information matters operationally because a request may succeed
while still experiencing provider instability.

For example:

``` json
{
  "status": "success",
  "attempts": 3,
  "llm_latency_ms": 5200
}
```

The user received a successful response, but observability tells us that
it was expensive/slow because retries occurred.

------------------------------------------------------------------------

## 15. Retry logs

Individual retry events are useful warnings.

Conceptually:

``` json
{
  "event": "llm_retry",
  "attempt": 1,
  "provider_status": 429,
  "retry_in_seconds": 1
}
```

The final request log still tells us the final number of attempts.

For this lightweight implementation, we did not introduce complex
request-context propagation into the harness solely to attach request
IDs to every internal retry record.

That is an intentional simplicity tradeoff.

------------------------------------------------------------------------

## 16. Async retry bug we corrected

Inside an asynchronous function, this is problematic:

``` python
time.sleep(wait_seconds)
```

because it blocks the event loop.

Instead:

``` python
await asyncio.sleep(wait_seconds)
```

Conceptually:

``` text
time.sleep()
→ blocks the worker/event loop

await asyncio.sleep()
→ yields control while waiting
```

This is not primarily an observability feature, but it is important when
retry behavior is part of an async LLM harness.

------------------------------------------------------------------------

## 17. Redis observability

We do not log every Redis command.

For rate limiting, the important business/system event is:

``` text
rate_limited = true
```

For caching, the important behavior is:

``` text
cache_hit = true
```

or:

``` text
cache_hit = false
```

We care about:

``` text
What did Redis cause the system to do?
```

rather than:

``` text
Which low-level Redis commands ran?
```

------------------------------------------------------------------------

## 18. Cache hit vs cache miss

For the stateless endpoint:

``` text
Request
   ↓
calculate deterministic cache key
   ↓
Redis lookup
   ↓
        ┌───────────────┐
        │ cached value? │
        └───────────────┘
          ↓           ↓
         yes          no
          ↓           ↓
     cache hit    cache miss
          ↓           ↓
      response      LLM call
```

Observability records:

``` text
llm_cache_hit
```

or:

``` text
llm_cache_miss
```

A cache hit is operationally important because it explains why a request
may return very quickly and avoid an LLM call.

------------------------------------------------------------------------

## 19. Rate-limit observability

Our rate limiter uses Redis to count requests.

When the configured limit is exceeded, we log a warning event such as:

``` json
{
  "event": "chat_request_rate_limited",
  "request_id": "abc123",
  "user_id": "alice",
  "conversation_id": 42,
  "rate_limited": true,
  "status": "failed"
}
```

This helps distinguish:

``` text
LLM failure
```

from:

``` text
request intentionally rejected by our own rate limiter
```

Both may prevent a successful chat response, but their causes are
completely different.

------------------------------------------------------------------------

## 20. Error observability

Errors should also produce useful structured metadata.

Example:

``` json
{
  "event": "chat_request_failed",
  "request_id": "abc123",
  "user_id": "alice",
  "conversation_id": 42,
  "error_type": "LLMError",
  "status": "failed"
}
```

The `request_id` is particularly important because failures are exactly
when engineers often need to reconstruct what happened.

------------------------------------------------------------------------

## 21. Logging levels

We use different levels to communicate severity.

### INFO

Normal, useful operational events.

Examples:

``` text
chat completed
cache hit
cache miss
```

Meaning:

> The system is behaving normally and this event is useful to record.

### WARNING

Something unusual happened, but the system handled or intentionally
rejected it.

Examples:

``` text
LLM retry
rate limited request
```

Meaning:

> Pay attention, but this is not necessarily an application failure.

### ERROR

An operation failed.

Examples:

``` text
LLM ultimately failed
chat request could not complete
```

Meaning:

> Something prevented the requested operation from succeeding.

A simple mental model:

``` text
INFO    → normal
WARNING → abnormal but handled/noteworthy
ERROR   → operation failed
```

------------------------------------------------------------------------

## 22. Do not log secrets

Observability can accidentally become a security/privacy problem.

Never log:

``` text
JWT access tokens
Authorization headers
API keys
passwords
database passwords
secret keys
GEMINI_API_KEY
```

Logs may live longer than expected and may eventually be accessible to
operational tools or engineers.

Therefore logs must be treated as potentially sensitive data.

------------------------------------------------------------------------

## 23. Be careful with prompts and responses

Avoid blindly logging:

``` python
body.message
result.text
```

User prompts and model responses may contain:

``` text
personal information
company information
private conversations
credentials pasted accidentally
sensitive business data
```

For our observability block, we prefer:

``` text
metadata
```

instead of:

``` text
raw conversation content
```

For example, we can understand system behavior from:

``` json
{
  "input_tokens": 800,
  "output_tokens": 120,
  "model": "gemini-3.5-flash",
  "status": "success"
}
```

without knowing what the user actually said.

------------------------------------------------------------------------

## 24. Token usage

LLM APIs consume tokens.

Our harness exposes:

``` text
input_tokens
output_tokens
```

Input tokens roughly correspond to content sent to the model, including
conversation/context as counted by the provider.

Output tokens correspond to generated model output.

Token usage is important for both:

``` text
context-size awareness
```

and:

``` text
cost awareness
```

------------------------------------------------------------------------

## 25. Cost awareness

The basic relationship is:

``` text
tokens
   ↓
provider pricing
   ↓
money
```

Conceptually:

``` text
estimated cost
=
input token usage × input token price
+
output token usage × output token price
```

If pricing configuration is expressed per one million tokens:

``` python
estimated_cost = (
    input_tokens / 1_000_000 * INPUT_PRICE_PER_MILLION
    + output_tokens / 1_000_000 * OUTPUT_PRICE_PER_MILLION
)
```

We intentionally do not hardcode provider prices into the observability
implementation unless pricing is explicitly maintained as configuration.

Provider pricing can change.

For now, preserving:

``` text
input_tokens
output_tokens
model
```

gives us the data needed for later cost analysis.

------------------------------------------------------------------------

## 26. Why model name matters

Token counts alone are not always enough for cost analysis because
different models may have different prices.

Therefore a useful usage record includes:

``` text
model
input_tokens
output_tokens
```

Conceptually:

``` text
model + token usage
        ↓
pricing configuration
        ↓
estimated cost
```

------------------------------------------------------------------------

## 27. Successful request record

A useful final request event contains enough metadata to understand the
outcome:

``` json
{
  "event": "chat_request_completed",
  "request_id": "...",
  "user_id": "...",
  "conversation_id": 42,
  "model": "...",
  "input_tokens": 800,
  "output_tokens": 120,
  "llm_latency_ms": 900,
  "total_latency_ms": 1050,
  "cache_hit": false,
  "attempts": 1,
  "rate_limited": false,
  "status": "success"
}
```

From one record we can answer:

``` text
Who made the request?
Which conversation?
Which model?
How many tokens?
How many attempts?
How long did the LLM take?
How long did everything take?
Was caching involved?
Was it rate limited?
Did it succeed?
```

------------------------------------------------------------------------

## 28. Testing observability

We test system behaviors, then inspect:

``` text
logs/app.log
```

### Test 1 --- Normal request

Make a valid `/chat` request.

Look for:

``` text
chat_request_completed
status = success
attempts
input_tokens
output_tokens
llm_latency_ms
total_latency_ms
```

### Test 2 --- Cache hit

Call the stateless cache endpoint twice with the same effective input
before the TTL expires.

Expected:

``` text
first request  → cache miss
second request → cache hit
```

### Test 3 --- Rate limit

With a deliberately small development rate limit, make enough requests
inside the window to exceed it.

Expected:

``` text
HTTP 429
```

and a warning log containing:

``` text
rate_limited = true
```

### Test 4 --- Safe error

If safely testable in local development, trigger a controlled
provider/application failure.

Expected:

``` text
chat_request_failed
status = failed
error_type = ...
request_id = ...
```

Do not perform unsafe tests against production credentials or systems.

------------------------------------------------------------------------

## 29. How to investigate a request

Suppose the HTTP response contains:

``` text
X-Request-ID: abc123
```

Open:

``` text
logs/app.log
```

and search for:

``` text
abc123
```

Then inspect the associated metadata.

This is the basic debugging workflow:

``` text
problem reported
      ↓
get request_id
      ↓
search logs
      ↓
inspect events/metadata
      ↓
understand what happened
```

------------------------------------------------------------------------

## 30. Local logs vs centralized logging

Local files are enough for this learning project and some simple
deployments.

But imagine production has three FastAPI servers:

``` text
                Load Balancer
                     ↓
        ┌────────────┼────────────┐
        ↓            ↓            ↓
   FastAPI A     FastAPI B    FastAPI C
        ↓            ↓            ↓
    app.log       app.log       app.log
```

A user's request could reach any server.

Now investigating `request_id=abc123` requires knowing which machine
handled the request.

This becomes difficult as the number of servers grows.

Production systems therefore commonly centralize logs:

``` text
FastAPI A ──┐
FastAPI B ──┼──→ centralized logging system
FastAPI C ──┘
```

Then engineers can search all application instances from one place.

We did **not** implement centralized logging in this block.

The important concept is:

> Structured local logging is the foundation; centralized logging
> becomes useful when logs are distributed across multiple machines or
> services.

------------------------------------------------------------------------

## 31. Observability vs logging

Logging is one tool used for observability.

They are not exactly the same concept.

``` text
Observability
    ↓
ability to understand system behavior
```

Logging provides records that help achieve that.

More advanced systems may also use metrics and distributed traces, but
our lightweight implementation intentionally focuses on structured
application logs plus latency/token metadata.

So:

``` text
logging ⊂ observability
```

For this block, logging gives us enough observability to understand
individual AI requests.

------------------------------------------------------------------------

## 32. What belongs in each layer

### FastAPI

Knows:

``` text
request_id
authenticated user
conversation ID
HTTP outcome
rate-limit outcome
total request latency
```

### Redis

Provides behavior used for:

``` text
rate limiting
cache hit/miss
```

We observe the meaningful outcome rather than every Redis command.

### PostgreSQL

Stores:

``` text
conversations
messages
```

We do not log raw stored conversation content.

### LLM Harness

Knows:

``` text
model
provider operation
retry behavior
attempts
token usage
LLM latency
```

### Logging layer

Records useful metadata from these components.

This preserves separation of concerns.

------------------------------------------------------------------------

## 33. Key architecture after Block 8

``` text
Client
  ↓
HTTP Request
  ↓
Request-ID Middleware
  │
  └── request_id
  ↓
JWT Authentication
  ↓
FastAPI /chat
  │
  ├── start total latency timer
  │
  ├── Redis rate limiting
  │
  ├── PostgreSQL conversation/history
  │
  ├── Context Builder
  │
  └── LLM Harness
  │       │
  │       ├── provider call
  │       ├── retries
  │       ├── model
  │       ├── token usage
  │       ├── attempts
  │       └── LLM latency
  │
  ├── persist messages
  │
  ├── calculate total latency
  │
  └── structured log
          ↓
      logs/app.log
          ↓
HTTP Response
  +
X-Request-ID
```

------------------------------------------------------------------------

## 34. Main design lessons

### Lesson 1 --- Give every request an identity

``` text
request → request_id
```

Without correlation, logs from concurrent requests become difficult to
reason about.

### Lesson 2 --- Log metadata, not noise

Prefer:

``` text
chat completed
rate limited
cache hit
retry
failure
```

over logging every low-level operation.

### Lesson 3 --- Structure your logs

Prefer fields such as:

``` text
event
request_id
user_id
model
latency
status
```

over arbitrary strings.

### Lesson 4 --- Measure different kinds of latency

``` text
LLM latency ≠ total request latency
```

That distinction helps locate performance problems.

### Lesson 5 --- Let components own their metrics

The LLM harness already knows token usage, attempts, model, and LLM
latency.

FastAPI should reuse them rather than duplicate provider logic.

### Lesson 6 --- Successful requests can still reveal problems

A request with:

``` text
status = success
attempts = 3
```

succeeded, but retries reveal instability.

### Lesson 7 --- Tokens matter operationally

``` text
tokens → usage → cost
```

Token metrics are useful even before actual cost calculation is
implemented.

### Lesson 8 --- Logs require security discipline

Do not blindly log secrets, prompts, or responses.

### Lesson 9 --- Rotate local logs

Persistent logs without retention limits can eventually consume disk
space.

### Lesson 10 --- Local logging eventually stops scaling

Once many application instances exist, centralized log search becomes
valuable.

------------------------------------------------------------------------

# Quick Revision Cheat Sheet

``` text
OBSERVABILITY
= ability to understand what happened inside a running system

REQUEST ID
= unique identifier used to correlate events belonging to one HTTP request

STRUCTURED LOG
= log represented using named fields rather than arbitrary text

INFO
= normal operational event

WARNING
= unusual/noteworthy event that is handled

ERROR
= operation failed

TOTAL LATENCY
= overall API processing time

LLM LATENCY
= time spent completing the LLM operation

ATTEMPTS
= number of provider attempts required by the harness

CACHE HIT
= Redis already had the reusable result

CACHE MISS
= result was not cached, so normal computation/LLM work is required

RATE LIMITED
= request rejected because the allowed request rate was exceeded

INPUT TOKENS
= tokens sent to the model

OUTPUT TOKENS
= tokens generated by the model

COST AWARENESS
= model + token usage + configured pricing → estimated cost

LOG ROTATION
= bound log-file growth and retain a small number of older files

LOCAL LOGGING
= simple and useful for one/few application instances

CENTRALIZED LOGGING
= necessary later when logs are spread across many servers
```

# What to remember for interviews and system design

If asked, **"How would you add basic observability to an AI API?"**, a
strong concise answer is:

> I would assign every HTTP request a request ID and propagate it into
> structured logs. I would log meaningful lifecycle outcomes rather than
> every implementation operation. For AI requests I would capture the
> authenticated user identifier, conversation identifier, model,
> input/output token usage, retry attempts, LLM latency, total request
> latency, cache/rate-limit outcomes, status, and safe error metadata. I
> would avoid logging credentials and raw prompts/responses by default.
> For a simple deployment I could write JSON logs to rotating local
> files, while larger distributed deployments would normally send those
> structured logs to a centralized logging system.

------------------------------------------------------------------------

# Block 8 Definition of Done

You should now understand:

-   observability
-   structured logging
-   request IDs and correlation
-   Python file logging
-   rotating log files
-   INFO / WARNING / ERROR
-   total request latency
-   LLM latency
-   token usage
-   retries and attempts
-   cache hit/miss observability
-   rate-limit observability
-   safe error metadata
-   token-based cost awareness
-   why secrets/prompts should not blindly be logged
-   why local logs become difficult across multiple servers
-   why centralized logging exists

The central idea of Block 8 is:

``` text
A request should leave enough safe, structured evidence behind
that we can understand what happened after the request is over.
```
