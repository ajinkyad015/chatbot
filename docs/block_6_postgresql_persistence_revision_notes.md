# Block 6 --- PostgreSQL Persistence Revision Notes

## 1. What problem did we solve?

Before Block 6, conversation history was stored in a Python dictionary:

``` python
conversations: dict[str, list[dict[str, str]]] = {}
```

Architecture:

``` text
Client
  ↓
JWT Authentication
  ↓
FastAPI
  ↓
Python Dictionary (RAM)
  ↓
Build LLM Context
  ↓
LLM Harness
  ↓
LLM Provider
```

This allowed conversation memory while FastAPI was running, but the
dictionary lived inside the application's RAM.

When the server stopped:

``` text
FastAPI process stops
        ↓
process memory is released
        ↓
Python dictionary disappears
        ↓
conversation history is lost
```

Block 6 replaced this process-local memory with PostgreSQL.

New architecture:

``` text
Authenticated User
        ↓
POST /chat
        ↓
PostgreSQL → load conversation history
        ↓
Build LLM Context
        ↓
LLM Harness
        ↓
LLM Provider
        ↓
Save user + assistant messages
        ↓
PostgreSQL
        ↓
Response
```

The main idea is:

> PostgreSQL, not FastAPI's RAM, is now responsible for durable
> conversation history.

------------------------------------------------------------------------

# 2. Persistence

## RAM vs PostgreSQL

### RAM

RAM is temporary process memory.

``` text
FastAPI
   ↓
dictionary
   ↓
RAM
```

Advantages:

-   very fast
-   easy to use
-   useful for temporary application state

Problem:

-   tied to one application process
-   disappears when the process stops
-   cannot naturally be shared by multiple FastAPI instances

### PostgreSQL

PostgreSQL is durable storage.

``` text
FastAPI
   ↓
PostgreSQL
   ↓
stored conversation data
```

Stopping FastAPI does not delete the PostgreSQL rows.

``` text
FastAPI stops
     ↓
PostgreSQL remains
     ↓
FastAPI restarts
     ↓
queries PostgreSQL
     ↓
old history is available
```

### Definition to remember

**Persistence** means data survives beyond the lifetime of the
application process that created it.

------------------------------------------------------------------------

# 3. PostgreSQL, SQLAlchemy, and psycopg

The application stack is conceptually:

``` text
Python / FastAPI
      ↓
SQLAlchemy
      ↓
psycopg PostgreSQL driver
      ↓
PostgreSQL
```

## PostgreSQL

PostgreSQL is the actual database.

It stores:

-   conversations
-   messages
-   ownership information
-   timestamps

## SQLAlchemy

SQLAlchemy is **not** the database.

It is a Python library that helps our Python application interact with
the database.

Instead of writing raw SQL everywhere, we can work with Python models
and queries.

Example:

``` python
conversation = db.get(
    Conversation,
    conversation_id,
)
```

Conceptually this causes SQLAlchemy to retrieve the corresponding row
from PostgreSQL.

## psycopg

`psycopg` is the PostgreSQL database driver.

A useful mental model:

``` text
Application logic
      ↓
SQLAlchemy
      ↓
Database driver
      ↓
PostgreSQL
```

------------------------------------------------------------------------

# 4. Database configuration

The database connection string belongs in `.env`:

``` text
DATABASE_URL=postgresql+psycopg://...
```

Why?

Database credentials/configuration should not be hard-coded throughout
application source code.

Conceptually:

``` text
.env
 ↓
DATABASE_URL
 ↓
SQLAlchemy engine
 ↓
PostgreSQL
```

------------------------------------------------------------------------

# 5. The SQLAlchemy Engine

We created an engine:

``` python
engine = create_engine(DATABASE_URL)
```

The engine contains the configuration SQLAlchemy needs to communicate
with the database.

Mental model:

``` text
DATABASE_URL
     ↓
   Engine
     ↓
database connectivity
```

