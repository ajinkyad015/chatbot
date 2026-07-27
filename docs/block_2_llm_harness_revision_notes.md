# LLM Harness --- Revision Notes

## 1. What is an LLM Harness?

An **LLM harness** is a layer between the rest of your application and
the LLM provider/model.

Instead of calling Gemini, OpenAI, Claude, or another model directly
from your API route, the application calls a function in the harness.

``` text
Client
  |
  v
FastAPI / Application
  |
  v
LLM Harness
  |
  v
LLM Provider / Model
```

The harness gives the application **one controlled place for LLM-related
behavior**.

In our project, the idea is roughly:

``` python
response = generate(prompt)
```

The rest of the application does not need to know all the details of how
the model is called.

------------------------------------------------------------------------

## 2. Why Create a Separate Harness?

A simple application could put the model call directly inside a FastAPI
endpoint:

``` python
@app.post("/chat")
async def chat(request):
    response = client.models.generate_content(...)
    return response.text
```

This works initially, but the API layer becomes responsible for too many
things:

-   HTTP handling
-   model configuration
-   timeouts
-   retries
-   error handling
-   provider-specific exceptions
-   response extraction
-   logging and observability

A harness separates these responsibilities.

``` text
FastAPI
  |
  | generate(prompt)
  v
LLM Harness
  |
  | provider-specific call
  v
Gemini
```

This is an example of **separation of concerns**.

------------------------------------------------------------------------

## 3. Core Responsibility of the Harness

The harness should answer a simple application-level question:

> "Given this input, generate a model response."

For example:

``` python
result = await generate(prompt)
```

Internally, the harness may perform several operations:

``` text
generate(prompt)
      |
      v
Validate/configure request
      |
      v
Call model
      |
      v
Wait with timeout
      |
      +---- failure ----> retry if appropriate
      |
      v
Extract response
      |
      v
Return result
```

The caller gets a simple interface while the complexity remains inside
the harness.

------------------------------------------------------------------------

## 4. Model Configuration

A harness commonly centralizes the model configuration.

Example:

``` python
MODEL = "gemini-3.5-flash"
TIMEOUT_SECONDS = 10
MAX_ATTEMPTS = 3
BASE_BACKOFF_SECONDS = 1
```

These values represent operational decisions.

### `MODEL`

Specifies which model the harness calls.

``` python
MODEL = "gemini-3.5-flash"
```

Keeping this in one place makes model changes easier.

### `TIMEOUT_SECONDS`

Defines how long the application is willing to wait for the LLM.

``` python
TIMEOUT_SECONDS = 10
```

LLM APIs are remote services. They can become slow or unavailable.

Without a timeout, a request could remain stuck for an undesirable
amount of time.

### `MAX_ATTEMPTS`

Controls how many attempts may be made when retryable failures occur.

``` python
MAX_ATTEMPTS = 3
```

This does **not** mean every error should be retried.

### `BASE_BACKOFF_SECONDS`

Controls the initial delay used for retry backoff.

``` python
BASE_BACKOFF_SECONDS = 1
```

Later attempts can wait longer than earlier attempts.

------------------------------------------------------------------------

## 5. Environment Variables

API keys should not be hard-coded into source code.

Example:

``` python
import os
from dotenv import load_dotenv

load_dotenv()

api_key = os.environ.get("GEMINI_API_KEY")
```

A `.env` file might contain:

``` text
GEMINI_API_KEY=...
```

The important principle is:

``` text
Source code       -> application logic
Environment       -> secrets/configuration
```

Benefits include:

-   avoiding committing secrets to Git
-   different configuration for development and production
-   easier secret rotation
-   cleaner deployment configuration

In production, secrets are usually supplied by the deployment platform
or a secret-management system rather than a committed `.env` file.

------------------------------------------------------------------------

## 6. LLM Client

The provider SDK client is initialized using configuration such as the
API key.

Conceptually:

``` python
client = genai.Client(
    api_key=os.environ.get("GEMINI_API_KEY")
)
```

Then the harness uses this client when making requests.

This keeps provider-specific code out of the FastAPI route.

------------------------------------------------------------------------

## 7. The `generate()` Function

The central function of a basic LLM harness is usually something like:

``` python
async def generate(prompt: str):
    ...
```

The application only needs to know:

``` python
response = await generate(prompt)
```

It should not need to know:

-   which SDK is being used
-   how retries work
-   how provider exceptions are represented
-   how timeout logic works
-   how the response object is parsed

This creates an **abstraction boundary**.

``` text
Application contract:

input  -> prompt
output -> generated response
error  -> application-level LLM error
```

