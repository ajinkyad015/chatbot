# Block 5 — Conversation Context

## Goal

Make an authenticated chat application appear to remember earlier messages.

Final flow:

```text
Authenticated User
        ↓
POST /chat
        ↓
Identify user from JWT
        ↓
Load that user's conversation history
        ↓
Add current user message to model context
        ↓
Send context to LLM Harness
        ↓
LLM Provider
        ↓
Receive assistant response
        ↓
Store user + assistant messages
        ↓
Return response
```

---

# 1. The Most Important Concept

## The LLM did not remember the conversation

LLM API requests are independent.

Suppose request 1 is:

```text
My name is Sam.
```

Later request 2 is:

```text
What is my name?
```

If request 2 contains only `"What is my name?"`, the model does not automatically have access to request 1.

The application creates conversational memory by storing previous messages and sending relevant messages again.

Mental model:

```text
LLM memory ❌

Application stores history
        +
Application resends history
        =
Apparent conversational memory ✅
```

The key sentence to remember:

> The LLM does not automatically remember previous API requests. The application stores conversation state and reconstructs the context sent to the model.

---

# 2. Conversation State

We introduced an in-memory dictionary:

```python
conversations: dict[str, list[dict[str, str]]] = {}
```

Conceptually:

```python
conversations = {
    "demo": [
        {"role": "user", "content": "My name is Sam."},
        {"role": "assistant", "content": "Nice to meet you, Sam."},
    ]
}
```

The structure is:

```text
user identity
    ↓
conversation history
```

Before this block, `/chat` was effectively:

```text
request → LLM → response
```

Now the response depends on existing server state:

```text
request
   ↓
load previous state
   ↓
LLM
   ↓
update state
   ↓
response
```

This means our application has become stateful with respect to conversations.

---

# 3. Why Conversation History Is Associated With the JWT User

Our endpoint already has:

```python
current_user: dict = Depends(get_current_user)
```

Authentication decodes the JWT and obtains the username from the `sub` claim.

Then `/chat` uses:

```python
username = current_user["username"]
```

and:

```python
history = conversations.setdefault(username, [])
```

`setdefault()` means:

- if the username already exists, return its history;
- otherwise create an empty list for that user and return it.

Example:

```python
conversations = {
    "alice": [...],
    "bob": [...]
}
```

Alice loads:

```python
conversations["alice"]
```

Bob loads:

```python
conversations["bob"]
```

This is **user isolation**.

Never use one global message list for all users:

```python
conversation = []
```

That could mix Alice's messages with Bob's messages.

The dictionary itself can be global for this learning implementation because each user's history is stored under a separate authenticated identity.

---

# 4. How `/chat` Builds Context

The current message is represented as:

```python
current_message = {
    "role": "user",
    "content": body.message,
}
```

Then we construct the messages sent to the model:

```python
messages = history[-MAX_CONTEXT_MESSAGES:] + [
    current_message
]
```

Conceptually:

```text
previous relevant messages
        +
current user message
        ↓
LLM
```

Suppose stored history is:

```python
[
    {"role": "user", "content": "My name is Sam."},
    {"role": "assistant", "content": "Nice to meet you, Sam."},
]
```

The next request is:

```text
What is my name?
```

The model receives context equivalent to:

```text
USER:
My name is Sam.

ASSISTANT:
Nice to meet you, Sam.

USER:
What is my name?
```

Now the model can answer:

```text
Your name is Sam.
```

Again, this works because the application resent the previous information.

---

# 5. Why Save Both User and Assistant Messages?

After a successful LLM call:

```python
history.append(current_message)

history.append({
    "role": "assistant",
    "content": result.text,
})
```

We store both sides because later conversation may depend on either side.

Example:

```text
User: Give me three project names.

Assistant:
1. Atlas
2. Nova
3. Orion

User: I like the second one.
```

To understand `"the second one"`, the model needs its previous response too.

Therefore conversation history normally contains both:

```text
user messages
+
assistant/model messages
```

---

# 6. Why Save Messages After the LLM Call?

Our flow is:

```python
result = await generate(messages)

history.append(current_message)
history.append(assistant_message)
```

We store the exchange only after the model call succeeds.

If the provider fails, we avoid recording an assistant response that never existed.

For this minimal implementation, this keeps conversation state simple and consistent.

---

# 7. LLM Harness Changed From String to Messages

Originally:

```python
async def generate(user_input: str) -> LLMResult:
```

The harness could only receive one string.

Now:

```python
async def generate(
    messages: list[dict[str, str]],
) -> LLMResult:
```

This allows the application to pass an entire conversation context.

Example:

```python
messages = [
    {"role": "user", "content": "My name is Sam."},
    {"role": "assistant", "content": "Nice to meet you."},
    {"role": "user", "content": "What is my name?"},
]
```

---

# 8. Application Message Format vs Gemini Format