Do not think of the engine as a conversation or a database table.

It is database infrastructure used by SQLAlchemy.

------------------------------------------------------------------------

# 6. Database Sessions

We created:

``` python
SessionLocal = sessionmaker(...)
```

and a FastAPI dependency:

``` python
def get_db():
    db = SessionLocal()

    try:
        yield db
    finally:
        db.close()
```

An endpoint can then request a session:

``` python
db: Session = Depends(get_db)
```

## What is a Session?

For this block, think of a SQLAlchemy `Session` as the application's
working interface for database operations during a request.

We use it for operations such as:

``` python
db.get(...)
db.scalars(...)
db.add(...)
db.commit()
db.refresh(...)
```

Lifecycle:

``` text
HTTP request
    ↓
create Session
    ↓
query / modify database
    ↓
endpoint finishes
    ↓
close Session
```

The `finally` block ensures the session is closed even when request
handling fails.

------------------------------------------------------------------------

# 7. Our Database Schema

We deliberately kept the schema minimal.

We created only:

``` text
Conversation

id
user_id
created_at
```

and:

``` text
Message

id
conversation_id
role
content
created_at
```

We did **not** add a database-backed user system yet.

The authenticated JWT identity is used as the conversation owner.

------------------------------------------------------------------------

# 8. Conversation and Message Relationship

A conversation contains many messages.

``` text
Conversation
     │
     │ 1
     │
     │ many
     ↓
Messages
```

This is a **one-to-many relationship**.

Example:

``` text
Conversation 10
    │
    ├── Message 1
    ├── Message 2
    ├── Message 3
    └── Message 4
```

Database example:

``` text
conversations

id | user_id
---+--------
10 | sam
```

``` text
messages

id | conversation_id | role      | content
---+-----------------+-----------+-------------------
1  | 10              | user      | My name is Sam
2  | 10              | assistant | Nice to meet you
3  | 10              | user      | What is my name?
4  | 10              | assistant | Your name is Sam
```

Every message points to its conversation using:

``` text
conversation_id
```

------------------------------------------------------------------------

# 9. Why `conversation_id` exists

Without `conversation_id`, the database would contain messages without
knowing which chat they belong to.

Bad conceptual structure:

``` text
My name is Sam
Explain decorators
What is my name?
Explain PostgreSQL
```

There is no grouping.

Instead:

``` text
message
   ↓
conversation_id
   ↓
conversation
```

Now we can ask PostgreSQL:

``` sql
SELECT messages
WHERE conversation_id = 10;
```

and retrieve only the messages belonging to conversation 10.

------------------------------------------------------------------------

# 10. Foreign Keys

Our `Message` model uses conceptually:

``` python
ForeignKey("conversations.id")
```

This expresses:

``` text
messages.conversation_id
          ↓
references
          ↓
conversations.id
```

So `conversation_id` is not merely an arbitrary integer.

It represents a relationship to a conversation row.

------------------------------------------------------------------------

# 11. Why create conversations separately?

In Block 5, conversation history was effectively associated directly
with a username:

``` text
username
   ↓
one history list
```

That design does not naturally support multiple chats for one user.

Now:

``` text
User
 │
 ├── Conversation 1
 ├── Conversation 2
 └── Conversation 3
```

We added:

``` text
POST /conversations
```

Flow:

``` text
Authenticated user
       ↓
POST /conversations
       ↓
create Conversation row
       ↓
PostgreSQL
       ↓
return conversation_id
```

Example response:

``` json
{
  "conversation_id": 10
}
```

Future messages can specify which conversation they belong to.

------------------------------------------------------------------------

# 12. New `/chat` Request

Previously:

``` json
{
  "message": "Hello"
}
```

Now:

``` json
{
  "conversation_id": 10,
  "message": "Hello"
}
```

This means:

> Send this message inside conversation 10.

