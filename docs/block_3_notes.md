# Block 3 — Turning an LLM Harness into an HTTP Service

## The big picture

```text
Client
  ↓ HTTP
FastAPI (app.py)
  ↓
LLM Harness (llm_harness.py)
  ↓
LLM Provider (Gemini)
```

The harness didn't change conceptually — it's still the only thing that knows about retries, backoff, timeouts, and the provider SDK. FastAPI just gave it a new front door (HTTP) in addition to the CLI front door you already had. **Same capability, two different clients.**

---

## 1. FastAPI basics

- **Server**: the running process (`uvicorn`) that listens on a port and accepts connections.
- **Route / endpoint**: a Python function decorated with `@app.get(...)` or `@app.post(...)` that runs when a matching HTTP request arrives.
- **HTTP method**: the verb of the request — `GET` (fetch/read, no body needed) vs `POST` (send data in a body, usually to create/do something). We used `GET /health` and `POST /chat`.
- **Request / Response**: the data going in and out of an endpoint. In our case, both are JSON.
- **JSON**: a plain text format for structured data (`{"key": "value"}`) that's the default way web APIs exchange data.

`/docs` is FastAPI's auto-generated Swagger UI — a browsable, testable version of your API contract, built automatically from your code.

---

## 2. API contract (Pydantic models)

An endpoint is a **contract** between the client and your service: "send me data shaped like *this*, and I'll send you back data shaped like *that*." Without a contract, arbitrary JSON (or arbitrary Python objects) could reach your business logic and blow up in unpredictable ways.

Pydantic models define that contract as Python classes:

```python
class ChatRequest(BaseModel):
    message: str

class Usage(BaseModel):
    input_tokens: int
    output_tokens: int

class ChatResponse(BaseModel):
    response: str
    model: str
    usage: Usage
    latency_ms: int
```

- `body: ChatRequest` on a route tells FastAPI: parse and validate incoming JSON against this shape *before* my function body runs.
- `response_model=ChatResponse` does the same for the outgoing JSON, and it's also what generates the schema shown in `/docs`.

---

## 3. Validation — what's automatic vs. what's yours

**FastAPI/Pydantic handle automatically (shape validation):**

- Missing required fields → `422`
- Wrong types (e.g. sending a number where a string is expected) → `422`
- Malformed JSON → `422`

**Your app must handle (meaning/business-rule validation):**

- An empty string `""` is a perfectly valid `str` — Pydantic lets it through. "A message can't be blank" is a rule specific to *your* app, not a general type rule.

We added this with a field validator:

```python
class ChatRequest(BaseModel):
    message: str

    @field_validator("message")
    @classmethod
    def message_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("message must not be empty")
        return value
```

Raising `ValueError` inside a validator makes Pydantic fail validation the same way it does for missing/wrong-type fields — FastAPI turns it into a `422` automatically.

**Rule of thumb:** Pydantic validates *shape*. You validate *meaning*.

---

## 4. HTTP status codes

Only the distinction that matters at this level:

| Range | Meaning | Example in our app |
| --- | --- | --- |
| `2xx` | Success | `200 OK` — chat response returned normally |
| `4xx` | Client/request problem | `422` — missing/blank/invalid message |
| `5xx` | Server/provider problem | Harness exhausted retries, provider down |

The goal: harness failures (`LLMError`) shouldn't crash into a generic unhandled `500` — they should map to a status code that tells the client *whose fault* the failure is (their bad input vs. our/provider's problem).

*(You marked steps 1–2 done and moved on — revisit this section once you've wired up the actual exception handler mapping `LLMError` → specific status codes if you want the full mapping written out.)*

---

## 5. Async — why it matters for LLM calls

Calling an LLM provider is **I/O-bound work**, not CPU-bound work: your process sends bytes over the network, then does *nothing* but wait for bytes to come back. That waiting time is "wasted" if the server can't do anything else during it.

```
Request A  → sends to Gemini → waiting...
Request B  →                              → server handles this while A waits
Request A  ← Gemini responds ← resumes, returns to client
```

`async`/`await` lets the server say: "this call is just waiting on the network — go handle other requests, come back when the response arrives." This only helps for I/O waits (network, disk) — Python still only executes one thing at a time per process, so it does **not** speed up CPU-heavy work.

Changes made:

- `generate()` in `llm_harness.py` became `async def`, and the SDK call switched to the async client:

  ```python
  response = await client.aio.models.generate_content(...)
  ```

- The route in `app.py` became `async def chat(...)`, calling `await generate(body.message)`.

**Known caveat (not required to fix):** `time.sleep()` used during retry backoff is still a *blocking* sleep even inside an async function — it would freeze the whole server during that pause, not just the current request. The correct fix is `asyncio.sleep(...)` with `await`, but this wasn't required to complete Block 3 since backoff only triggers on retries.

---

## 6. Why the API layer and the harness stay separate

`app.py` (API layer):

- Knows about HTTP: routes, methods, request/response shapes, status codes.
- Has **zero** knowledge of Gemini, retries, backoff, or provider-specific errors.

`llm_harness.py` (harness layer):

- Knows about the LLM provider: SDK calls, timeouts, retry/backoff logic, provider-specific error codes.
- Has **zero** knowledge of HTTP, JSON responses, or status codes.

Why this separation matters: the CLI and the FastAPI service are both just *callers* of the same harness function. If you swapped providers, or added a third client (say, a Slack bot) tomorrow, none of that logic needs to change — only the harness. This is the core idea behind turning an "AI capability" into a reusable service rather than a single script.

---

## 7. Manual testing checklist

Using `curl` or Swagger UI (`/docs`):

| Test | Input | Expected |
| --- | --- | --- |
| Valid message | `{"message": "What is an embedding?"}` | `200`, real LLM response + usage/latency |
| Missing field | `{}` | `422`, "field required" |
| Wrong type | `{"message": 123}` | `422`, type error |
| Empty message | `{"message": ""}` | `422`, "message must not be empty" |
| Whitespace-only | `{"message": "   "}` | `422`, same custom error |

---

## Full request lifecycle (definition of done)

```
Client
  ↓ HTTP POST /chat
FastAPI routing            → matches method + path to the chat() function
  ↓
Request validation         → Pydantic checks shape (ChatRequest) + your custom rule (non-blank)
  ↓
Endpoint (chat())          → calls the harness, has no LLM-specific knowledge
  ↓
LLM harness (generate())   → owns retries, backoff, timeout, provider error handling
  ↓
LLM provider (Gemini)      → actually generates the text
  ↓
Harness result (LLMResult) → returned back up to the endpoint
  ↓
JSON HTTP response         → shaped by ChatResponse, sent back
  ↓
Client                     → receives response, model, usage, latency_ms
```

## Self-check — can you explain these?

- [ ] What an API endpoint is
- [ ] GET vs POST at a basic level
- [ ] What a JSON request/response is
- [ ] What an API contract is, and why Pydantic models define one
- [ ] Why request validation matters, and what's automatic vs. what you must add
- [ ] Basic 2xx / 4xx / 5xx semantics
- [ ] Why the API layer and the harness are kept separate
- [ ] Why async helps for network-bound LLM calls (and why it wouldn't help for CPU-bound work)
- [ ] The complete lifecycle of `POST /chat`, start to finish