------------------------------------------------------------------------

## 8. Async LLM Calls

LLM calls are primarily **I/O-bound operations**.

The application sends a network request and spends much of the time
waiting for the remote provider.

That is why asynchronous code is useful.

``` python
async def generate(...):
    response = await ...
```

During the wait, the server can work on other requests rather than
blocking that execution path unnecessarily.

Conceptually:

``` text
Request A -> waiting for LLM
                  |
                  | server can process
                  v
             Request B
```

This is especially important for web APIs handling concurrent users.

------------------------------------------------------------------------

## 9. Timeout Handling

External services should generally have bounded waiting times.

A timeout protects your application when the model provider is too slow.

Conceptually:

``` python
try:
    response = await asyncio.wait_for(
        model_call(),
        timeout=TIMEOUT_SECONDS
    )
except asyncio.TimeoutError:
    ...
```

Without a timeout:

``` text
Application -> provider
                |
                | very slow response
                |
                v
          request stays waiting
```

With a timeout:

``` text
Application -> provider
                |
          timeout reached
                |
                v
       controlled failure
```

Timeouts are a **reliability mechanism**.

------------------------------------------------------------------------

## 10. Retries

Some LLM failures are temporary.

Examples include:

-   transient network failures
-   temporary server errors
-   rate-limit responses
-   brief provider unavailability

A retry mechanism allows the application to try again when appropriate.

Conceptually:

``` python
for attempt in range(MAX_ATTEMPTS):
    try:
        return await call_model()
    except RetryableError:
        ...
```

The key principle is:

> Retry failures that may succeed later; do not blindly retry every
> failure.

For example, an invalid API key will usually not become valid one second
later.

------------------------------------------------------------------------

## 11. Exponential Backoff

Retrying immediately can make outages and rate limiting worse.

Instead, retries should usually wait progressively longer.

A common formula is:

``` python
delay = BASE_BACKOFF_SECONDS * (2 ** attempt)
```

If:

``` text
BASE_BACKOFF_SECONDS = 1
```

the delays may look like:

``` text
Attempt 1 fails
wait 1 second

Attempt 2 fails
wait 2 seconds

Attempt 3 fails
wait 4 seconds
```

This pattern is called **exponential backoff**.

It reduces pressure on an already struggling external service.

In production systems, **jitter** is often added so many servers do not
retry at exactly the same time.

------------------------------------------------------------------------

## 12. Retryable vs Non-Retryable Errors

An important production concept is distinguishing between error types.

### Potentially retryable

Examples:

``` text
429 Too Many Requests
500 Internal Server Error
502 Bad Gateway
503 Service Unavailable
network interruption
temporary timeout
```

### Usually non-retryable

Examples:

``` text
invalid API key
invalid request
unsupported model
malformed parameters
authorization failure
```

The exact classification depends on the provider and API.

A strong harness therefore asks:

``` text
Did the request fail?
       |
       v
Is the failure temporary?
   /             \
 yes              no
 |                 |
retry          fail immediately
```

------------------------------------------------------------------------

## 13. Custom `LLMError`

Provider SDKs expose their own exception classes.

For example, Gemini may throw Gemini-specific exceptions.

You generally do not want the rest of your application tightly coupled
to those exceptions.

Instead, the harness can expose an application-level exception:

``` python
class LLMError(Exception):
    pass
```

Then:

``` python
try:
    ...
except ProviderError as exc:
    raise LLMError(...) from exc
```

The architecture becomes:

``` text
Gemini error
    |
    v
LLM Harness
    |
    v
LLMError
    |
    v
FastAPI
```

This is called **exception translation**.

The application understands your abstraction rather than every
provider's SDK.

------------------------------------------------------------------------

## 14. Why Exception Translation Matters

Suppose FastAPI directly handles:

``` python
google.genai.errors.ServerError
```

Now your API layer knows that Gemini is the provider.

If you later switch providers, multiple application layers may require
changes.

With a harness:

``` python
except LLMError:
    ...
```

the provider can potentially change while the API contract remains
stable.

``` text
Before

FastAPI -> Gemini SDK details


After

FastAPI -> LLM Harness -> Gemini SDK
              ^
              |
         stable boundary
```

This is an important maintainability principle.

------------------------------------------------------------------------

## 15. Harness and FastAPI Responsibilities

The FastAPI layer should mainly deal with HTTP concerns.

Example responsibilities:

``` text
FastAPI
------------------------
receive HTTP request
validate request schema
authenticate user
call application/harness
convert result to HTTP response
map application errors to HTTP errors
```

The harness deals with LLM concerns:

``` text
LLM Harness
------------------------
model selection
provider client
LLM request
timeouts
retries
backoff
provider error handling
response extraction
```

Keeping these layers separate makes the system easier to test and
evolve.

------------------------------------------------------------------------

## 16. Request Flow in Our Architecture

A simplified request flow is:

``` text
User
 |
 | POST /chat
 v
FastAPI
 |
 | authentication / validation
 v
Chat endpoint
 |
 | generate(...)
 v
LLM Harness
 |
 | provider API request
 v
Gemini
 |
 | model response
 v
LLM Harness
 |
 | normalized result
 v
FastAPI
 |
 v
User
```

If something goes wrong:

``` text
Gemini/provider failure
        |
        v
   Harness checks
        |
        +---- retryable ----> backoff -> retry
        |
        +---- fatal --------> LLMError
                                  |
                                  v
                               FastAPI
                                  |
                                  v
                         appropriate HTTP error
```

------------------------------------------------------------------------

## 17. Why Not Put Everything in `app.py`?

Putting everything into one file may initially be faster:

``` text
app.py
  authentication
  API routes
  model client
  retries
  timeout handling
  logging
  validation
```

But the file quickly becomes difficult to maintain.

Our modular structure moves responsibilities into separate modules:

``` text
app.py
authentication.py
validation.py
schema.py
llm_harness.py
```

For the LLM specifically:

``` text
app.py
   |
   v
llm_harness.py
   |
   v
provider SDK
```

This improves:

-   readability
-   maintainability
-   testability
-   provider replacement
-   configuration management

------------------------------------------------------------------------

## 18. Harness vs Model

These terms should not be confused.

### Model

The actual AI model:

``` text
Gemini
GPT
Claude
Llama
```

### Harness

Infrastructure around the model call:

``` text
timeouts
retries
error normalization
configuration
response handling
logging
metrics
```

Analogy:

``` text
Model   = engine
Harness = controlled machinery around the engine
```

The harness does not make the model intelligent. It makes model usage
more controlled and reliable.

------------------------------------------------------------------------

## 19. Harness vs API Endpoint

Another distinction:

### API endpoint

Handles communication with your application's client.

``` text
POST /chat
```

### LLM harness

Handles communication between your application and the LLM provider.

``` text
Client
   |
   v
FastAPI endpoint
   |
   v
LLM harness
   |
   v
LLM provider
```

These are different architectural layers.

------------------------------------------------------------------------

## 20. Reliability Pattern We Implemented

The basic reliability strategy can be summarized as:

``` text
               generate(prompt)
                     |
                     v
                call model
                     |
          +----------+----------+
          |                     |
       success                failure
          |                     |
          v                     v
       return            classify failure
                                |
                    +-----------+-----------+
                    |                       |
                retryable              non-retryable
                    |                       |
                    v                       v
                 backoff                LLMError
                    |
                    v
                  retry
```

The main concepts are:

1.  **Timeout** --- don't wait forever.
2.  **Retry** --- recover from temporary failures.
3.  **Backoff** --- don't retry aggressively.
4.  **Error translation** --- hide provider-specific exceptions.
5.  **Abstraction** --- give the application a simple interface.

------------------------------------------------------------------------

## 21. What Makes This Useful in Production?

A raw model call is easy:

``` python
response = model.generate(...)
```

A production application has to consider:

``` text
What if the provider is slow?
What if the request times out?
What if the provider returns 503?
What if we are rate limited?
What should FastAPI receive?
How do we switch models later?
How do we measure latency?
How do we log failures?
```

The harness becomes the natural location for solving these operational
concerns.

------------------------------------------------------------------------

## 22. What Can Be Added Later?

Our current harness establishes the foundation.

A more advanced harness can add:

### Observability

``` text
request latency
model name
token usage
error count
retry count
success/failure
```

### Cost tracking

``` text
input tokens
output tokens
estimated request cost
```

### Multiple models

``` python
generate(prompt, model="...")
```

or routing:

``` text
simple request -> fast/cheap model
complex request -> stronger model
```

### Fallback providers

``` text
Primary model fails
       |
       v
Fallback model
```

### Structured outputs

Instead of returning arbitrary text:

``` text
LLM -> validated structured response
```

### Evaluation

Responses can later be evaluated for:

-   correctness
-   relevance
-   hallucinations
-   safety
-   latency
-   cost

------------------------------------------------------------------------

## 23. Important Design Principle: Provider Isolation

One of the most valuable architectural ideas in the harness is
**provider isolation**.

Bad coupling:

``` text
app.py
  |
  +--> Gemini classes
  +--> Gemini errors
  +--> Gemini configuration
  +--> Gemini response objects
```

Better:

``` text
app.py
  |
  v
LLM Harness
  |
  v
Gemini
```

Only the harness needs deep knowledge of Gemini.

If the provider changes:

``` text
Gemini -> another provider
```

the amount of application code that needs modification is reduced.

------------------------------------------------------------------------

## 24. Important Design Principle: Single Responsibility

Each module should have a clear responsibility.

``` text
authentication.py
    -> authentication

validation.py
    -> validation

schema.py
    -> request/response structures

llm_harness.py
    -> LLM interaction and reliability

app.py
    -> HTTP/API orchestration
```

This is closely related to the **Single Responsibility Principle**.

It does not mean every function must have its own file. It means modules
should have coherent responsibilities.

------------------------------------------------------------------------

## 25. Important Design Principle: Fail Predictably

External APIs will eventually fail.

A production system should not assume:

``` text
LLM always succeeds
```

Instead:

``` text
LLM may fail
    |
    v
failure is expected
    |
    v
timeout + retry + controlled errors
```

The goal is not to eliminate failure.

The goal is to make failure **bounded, observable, and manageable**.

------------------------------------------------------------------------

## 26. Quick Code Skeleton

A simplified conceptual harness looks like:

``` python
import asyncio


class LLMError(Exception):
    pass


MODEL = "..."
TIMEOUT_SECONDS = 10
MAX_ATTEMPTS = 3
BASE_BACKOFF_SECONDS = 1


async def generate(prompt: str) -> str:

    for attempt in range(MAX_ATTEMPTS):

        try:
            response = await asyncio.wait_for(
                call_provider(prompt),
                timeout=TIMEOUT_SECONDS,
            )

            return extract_text(response)

        except RetryableProviderError as exc:

            if attempt == MAX_ATTEMPTS - 1:
                raise LLMError("LLM request failed") from exc

            delay = BASE_BACKOFF_SECONDS * (2 ** attempt)
            await asyncio.sleep(delay)

        except Exception as exc:
            raise LLMError("LLM request failed") from exc
```

This is a conceptual revision example, not necessarily an exact copy of
the project's current source.

------------------------------------------------------------------------

## 27. Interview / Revision Questions

### What is an LLM harness?

A layer that centralizes and controls interaction with an LLM, including
model calls, configuration, reliability behavior, and error handling.

### Why not call the LLM directly from FastAPI?

Because it couples HTTP logic to provider-specific model logic and makes
retries, timeouts, testing, and future provider changes harder.

### Why use a timeout?

To prevent an external LLM request from waiting indefinitely or
consuming server resources for too long.

### Why retry?

Some failures are temporary and may succeed on a later attempt.

### Why exponential backoff?

To avoid repeatedly hammering an overloaded or rate-limited provider.

### Should every error be retried?

No. Retry only errors likely to be transient.

### Why create `LLMError`?

To translate provider-specific exceptions into an application-level
abstraction.

### Why use `async`?

LLM calls are network I/O, so async execution helps a web server handle
other work while waiting.

### Why use environment variables?

To keep secrets and environment-specific configuration outside source
code.

### What is separation of concerns here?

FastAPI handles HTTP concerns while the harness handles LLM interaction
concerns.

------------------------------------------------------------------------

## 28. Revision Cheat Sheet

``` text
LLM HARNESS
===========

Purpose:
    Controlled interface between application and LLM provider.

Application:
    generate(prompt)

Harness internally handles:
    model configuration
    provider client
    model request
    timeout
    retries
    exponential backoff
    provider exceptions
    LLMError
    response extraction

Key architecture:

Client
  |
FastAPI
  |
LLM Harness
  |
Gemini / LLM Provider

TIMEOUT
    prevents waiting too long

RETRY
    handles temporary failures

BACKOFF
    increases delay between retries

LLMError
    hides provider-specific exceptions

ASYNC
    avoids blocking while waiting on network I/O

ENVIRONMENT VARIABLES
    keep API keys/config outside source code

SEPARATION OF CONCERNS
    FastAPI -> HTTP
    Harness -> LLM
```

------------------------------------------------------------------------

## 29. One Mental Model to Remember

When revising, remember this sentence:

> **The LLM harness is the reliability and abstraction layer between our
> application and the model provider.**

Then remember:

``` text
                 LLM HARNESS
                     |
       +-------------+-------------+
       |             |             |
   abstraction   reliability    isolation
       |             |             |
   generate()     timeout       provider SDK
                  retries       hidden from app
                  backoff
```

That captures the core reason we introduced the harness.