The API can then load the correct history from PostgreSQL.

------------------------------------------------------------------------

# 13. Why `Conversation.user_id` exists

The conversation stores:

``` text
user_id
```

For this block, it comes from the authenticated JWT identity.

Example:

``` text
Conversation

id      = 10
user_id = sam
```

This establishes **ownership**.

It allows the application to answer:

> Who owns conversation 10?

That becomes essential for authorization.

------------------------------------------------------------------------

# 14. Authentication vs Authorization

These are different concepts.

## Authentication

Question:

> Who are you?

Our JWT authentication answers this.

``` text
JWT
 ↓
verify token
 ↓
extract identity
 ↓
sam
```

Authentication establishes identity.

## Authorization

Question:

> Are you allowed to access this resource?

Example:

``` text
current user = sam

conversation 42
owner = alice
```

Sam may have a perfectly valid JWT.

Therefore:

``` text
Authentication: SUCCESS
```

But Sam does not own conversation 42.

Therefore:

``` text
Authorization: FAILED
```

The API returns:

``` text
403 Forbidden
```

### Remember

``` text
Authentication
=
Who are you?

Authorization
=
What are you allowed to access?
```

Being authenticated does **not** mean a user may access every resource.

------------------------------------------------------------------------

# 15. Ownership Check

Before loading conversation history into the LLM context, we check
ownership.

Conceptually:

``` python
if conversation.user_id != username:
    raise HTTPException(status_code=403)
```

Flow:

``` text
conversation_id
      ↓
load Conversation
      ↓
conversation.user_id
      ↓
compare with JWT identity
      ↓
allowed?
```

Example:

``` text
JWT user                = sam
conversation.user_id    = sam

sam == sam

ACCESS ALLOWED
```

But:

``` text
JWT user                = bob
conversation.user_id    = sam

bob != sam

ACCESS DENIED
```

This check should happen before exposing or using that conversation's
private messages.

------------------------------------------------------------------------

# 16. Loading Conversation History

Previously we did:

``` python
history = conversations.setdefault(username, [])
```

That read history from Python RAM.

Now we query PostgreSQL.

Conceptually:

``` sql
SELECT messages
WHERE conversation_id = ?
ORDER BY ...
LIMIT ...;
```

The important change is:

``` text
OLD

Python dictionary
      ↓
history
```

becomes:

``` text
NEW

PostgreSQL query
      ↓
history
```

The database is now responsible for remembering previous messages.

------------------------------------------------------------------------

# 17. PostgreSQL Memory Is Not LLM Memory

This distinction is extremely important.

The LLM does not directly read PostgreSQL.

Gemini does not automatically know:

``` text
conversation_id = 10
```

Our application performs the memory mechanism.

``` text
PostgreSQL
     ↓
query previous messages
     ↓
FastAPI
     ↓
construct context
     ↓
LLM Harness
     ↓
Gemini
```

Suppose PostgreSQL contains:

``` text
user: My name is Sam.
assistant: Nice to meet you, Sam.
```

The next user asks:

``` text
What is my name?
```

FastAPI constructs context approximately like:

``` text
SYSTEM:
You are a concise, helpful assistant.

USER:
My name is Sam.

ASSISTANT:
Nice to meet you, Sam.

USER:
What is my name?
```

The LLM can answer because **we sent the old messages again**.

### Key idea

> PostgreSQL stores the durable history. The application retrieves
> selected history and turns it into LLM context.

The LLM itself is not our durable memory store.

------------------------------------------------------------------------

# 18. Database History vs LLM Context

These are two separate things.

## Database history

PostgreSQL may eventually contain:

``` text
500 messages
```

That is durable stored history.

## LLM context

We might send only:

``` text
20 recent messages
```

to the LLM.

Architecture:

``` text
PostgreSQL
500 stored messages
       ↓
database query
       ↓
recent 20 messages
       ↓
LLM context
```

So:

``` text
stored history ≠ current LLM context
```

------------------------------------------------------------------------

# 19. Why We Limit Context

We kept:

``` python
MAX_CONTEXT_MESSAGES = 20
```

We should not blindly load unlimited conversation history.

Imagine a conversation contains 20,000 messages.

Sending all of them on every request would mean:

``` text
more database work
more application memory
more data processing
more LLM input tokens
higher latency
larger requests
context-window pressure
potentially higher cost
```

Instead:

``` text
PostgreSQL
stores durable history
        ↓
query
        ↓
only recent messages needed for context
```

For this block, a simple fixed message limit is enough.

We deliberately did **not** add summarization.

------------------------------------------------------------------------

# 20. Why Query Newest Messages First?

Suppose the database has messages:

``` text
1
2
3
...
999
1000
```

and we want the most recent 20.

If we query ascending and immediately limit:

``` text
1
2
...
20
```

we get the oldest messages.

Instead, conceptually:

``` text
ORDER BY id DESC
LIMIT 20
```

returns:

``` text
1000
999
998
...
981
```

This selects the correct recent messages.

But the LLM should see conversation history chronologically:

``` text
981
982
...
999
1000
```

So we reverse the result in Python before constructing context.

Mental model:

``` text
Database query:
newest → oldest

reverse

LLM context:
oldest → newest
```

------------------------------------------------------------------------

# 21. Building LLM Context

Database rows are not automatically LLM messages.

Our application converts them into the format expected by the existing
harness:

``` python
{
    "role": message.role,
    "content": message.content,
}
```

Then the current user message is appended.

Conceptually:

``` text
database rows
      ↓
convert
      ↓
[
    previous user,
    previous assistant,
    previous user,
    previous assistant,
    current user
]
      ↓
generate(messages)
```

The existing LLM harness remains responsible for provider interaction.

This is a useful separation:

``` text
Database layer
=
store/retrieve conversation data

FastAPI endpoint
=
authorization + orchestration + context construction

LLM Harness
=
reliable interaction with LLM provider
```

------------------------------------------------------------------------

# 22. Saving Messages

After the LLM successfully responds, we persist both sides of the
exchange.

``` text
User Message
+
Assistant Message
```

Example:

``` text
role = user
content = My name is Sam.
```

and:

``` text
role = assistant
content = Nice to meet you, Sam.
```

Why both?

Because future context should reproduce the conversation:

``` text
user
assistant
user
assistant
user
assistant
```

not merely a collection of user prompts.

------------------------------------------------------------------------

# 23. Why Save After Successful LLM Generation?

Our simple flow is:

``` text
receive message
      ↓
load previous history
      ↓
call LLM
      ↓
LLM succeeds
      ↓
save user message
      ↓
save assistant message
      ↓
commit
```

For this learning block, we treat:

``` text
user message + assistant response
```

as one successful conversation exchange.

If the provider fails before producing an answer, we do not persist an
incomplete exchange with this design.

More sophisticated systems can make different choices, but they are
outside this block.

------------------------------------------------------------------------

# 24. `db.add()` and `db.commit()`

Simplified mental model:

``` python
db.add(message)
```

means:

> Track this new database object as something that should be inserted.

Then:

``` python
db.commit()
```

means:

> Commit the transaction containing these database changes.

Think:

``` text
db.add()
   ↓
prepare/stage ORM change

db.commit()
   ↓
commit transaction
   ↓
changes persist
```

Database transactions have deeper behavior, but this understanding is
sufficient for Block 6.

------------------------------------------------------------------------

# 25. Why `db.refresh()` Was Used When Creating a Conversation

When creating a conversation:

``` python
conversation = Conversation(user_id=username)

db.add(conversation)
db.commit()
db.refresh(conversation)
```

PostgreSQL generates values such as:

``` text
id
created_at
```

Refreshing allows the ORM object to reflect database-generated state.