Our application uses a simple provider-independent representation:

```python
{
    "role": "user",
    "content": "Hello"
}
```

and:

```python
{
    "role": "assistant",
    "content": "Hi!"
}
```

Gemini expects its own SDK objects.

So the LLM harness converts our messages:

```python
contents=[
    types.Content(
        role="model" if message["role"] == "assistant" else "user",
        parts=[
            types.Part.from_text(
                text=message["content"]
            )
        ],
    )
    for message in messages
]
```

Role mapping:

```text
Our application     Gemini
---------------------------
user             →  user
assistant        →  model
```

The harness is a good place for this conversion because provider-specific details remain outside the FastAPI endpoint.

Mental model:

```text
FastAPI/application format
        ↓
LLM Harness
        ↓
provider-specific conversion
        ↓
Gemini API
```

---

# 9. Understanding the List Comprehension

This:

```python
contents=[
    convert(message)
    for message in messages
]
```

is conceptually equivalent to:

```python
contents = []

for message in messages:
    converted = convert(message)
    contents.append(converted)
```

So every stored application message is converted into the format expected by Gemini.

---

# 10. System Instruction vs Conversation Messages

Our Gemini call still has:

```python
system_instruction="You are a concise, helpful assistant."
```

Conceptually the model receives:

```text
system instruction
+
conversation history
+
current user message
```

The system instruction controls general model behavior.

Conversation messages provide the current conversational context.

---

# 11. Context Growth

We added simple observability:

```python
print(f"Messages in context: {len(messages)}")
print(f"Input tokens: {result.input_tokens}")
```

As a conversation grows, you may observe:

```text
Messages in context: 1
Input tokens: 20

Messages in context: 3
Input tokens: 55

Messages in context: 5
Input tokens: 100
```

Exact numbers vary.

The important relationship is:

```text
more history
    ↓
more input text
    ↓
more input tokens
    ↓
more cost
    ↓
potentially more latency
```

Conversation memory has a recurring cost because old messages are sent again on future requests.

---

# 12. Context Window

Models cannot accept unlimited input.

They have a finite **context window**.

The context window is the amount of information/tokens the model can process for a request.

Conceptually:

```text
system instructions
+
conversation history
+
current user input
+
other supplied context
```

must fit within the model's supported context constraints.

Therefore:

> Conversation history cannot be sent forever without some context-management strategy.

We are intentionally not implementing summarization, RAG, or advanced context management in this block.

---

# 13. Simple Context Limit

We added:

```python
MAX_CONTEXT_MESSAGES = 20
```

and:

```python
messages = history[-MAX_CONTEXT_MESSAGES:] + [
    current_message
]
```

If 100 messages are stored, we do not send all 100.

We send approximately:

```text
system instruction
+
latest 20 stored messages
+
current user message
```

This is a simple learning implementation.

It is not necessarily the best production strategy.

---

# 14. Stored History vs Model Context

This distinction is important.

We continue storing messages with:

```python
history.append(...)
```

But we limit what gets sent:

```python
history[-MAX_CONTEXT_MESSAGES:]
```

Therefore:

```text
Stored conversation history
        ≠
Context sent to model
```

Example:

```text
Stored messages: 100

Messages selected for current model request:
latest 20 + current message
```

The model only knows what is included in the current request.

If `"My name is Sam"` was far enough back that it was excluded, the model may no longer know the name.

---

# 15. Context Tradeoff

There is an unavoidable tradeoff.

## More history

```text
more history
→ better conversational continuity
→ more information available
→ more input tokens
→ higher cost
→ potentially higher latency
```

## Less history

```text
less history
→ fewer tokens
→ lower cost
→ smaller requests
→ but older information can disappear
```

This is one of the central design problems in conversational AI systems.

Our current solution is deliberately simple:

```text
keep the latest N messages
```

---

# 16. Conversation Reset

We added:

```python
@app.post("/conversation/reset")
def reset_conversation(
    current_user: dict = Depends(get_current_user),
):
    username = current_user["username"]

    conversations.pop(username, None)

    return {"status": "conversation reset"}
```

`pop(username, None)` removes only that authenticated user's history.

Example:

```python
conversations = {
    "alice": [...],
    "bob": [...]
}
```

If Alice resets:

```text
alice history → deleted
bob history   → unchanged
```

This demonstrates the conversation lifecycle:

```text
conversation starts
        ↓
messages accumulate
        ↓
context reconstructed per request
        ↓
conversation reset
        ↓
history removed
```

---

# 17. Test to Remember

Request 1:

```text
My name is Sam.
```

Application stores:

```text
USER: My name is Sam.
ASSISTANT: ...
```

Request 2:

```text
What is my name?
```

Application constructs:

```text
USER: My name is Sam.
ASSISTANT: ...
USER: What is my name?
```

Model responds:

```text
Sam
```

