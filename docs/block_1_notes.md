# Block 1: The Smallest Working LLM Application

**Goal:** `User → Terminal → Python → LLM API → Response`

Final structure:
```
project/
├── app.py
├── .env
├── .gitignore
└── requirements.txt
```

---

## 1. How an LLM API Call Works

```
Python → SDK/client → network request → LLM provider/model → response → Python
```

Your code never talks to the model directly. The SDK (`google-genai`) packages your request into an HTTP call, sends it over the network to the provider's servers, the model generates output, and the result comes back as structured data (JSON under the hood) that the SDK turns into a Python object.

Every AI application — no matter how complex — is built from this one round trip repeated and orchestrated in different ways.

---

## 2. Messages

Three roles make up a conversation:

| Role | Purpose |
|---|---|
| **system** | Sets the AI's behavior/persona/instructions. Not visible to the user, but shapes every response. |
| **user** | What the human is asking or saying. |
| **assistant** | The model's generated reply. |

In our code, the system instruction was set once via `types.GenerateContentConfig(system_instruction=...)`, and the user's terminal input was passed as `contents`.

---

## 3. Statelessness

**The API has no memory between calls.** Each request is completely isolated — the server doesn't know what you asked five seconds ago.

Demonstrated with:
```
You: My name is Sam
AI: Nice to meet you, Sam!

You: What is my name?
AI: I don't have access to your name — could you tell me?
```

The second call's **input token count stayed just as small as the first** — proof that the earlier message was never resent. If we wanted the model to "remember," our application would need to manually collect and resend the full conversation history on every request. That's a job for Block 2 — not implemented yet.

**Key takeaway:** the model doesn't forget — there was never anything to remember. Memory is an *application-level* responsibility, not a model feature.

---

## 4. Tokens

Tokens are the chunks of text (roughly ¾ of a word) that models read and generate.

- **Input tokens** — your prompt + system message, counted before generation.
- **Output tokens** — the model's generated response.
- **Why they affect cost** — providers bill per token, input and output priced separately (output is usually more expensive).
- **Why they affect context management** — every model has a maximum context window (input + output tokens combined). As conversation history grows (once we add memory in a later block), token count climbs and eventually forces truncation, summarization, or windowing strategies.

Retrieved directly from the API response:
```python
usage = response.usage_metadata
input_tokens = usage.prompt_token_count
output_tokens = usage.candidates_token_count
```

---

## 5. Latency

Measured by timestamping immediately before and after the API call:

```python
start = time.time()
response = client.models.generate_content(...)
latency = time.time() - start
```

This captures the **entire round trip** — network handshake, request transfer, server-side model generation, and response transfer back. It is *not* just "model thinking time."

**Why it matters:** latency is a core system-design metric. It drives UX decisions like whether to stream responses, show loading indicators, or cache results. Production systems track latency *distributions* (p50/p95/p99) rather than single-call averages, since averages hide bad outliers.

---

## 6. API Keys

- Stored in `.env`, loaded via `python-dotenv`:
  ```python
  load_dotenv()
  client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))
  ```
- **Never hardcoded** in source files.
- `.env` added to `.gitignore` so it's never committed to version control.

This is the most basic security boundary in any AI system: secrets are separated from code.

---

## 7. Basic Failure Modes

Only three failures matter at this stage — no retries, no fallback logic, just clear diagnostics:

| Failure | Cause | What you see |
|---|---|---|
| **Missing/invalid API key** | Auth fails before reaching the model | `[API error]` — authentication/permission denied |
| **Invalid model name** | Model string doesn't exist or isn't accessible | `[API error]` — model not found |
| **Provider/network failure** | No internet, DNS issue, provider outage | `[Unexpected error]` — connection failure |

```python
try:
    reply, latency, input_tokens, output_tokens = ask(user_input)
    ...
except errors.APIError as e:
    print(f"[API error] {e}")
except Exception as e:
    print(f"[Unexpected error] {e}")
```

**Why it matters:** distinguishing "my code is broken" vs "my credentials are broken" vs "the network/provider is broken" is the first triage step in any real incident. This makes failures *legible* — the prerequisite for building retries, fallbacks, or circuit breakers later.

---

## Final `app.py` (end of Block 1)

```python
import os
import time
from dotenv import load_dotenv
from google import genai
from google.genai import types
from google.genai import errors

load_dotenv()

client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))

def ask(user_input):
    start = time.time()
    response = client.models.generate_content(
        model="gemini-2.0-flash",
        contents=user_input,
        config=types.GenerateContentConfig(
            system_instruction="You are a concise, helpful assistant."
        )
    )
    latency = time.time() - start

    usage = response.usage_metadata
    input_tokens = usage.prompt_token_count
    output_tokens = usage.candidates_token_count

    return response.text, latency, input_tokens, output_tokens

while True:
    user_input = input("You: ")
    if user_input.lower() in ("exit", "quit"):
        break

    try:
        reply, latency, input_tokens, output_tokens = ask(user_input)
        print("AI:", reply)
        print(f"Latency: {latency:.2f}s")
        print(f"Input tokens: {input_tokens}")
        print(f"Output tokens: {output_tokens}")

    except errors.APIError as e:
        print(f"[API error] {e}")
    except Exception as e:
        print(f"[Unexpected error] {e}")
```

---

## Definition of Done — Self-Check

You should now be able to explain, without looking anything up:

- [ ] What happens when Python calls an LLM (the full round trip)
- [ ] Request vs response
- [ ] System / user / assistant messages
- [ ] Why the call is stateless
- [ ] Input vs output tokens
- [ ] Why tokens affect cost
- [ ] What latency means (and what it does *not* measure)
- [ ] Why API keys belong outside source code
- [ ] What can cause an LLM API call to fail

**Not yet implemented (future blocks):** conversation memory, retries, streaming, RAG, agents, production architecture (FastAPI, Docker, DB, auth).