Then we can return:

``` python
conversation.id
```

as:

``` json
{
  "conversation_id": 10
}
```

------------------------------------------------------------------------

# 26. Source of Truth

This is one of the most important architectural concepts.

## Before

``` text
Python dictionary
=
source of truth for conversation history
```

## Now

``` text
PostgreSQL
=
source of truth for durable conversation history
```

If FastAPI needs old conversation messages, it should query PostgreSQL.

It should not depend on some global dictionary surviving.

### Definition

The **source of truth** is the authoritative place from which the
application gets the durable state.

For conversation history, that is now PostgreSQL.

------------------------------------------------------------------------

# 27. Persistence Restart Test

This is the most important test in Block 6.

### Step 1

Create conversation:

``` text
POST /conversations
```

Receive:

``` json
{
  "conversation_id": 10
}
```

### Step 2

Send:

``` text
My name is Sam.
```

### Step 3

Send:

``` text
What is my name?
```

Expected:

``` text
Sam
```

### Step 4

Stop FastAPI completely.

``` text
Ctrl+C
```

The FastAPI process and its RAM disappear.

### Step 5

Restart FastAPI.

### Step 6

Using the same conversation ID, ask:

``` text
What is my name?
```

It should still know.

Why?

``` text
old FastAPI process
       X

PostgreSQL
       ✓
conversation still stored
messages still stored

new FastAPI process
       ↓
query PostgreSQL
       ↓
reconstruct context
       ↓
LLM sees previous messages
```

This proves conversation memory is persistent rather than process-local.

------------------------------------------------------------------------

# 28. Authorization Test

Create a conversation while authenticated as User A.

Example:

``` text
conversation 10
owner = alice
```

Then authenticate as User B:

``` text
bob
```

Bob sends:

``` json
{
  "conversation_id": 10,
  "message": "What did we discuss?"
}
```

Authentication succeeds because Bob's JWT is valid.

But authorization fails:

``` text
bob != alice
```

Expected:

``` text
403 Forbidden
```

This demonstrates:

> Successful authentication does not automatically imply successful
> authorization.

------------------------------------------------------------------------

# 29. Why PostgreSQL Helps Multiple FastAPI Instances

With dictionaries:

``` text
             Load Balancer
              /        \
             ↓          ↓
        FastAPI A    FastAPI B
            ↓            ↓
      dictionary A  dictionary B
```

These dictionaries are separate.

Suppose:

``` text
Request 1
"My name is Sam"
      ↓
FastAPI A
      ↓
dictionary A
```

Then:

``` text
Request 2
"What is my name?"
      ↓
FastAPI B
      ↓
dictionary B
```

FastAPI B may know nothing about request 1.

This makes process-local memory unsuitable as the durable source of
truth for a multi-instance application.

With PostgreSQL:

``` text
             Load Balancer
              /        \
             ↓          ↓
        FastAPI A    FastAPI B
              \       /
               \     /
                ↓   ↓
             PostgreSQL
```

FastAPI A can insert a message.

FastAPI B can later query the same message.

Both instances share the same durable data source.

------------------------------------------------------------------------

# 30. Why We Did Not Add a Database `User` Table

Authentication already gives us an identity from the JWT.

Conceptually:

``` text
JWT
 ↓
sub / username
 ↓
Conversation.user_id
```

That is enough to learn:

-   ownership
-   authorization
-   persistent conversations

Adding full database-backed users would introduce unrelated concerns
such as:

-   persistent accounts
-   user lifecycle
-   password storage in PostgreSQL
-   account relationships
-   roles and permissions

Those are intentionally outside Block 6.

------------------------------------------------------------------------

# 31. Automatic Table Creation

For this learning block we used:

``` python
Base.metadata.create_all(bind=engine)
```

This is convenient because SQLAlchemy can create missing tables from our
models.

For learning:

``` text
create_all()
✓ simple
✓ minimal setup
✓ enough for Block 6
```