This proves **application-managed conversational memory**, not persistent memory inside the model.

Then call:

```text
POST /conversation/reset
```

and ask:

```text
What is my name?
```

The old history is gone, so the application can no longer resend that information.

---

# 18. Architecture Before and After

Before conversation context:

```text
Client
  ↓
JWT Authentication
  ↓
FastAPI
  ↓
LLM Harness
  ↓
LLM Provider
```

After this block:

```text
Client
  ↓
JWT Authentication
  ↓
FastAPI
  ↓
Authenticated username
  ↓
In-memory conversation state
  ↓
Construct context
  ↓
LLM Harness
  ↓
LLM Provider
  ↓
Store response in conversation state
```

The new concept is:

```text
user_id → conversation state
```

---

# 19. Limitations of the In-Memory Dictionary

These limitations are intentional.

## Limitation 1 — Restart loses conversations

The dictionary exists only inside the running Python process.

```python
conversations = {}
```

If FastAPI stops or restarts:

```text
process memory disappears
        ↓
conversation history disappears
```

The same limitation currently applies to our in-memory user store.

---

## Limitation 2 — Multiple Server Instances

Suppose production eventually has:

```text
             ┌── Server A
Client ──────┤
             └── Server B
```

Each process has its own dictionary.

```text
Server A:
conversations = {...}

Server B:
conversations = {...}
```

They are not automatically shared.

Request 1 might reach Server A:

```text
"My name is Sam"
```

Server A remembers it.

Request 2 might reach Server B:

```text
"What is my name?"
```

Server B may have no corresponding history.

So apparent conversation memory can disappear when requests reach different instances.

This is one reason production systems eventually need shared/persistent state.

We are not solving that yet.

---

## Limitation 3 — Memory Usage Grows

We limit what is sent to the model:

```python
history[-20:]
```

but we currently keep appending to the stored history:

```python
history.append(...)
```

Therefore:

```text
more users
+
more conversations
+
more messages
=
more application RAM
```

The context limit protects model input size, but it does not automatically limit server-side memory usage.

---

## Limitation 4 — Simplistic Conversation Model

Our structure is:

```text
username → one conversation history
```

That means one user effectively has one chat.

We currently do not have:

```text
conversation IDs
multiple chats per user
conversation titles
persistent history
shared storage
advanced context selection
summarization
RAG
```

Those are deliberately outside Block 5.

---

# 20. Important Async Fix

Inside an `async def`, avoid blocking the event loop with:

```python
time.sleep(wait_seconds)
```

Use:

```python
await asyncio.sleep(wait_seconds)
```

`time.sleep()` blocks the worker/event loop.

`await asyncio.sleep()` allows other async work to continue while waiting.

This fix is separate from conversation memory but is important for the existing LLM harness.

---

# 21. Core Code to Remember

## Conversation store

```python
conversations: dict[str, list[dict[str, str]]] = {}

MAX_CONTEXT_MESSAGES = 20
```

## Identify the authenticated user's history

```python
username = current_user["username"]

history = conversations.setdefault(username, [])
```

## Build current message

```python
current_message = {
    "role": "user",
    "content": body.message,
}
```

## Construct model context

```python
messages = history[-MAX_CONTEXT_MESSAGES:] + [
    current_message
]
```

## Call the LLM

```python
result = await generate(messages)
```

## Save successful exchange

```python
history.append(current_message)

history.append({
    "role": "assistant",
    "content": result.text,
})
```

## Reset

```python
conversations.pop(username, None)
```

---

# 22. Revision Questions

You should be able to answer these without looking at the code:

1. Does the LLM automatically remember previous API calls?
2. Where does conversation memory currently live?
3. Why do we resend previous messages?
4. Why do we store assistant responses as well as user messages?
5. How do we prevent Alice from receiving Bob's history?
6. Where does the user's identity come from?
7. What is a context window?
8. Why do input tokens increase as conversations grow?
9. Why can more history increase cost and latency?
10. Why do we send only the latest N messages?
11. What is the difference between stored history and model context?
12. What happens after `/conversation/reset`?
13. What happens to conversations after a FastAPI restart?
14. Why does this dictionary approach cause problems with multiple API instances?
15. Why can server RAM usage continue growing even if model context is limited?

---

# 23. Final Mental Model

Remember this diagram:

```text
JWT
 ↓
Who is the user?
 ↓
username
 ↓
conversations[username]
 ↓
previous messages
 ↓
take relevant/latest history
 ↓
add current user message
 ↓
convert to provider format
 ↓
LLM request
 ↓
LLM response
 ↓
store user message + assistant response
```

And remember this distinction:

```text
LLM = stateless between independent API requests

Application = owns conversation state

Context = selected information sent to the model for this request
```

## One-line summary

> Conversation memory in an LLM application is created by storing conversation state outside the model and reconstructing relevant context on each new model request.