However, production systems normally use proper schema migrations.

------------------------------------------------------------------------

# 32. Why Production Systems Use Migrations

Database schemas evolve.

Today:

``` text
Conversation

id
user_id
created_at
```

Later we might need:

``` text
Conversation

id
user_id
title
created_at
archived_at
```

A production database may already contain millions of rows.

Schema changes need to happen in a controlled, repeatable, versioned
way.

Conceptually:

``` text
schema version 1
       ↓
migration
       ↓
schema version 2
```

Tools such as Alembic are commonly used with SQLAlchemy for this.

We deliberately did **not** introduce migrations in Block 6.

------------------------------------------------------------------------

# 33. Complete Request Flow

The final `/chat` flow is:

``` text
Client
  ↓
POST /chat
  ↓
JWT Authentication
  ↓
current authenticated user
  ↓
load Conversation from PostgreSQL
  ↓
verify conversation ownership
  ↓
load recent Messages
  ↓
convert rows into LLM messages
  ↓
append current user message
  ↓
LLM Harness
  ↓
LLM Provider
  ↓
assistant response
  ↓
save user message
  ↓
save assistant message
  ↓
commit to PostgreSQL
  ↓
return response
```

------------------------------------------------------------------------

# 34. Responsibility of Each Component

## JWT Authentication

Responsible for:

``` text
Who is making this request?
```

## Conversation ownership check

Responsible for:

``` text
May this authenticated user access this conversation?
```

## PostgreSQL

Responsible for:

``` text
Durably storing conversation history.
```

## SQLAlchemy

Responsible for:

``` text
Helping Python communicate with and manipulate database data.
```

## FastAPI endpoint

Responsible for orchestration:

``` text
authenticate
↓
authorize
↓
query
↓
build context
↓
call harness
↓
persist result
↓
respond
```

## LLM Harness

Responsible for provider interaction such as:

``` text
model selection
timeouts
retries
error normalization
usage/latency information
provider request
```

## LLM Provider

Responsible for:

``` text
generating the assistant response from supplied context
```

------------------------------------------------------------------------

# 35. Most Important Mental Model

The LLM does not magically remember the user.

The actual mechanism is:

``` text
Previous request
      ↓
messages saved
      ↓
PostgreSQL
      ↓
      ↓ later request
      ↓
messages queried
      ↓
context reconstructed
      ↓
LLM receives old messages again
      ↓
LLM appears to remember
```

So conversation memory is primarily an **application + storage +
context-construction mechanism**.

------------------------------------------------------------------------

# 36. Block 5 vs Block 6

## Block 5

``` text
Conversation memory
      ↓
Python dictionary
      ↓
RAM
```

Properties:

``` text
temporary
process-local
lost after restart
not naturally shared
```

## Block 6

``` text
Conversation memory
      ↓
PostgreSQL
```

Properties:

``` text
durable
shared
survives FastAPI restart
queryable
supports ownership
supports multiple conversations
works across multiple application instances
```

The LLM harness itself did not need to become a database system.

It still receives:

``` python
list[dict[str, str]]
```

This is good separation of responsibilities.

------------------------------------------------------------------------

# 37. Core Concepts to Memorize

## Persistence

``` text
RAM
=
temporary process-local state

PostgreSQL
=
durable shared storage
```

## Source of Truth

``` text
PostgreSQL
=
authoritative durable conversation history
```

## Relationship

``` text
Conversation
     ↓
1-to-many
     ↓
Messages
```

## Ownership

``` text
Conversation.user_id
```

tells us which authenticated identity owns the conversation.

## Authentication

``` text
Who are you?
```

## Authorization

``` text
Can you access this resource?
```

## Querying

Retrieve only the history needed for the current operation.

``` text
PostgreSQL
      ↓
recent messages
      ↓
LLM context
```

Do not blindly send unlimited history.

## Multiple Instances

``` text
FastAPI A ──┐
            ├── PostgreSQL
FastAPI B ──┘
```

Both can see the same durable conversation data.

## Migrations

`create_all()` is acceptable for this learning block.

Production databases normally require controlled schema migrations.

------------------------------------------------------------------------

# 38. Interview / Revision Questions

Try answering these without looking above.

### Q1. Why did our old conversation memory disappear?

Because it was stored in a Python dictionary in the FastAPI process's
RAM.

### Q2. What does persistence mean?

Data survives beyond the lifetime of the application process that
created it.

### Q3. What is the source of truth now?

PostgreSQL.

### Q4. Is SQLAlchemy our database?

No. PostgreSQL is the database. SQLAlchemy is a Python library used to
interact with it.

### Q5. What relationship exists between Conversation and Message?

One conversation has many messages: one-to-many.

### Q6. Why does Message contain `conversation_id`?

To identify which conversation the message belongs to.

### Q7. Why does Conversation contain `user_id`?

To establish ownership and perform authorization.

### Q8. Authentication vs authorization?

Authentication determines who the user is.

Authorization determines whether that user may access a particular
resource.

### Q9. Does Gemini directly remember our PostgreSQL data?

No. FastAPI queries PostgreSQL and sends selected previous messages back
to Gemini as context.

### Q10. Why don't we send every stored message?

Conversation history can grow indefinitely, while LLM context is finite
and consumes tokens, latency, and resources.

### Q11. Why does memory survive a FastAPI restart?

The conversation is stored in PostgreSQL, which exists independently
from the FastAPI process.

### Q12. Why is PostgreSQL better for multiple FastAPI instances?

Every application instance can query the same shared database instead of
maintaining separate local dictionaries.

### Q13. What does `db.commit()` do conceptually?

It commits the current database transaction so the changes are
persisted.

### Q14. Why use migrations in production?

To evolve database schemas in a controlled, versioned, repeatable way
without casually recreating or manually changing production tables.

------------------------------------------------------------------------

# 39. Final Architecture

``` text
                    ┌───────────────┐
                    │    Client     │
                    └───────┬───────┘
                            │
                            ↓
                    ┌───────────────┐
                    │    FastAPI    │
                    └───────┬───────┘
                            │
                    JWT Authentication
                            │
                            ↓
                     authenticated user
                            │
                            ↓
                    load Conversation
                            │
                            ↓
                     authorization
                  conversation.user_id
                            │
                            ↓
                    query recent Messages
                            │
                            ↓
                       PostgreSQL
                            │
                            ↓
                     construct context
                            │
                            ↓
                      LLM Harness
                            │
                            ↓
                      LLM Provider
                            │
                            ↓
                    assistant response
                            │
                            ↓
              save user + assistant messages
                            │
                            ↓
                       PostgreSQL
                            │
                            ↓
                         Response
```

------------------------------------------------------------------------

# 40. Block 6 Definition of Done

You understand Block 6 when you can explain and demonstrate:

-   create a conversation
-   send messages to that conversation
-   retrieve previous history from PostgreSQL
-   build LLM context from stored messages
-   persist user and assistant messages
-   stop FastAPI
-   restart FastAPI
-   continue the same conversation successfully
-   reject another authenticated user's attempt to access the
    conversation
-   explain RAM vs durable storage
-   explain PostgreSQL as the source of truth
-   explain Conversation → Messages as one-to-many
-   explain why `conversation_id` exists
-   explain why `user_id` exists
-   explain authentication vs authorization
-   explain why LLM context is limited
-   explain why multiple FastAPI instances can share PostgreSQL
-   explain why production systems use migrations

## One-sentence summary

> Block 6 moved conversation memory from temporary FastAPI RAM into
> durable PostgreSQL storage, while adding conversation ownership,
> authorization, database-backed history retrieval, and persistent LLM
> context reconstruction.
