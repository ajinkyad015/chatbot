# Block 4 --- Authentication for a FastAPI LLM Service

## Purpose

This document captures the authentication system we built, why each
piece exists, how the request lifecycle works, and the concepts to
revise later.

The application started as:

``` text
Client
  ↓
FastAPI
  ↓
LLM Harness
  ↓
LLM Provider
```

The goal was to protect the expensive `/chat` operation:

``` text
Client
  ↓
Register / Login
  ↓
JWT access token
  ↓
POST /chat + Authorization: Bearer <JWT>
  ↓
FastAPI authentication
  ↓
LLM Harness
  ↓
LLM Provider
```

The central architectural rule is:

> Authenticate before performing the protected or expensive operation.

------------------------------------------------------------------------

# 1. Final Project Responsibilities

We kept the project small:

``` text
app.py
authentication.py
validation.py
llm_harness.py
.env
```

Responsibilities:

``` text
validation.py
    → API request/response schemas and input constraints

authentication.py
    → user storage
    → password hashing/verification
    → JWT creation/verification
    → current-user authentication dependency

app.py
    → HTTP routes
    → orchestration
    → connects authentication to /chat

llm_harness.py
    → LLM provider communication
    → timeout/retry/backoff
    → provider error normalization
    → token usage and latency

.env
    → secrets/configuration
```

Authentication does **not** belong inside the LLM harness. The harness
should not care whether the caller is Alice, Bob, an admin, or a mobile
client.

------------------------------------------------------------------------

# 2. Dependencies

We used FastAPI plus:

``` bash
pip install "pwdlib[argon2]" PyJWT python-dotenv
```

Important libraries:

-   `pwdlib` / Argon2 --- password hashing and verification.
-   `PyJWT` --- JWT creation and verification.
-   `python-dotenv` --- loads local environment configuration.

Example `.env`:

``` text
GEMINI_API_KEY=...
JWT_SECRET=<long-random-secret>
JWT_ALGORITHM=HS256
JWT_EXPIRE_MINUTES=30
```

Generate a development signing secret with:

``` bash
python -c "import secrets; print(secrets.token_hex(32))"
```

Do not commit `.env` or expose `JWT_SECRET`.

------------------------------------------------------------------------

# 3. Validation Models

`validation.py`:

``` python
from pydantic import BaseModel, Field


class RegisterRequest(BaseModel):
    username: str = Field(min_length=3, max_length=50)
    password: str = Field(min_length=8, max_length=128)


class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=10_000)


class Usage(BaseModel):
    input_tokens: int
    output_tokens: int


class ChatResponse(BaseModel):
    response: str
    model: str
    usage: Usage
    latency_ms: int
```

## What validation does

Validation answers:

> Is this incoming data structurally acceptable?

It does not answer:

> Who is this user?

For example:

``` text
POST /register
      ↓
Pydantic validation
      ↓
username/password have acceptable shape?
      ↓
registration logic
```

Authentication and validation are different concerns.

------------------------------------------------------------------------

# 4. Authentication Module

A compact version of `authentication.py`:

``` python
import os
from datetime import datetime, timedelta, timezone

import jwt
from dotenv import load_dotenv
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pwdlib import PasswordHash


load_dotenv()

JWT_SECRET = os.environ["JWT_SECRET"]
JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
JWT_EXPIRE_MINUTES = int(os.getenv("JWT_EXPIRE_MINUTES", "30"))

password_hash = PasswordHash.recommended()

users: dict[str, dict[str, str]] = {}

bearer_scheme = HTTPBearer()


def hash_password(password: str) -> str:
    return password_hash.hash(password)


def verify_password(password: str, hashed_password: str) -> bool:
    return password_hash.verify(password, hashed_password)


def create_user(username: str, password: str) -> dict[str, str]:
    if username in users:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Username already exists",
        )

    user = {
        "username": username,
        "password_hash": hash_password(password),
    }

    users[username] = user
    return user


def authenticate_user(username: str, password: str) -> dict[str, str] | None:
    user = users.get(username)

    if user is None:
        return None

    if not verify_password(password, user["password_hash"]):
        return None

    return user


def create_access_token(username: str) -> str:
    now = datetime.now(timezone.utc)

    payload = {
        "sub": username,
        "iat": now,
        "exp": now + timedelta(minutes=JWT_EXPIRE_MINUTES),
    }

    return jwt.encode(
        payload,
        JWT_SECRET,
        algorithm=JWT_ALGORITHM,
    )


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
) -> dict[str, str]:
    token = credentials.credentials

    try:
        payload = jwt.decode(
            token,
            JWT_SECRET,
            algorithms=[JWT_ALGORITHM],
            options={"require": ["sub", "iat", "exp"]},
        )

    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token expired",
            headers={"WWW-Authenticate": "Bearer"},
        )

    except jwt.InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    username = payload["sub"]
    user = users.get(username)

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User no longer exists",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return user
```

This implementation is intentionally in-memory for learning. It is
production-shaped, but the dictionary is not production storage.

------------------------------------------------------------------------

# 5. API Layer

`app.py`:

``` python
from fastapi import Depends, FastAPI, HTTPException

from authentication import (
    authenticate_user,
    create_access_token,
    create_user,
    get_current_user,
)
from llm_harness import generate, LLMError
from validation import (
    ChatRequest,
    ChatResponse,
    LoginRequest,
    RegisterRequest,
    TokenResponse,
    Usage,
)


app = FastAPI()


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/register", status_code=201)
def register(body: RegisterRequest):
    user = create_user(
        username=body.username,
        password=body.password,
    )

    return {"username": user["username"]}


@app.post("/login", response_model=TokenResponse)
def login(body: LoginRequest):
    user = authenticate_user(
        username=body.username,
        password=body.password,
    )

    if user is None:
        raise HTTPException(
            status_code=401,
            detail="Invalid username or password",
        )

    token = create_access_token(
        username=user["username"],
    )

    return TokenResponse(
        access_token=token,
        token_type="bearer",
    )


@app.post("/chat", response_model=ChatResponse)
async def chat(
    body: ChatRequest,
    current_user: dict = Depends(get_current_user),
):
    try:
        result = await generate(body.message)
    except LLMError:
        raise HTTPException(
            status_code=502,
            detail="LLM provider failed",
        )

    return ChatResponse(
        response=result.text,
        model=result.model,
        usage=Usage(
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
        ),
        latency_ms=round(result.latency * 1000),
    )
```

The most important line is:

``` python
current_user: dict = Depends(get_current_user)
```

It creates the authentication gate in front of `/chat`.

------------------------------------------------------------------------

# 6. Registration Lifecycle

A first-time user sends:

``` http
POST /register
```

``` json
{
  "username": "alice",
  "password": "mypassword123"
}
```

Lifecycle:

``` text
Client
  ↓
POST /register
  ↓
RegisterRequest validation
  ↓
create_user()
  ↓
Does username already exist?
  ├── yes → 409 Conflict
  └── no
       ↓
   hash_password()
       ↓
      Argon2
       ↓
   password hash
       ↓
   store user
       ↓
      201
```

After registration, memory resembles:

``` python
{
    "alice": {
        "username": "alice",
        "password_hash": "$argon2id$..."
    }
}
```

It should never resemble:

``` python
{
    "alice": {
        "username": "alice",
        "password": "mypassword123"
    }
}
```

------------------------------------------------------------------------

# 7. Password Hashing

Passwords should not be stored in plaintext.

Registration:

``` text
plaintext password
       ↓
     Argon2
       ↓
password hash
       ↓
     storage
```

Code:

``` python
def hash_password(password: str) -> str:
    return password_hash.hash(password)
```

## Hashing vs encryption

Encryption is designed to be reversible:

``` text
plaintext
   ↓
encrypt
   ↓
ciphertext
   ↓
decrypt
   ↓
plaintext
```

Password hashing is used differently:

``` text
password
   ↓
password hashing function
   ↓
hash
```

During login, we do not decrypt the stored password. We verify the
submitted password against the stored hash:

``` python
def verify_password(password: str, hashed_password: str) -> bool:
    return password_hash.verify(password, hashed_password)
```

Conceptually:

``` text
submitted password
       +
stored password hash
       ↓
Argon2 verification
       ↓
true / false
```

## Why Argon2?

Password hashing should intentionally be expensive enough to make
large-scale password guessing harder than a fast general-purpose hash
would be. Argon2 is designed specifically for password hashing.

Do not replace password hashing with ordinary SHA-256 just because
SHA-256 is a hash function. General-purpose hashing and password hashing
solve different problems.

------------------------------------------------------------------------

# 8. Login Lifecycle

Client sends:

``` http
POST /login
```

``` json
{
  "username": "alice",
  "password": "mypassword123"
}
```

Flow:

``` text
Client
  ↓
POST /login
  ↓
authenticate_user()
  ↓
users.get("alice")
  ↓
user exists?
  ├── no → authentication fails
  └── yes
       ↓
verify submitted password
against stored password hash
       ↓
matches?
  ├── no → authentication fails
  └── yes
       ↓
identity confirmed
       ↓
create_access_token()
       ↓
JWT returned
```

Code:

``` python
def authenticate_user(username: str, password: str):
    user = users.get(username)

    if user is None:
        return None

    if not verify_password(password, user["password_hash"]):
        return None

    return user
```

The endpoint deliberately returns the same external message for an
unknown username and a wrong password:

``` text
Invalid username or password
```

This avoids unnecessarily revealing which usernames exist.

------------------------------------------------------------------------

# 9. Authentication vs Authorization

This distinction must be memorized.

## Authentication

Question:

> Who are you?

Examples:

``` text
Are you Alice?
Are you Bob?
Which user does this JWT represent?
```

Our system implements authentication.

## Authorization

Question:

> What are you allowed to do?

Example:

``` text
Alice → /chat
Admin → /chat + /admin
```

Authorization could involve roles, permissions, ownership rules,
policies, etc.

Memory rule:

``` text
Authentication = identity
Authorization  = permissions
```

Authentication usually happens before authorization:

``` text
Request
  ↓
Who are you?
  ↓
Authenticated identity
  ↓
What may you do?
  ↓
Authorized operation
```

We have not implemented role/permission authorization in this block.

------------------------------------------------------------------------

# 10. Why Use an Access Token?

After password verification, the client could theoretically send its
password with every `/chat` request. That is not the design we want.

Instead:

``` text
username + password
        ↓
      /login
        ↓
prove identity
        ↓
access token
        ↓
use token for later requests
```

So there are two phases:

## Phase A --- Credential authentication

``` text
username/password
       ↓
prove identity
```

## Phase B --- Token authentication

``` text
JWT
 ↓
authenticate subsequent API request
```

The password is used to obtain the token. The access token is then used
as the request credential.

------------------------------------------------------------------------

# 11. What Is a JWT?

JWT means **JSON Web Token**.

For this project, the useful mental model is:

> A JWT is a signed token containing claims that the server can later
> verify.

Our payload resembles:

``` json
{
  "sub": "alice",
  "iat": 1785000000,
  "exp": 1785001800
}
```

JWTs commonly have three logical sections:

``` text
HEADER.PAYLOAD.SIGNATURE
```

Conceptually:

``` text
Header
  ↓
metadata such as signing algorithm

Payload
  ↓
claims such as sub, iat, exp

Signature
  ↓
allows tampering to be detected
```

------------------------------------------------------------------------

# 12. JWT Claims We Used

## `sub` --- Subject

``` json
{
  "sub": "alice"
}
```

Meaning:

> This token represents Alice.

When verifying `/chat`:

``` python
username = payload["sub"]
```

Flow:

``` text
JWT
 ↓
verify
 ↓
payload
 ↓
sub
 ↓
alice
```

In larger systems, `sub` is often a stable user identifier rather than a
mutable username.

## `iat` --- Issued At

Records when the token was issued.

``` text
iat
 ↓
token creation time
```

## `exp` --- Expiration

Records when the token stops being valid.

``` text
iat                               exp
 │                                 │
 ▼                                 ▼
issued ─────── valid period ───── expired
```

Access tokens should not remain valid indefinitely.

------------------------------------------------------------------------

# 13. JWT Signing

The server has a signing secret:

``` text
JWT_SECRET
```

It stays server-side.

Token creation:

``` python
jwt.encode(
    payload,
    JWT_SECRET,
    algorithm=JWT_ALGORITHM,
)
```

Simplified mental model:

``` text
header + payload + JWT_SECRET
             ↓
          signature
```

Suppose a legitimate token contains:

``` json
{
  "sub": "alice"
}
```

A client tries to change it to:

``` json
{
  "sub": "admin"
}
```

The original signature no longer corresponds to the modified token.

The client cannot generate a correct replacement signature without the
signing secret.

Therefore:

``` text
modified JWT
    ↓
server verifies signature
    ↓
verification fails
    ↓
request rejected
```

------------------------------------------------------------------------

# 14. Signing Is Not Encryption

A common misconception:

> Signed JWT = secret payload.

Wrong.

The payload of a normal signed JWT can generally be decoded/read by
whoever possesses the token.

Signing primarily provides integrity/authenticity:

``` text
Signing:
Can unauthorized modification be detected?

Encryption:
Can unauthorized parties read the content?
```

Therefore do not put secrets in the JWT payload:

``` text
NO passwords
NO API keys
NO JWT signing secret
```

------------------------------------------------------------------------

# 15. JWT vs JWT Secret

These must never be confused.

## JWT

Example:

``` text
eyJhbGciOiJIUzI1Ni...
```

The client receives it.

The client sends it with requests.

## JWT_SECRET

Example configuration:

``` text
JWT_SECRET=<server-secret>
```

The server keeps it private.

With HS256, it is used to create and verify signatures.

``` text
SERVER

JWT_SECRET
   │
   ├── sign JWT
   └── verify JWT

CLIENT

JWT only
```

If the signing secret is compromised, an attacker may be able to forge
apparently valid tokens. Secret management therefore matters.

------------------------------------------------------------------------

# 16. Bearer Authentication

The client calls:

``` http
POST /chat
Authorization: Bearer <JWT>
```

Breakdown:

``` text
Authorization: Bearer <JWT>
       │           │      │
       │           │      └── credential
       │           └───────── authentication scheme
       └───────────────────── HTTP header
```

For this project:

> Bearer means the client presents possession of the token as its
> credential.

Because possession can grant access, access tokens must be protected.

Production APIs must use HTTPS so credentials are protected in transit.

------------------------------------------------------------------------

# 17. `HTTPBearer()` vs JWT Verification

We use:

``` python
bearer_scheme = HTTPBearer()
```

Important distinction:

`HTTPBearer()` extracts the Bearer credential from the HTTP request.

It does not perform our complete JWT validation.

Flow:

``` text
Authorization: Bearer eyJ...
          ↓
      HTTPBearer
          ↓
extract credential
          ↓
         eyJ...
```

Then:

``` python
token = credentials.credentials
```

Actual JWT verification is performed by:

``` python
jwt.decode(...)
```

Memory rule:

``` text
HTTPBearer → extract token
jwt.decode → verify token
```

------------------------------------------------------------------------

# 18. JWT Verification

Core code:

``` python
payload = jwt.decode(
    token,
    JWT_SECRET,
    algorithms=[JWT_ALGORITHM],
    options={
        "require": ["sub", "iat", "exp"],
    },
)
```

Conceptually:

``` text
incoming JWT
    ↓
parse token
    ↓
verify expected signing algorithm/signature
    ↓
validate expiration
    ↓
require expected claims
    ↓
return claims
```

If successful:

``` python
payload = {
    "sub": "alice",
    "iat": ...,
    "exp": ...,
}
```

We then obtain:

``` python
username = payload["sub"]
```

------------------------------------------------------------------------

# 19. Expired and Invalid Tokens

Expired token:

``` python
except jwt.ExpiredSignatureError:
    raise HTTPException(
        status_code=401,
        detail="Token expired",
        headers={"WWW-Authenticate": "Bearer"},
    )
```

Conceptually:

``` text
JWT
 ↓
signature valid
 ↓
exp checked
 ↓
expiration passed
 ↓
401
```

Invalid token:

``` python
except jwt.InvalidTokenError:
    raise HTTPException(
        status_code=401,
        detail="Invalid token",
        headers={"WWW-Authenticate": "Bearer"},
    )
```

Examples include malformed/tampered tokens and invalid signatures.

------------------------------------------------------------------------

# 20. Why Look Up the User After JWT Verification?

After verifying the JWT:

``` python
username = payload["sub"]
user = users.get(username)
```

Why not simply trust `sub` and return?

Because token validity and current application state are different
things.

Example:

``` text
10:00 Alice exists
      ↓
      login
      ↓
      JWT issued

10:10 Alice account removed

10:15 Alice presents old JWT
```

The JWT may still have:

``` text
valid signature
valid exp
sub = alice
```

But the application state says Alice no longer exists.

Therefore our dependency checks both:

``` text
token valid?
    ↓
yes
    ↓
current user exists?
    ↓
yes
    ↓
authenticated
```

This pattern becomes even more important when users can be disabled,
suspended, deleted, or have their security state changed.

------------------------------------------------------------------------

# 21. FastAPI Dependencies as an Authentication Gate

Protected endpoint:

``` python
@app.post("/chat")
async def chat(
    body: ChatRequest,
    current_user: dict = Depends(get_current_user),
):
    result = await generate(body.message)
```

The crucial line:

``` python
Depends(get_current_user)
```

FastAPI resolves the dependency before executing the endpoint body.

Mental model:

``` text
POST /chat
    ↓
get_current_user()
    ↓
authentication succeeds?
   /                    \
 yes                     no
  ↓                       ↓
execute chat()         reject request
```

If authentication raises an HTTP exception, this line is never reached:

``` python
result = await generate(body.message)
```

------------------------------------------------------------------------

# 22. Why Authentication Must Precede the LLM

LLM inference is expensive relative to checking a JWT.

It consumes:

-   provider quota
-   tokens
-   latency
-   compute
-   potentially money

Bad architecture:

``` text
request
 ↓
LLM generation
 ↓
authentication
 ↓
reject
```

The expensive operation already occurred.

Correct architecture:

``` text
request
 ↓
validation/authentication
 ↓
valid?
 ├── no → reject cheaply
 └── yes
      ↓
   LLM generation
```

General engineering principle:

> Perform cheap validation and security checks before expensive
> computation or side effects.

------------------------------------------------------------------------

# 23. Complete Protected `/chat` Lifecycle

``` text
Client
  ↓
POST /chat
Authorization: Bearer <JWT>
  ↓
FastAPI routing
  ↓
Depends(get_current_user)
  ↓
HTTPBearer
  ↓
extract JWT
  ↓
jwt.decode()
  ↓
verify signature
  ↓
check expiration
  ↓
require sub / iat / exp
  ↓
extract sub
  ↓
username = alice
  ↓
lookup current Alice
  ↓
return current_user
  ↓
dependency succeeds
  ↓
chat() starts
  ↓
generate(body.message)
  ↓
LLM Harness
  ↓
Gemini
  ↓
LLMResult
  ↓
ChatResponse
  ↓
Client
```

Invalid authentication short-circuits:

``` text
Client
 ↓
/chat
 ↓
JWT verification
 ↓
FAIL
 ↓
401
 ↓
STOP

LLM is never called
```

------------------------------------------------------------------------

# 24. Why `/login` and `/register` Are Public

A client does not yet possess a token when registering or initially
logging in.

If `/login` required a JWT:

``` text
Need JWT to login
       ↓
Need login to obtain JWT
       ↓
circular dependency
```

Therefore:

``` text
/register → public entry point for account creation
/login    → public entry point for credential authentication
/chat     → protected
```

Public does not mean "no security matters." Production
registration/login endpoints still need abuse controls, rate limiting,
HTTPS, secure validation, etc.

------------------------------------------------------------------------

# 25. Multiple Logins and Multiple Valid JWTs

Suppose Alice logs in from her laptop:

``` text
10:00
 ↓
JWT-A
sub = alice
exp = 10:30
```

Then logs in from her phone:

``` text
10:10
 ↓
JWT-B
sub = alice
exp = 10:40
```

At 10:15:

``` text
JWT-A → valid
JWT-B → valid
```

Our current system allows this.

Why?

Because verification asks:

``` text
Is JWT-A correctly signed?
Has JWT-A expired?
Does it contain required claims?
Does Alice currently exist?
```

It does not ask:

``` text
Is JWT-A Alice's newest token?
```

JWTs are independently valid credentials until they expire or until
additional server-side revocation/session rules reject them.

This behavior is often desirable because users may legitimately use:

``` text
Laptop
Phone
Tablet
```

simultaneously.

------------------------------------------------------------------------

# 26. Why Stateless JWTs Make Revocation Interesting

A basic JWT can be validated from:

``` text
token + signing key
```

without storing the token itself in a server-side session table.

That is useful, but it creates a tradeoff:

``` text
Token issued
    ↓
valid until exp
```

If the user logs out or an administrator wants to revoke a token early,
a purely stateless verifier has no automatic knowledge that the token
should stop working.

This is why production systems may add session/revocation state.

------------------------------------------------------------------------

# 27. Token Version Strategy

If the requirement is:

> Every new login should invalidate all older tokens for that user.

One simple design is a user-level token version.

Store:

``` python
users = {
    "alice": {
        "username": "alice",
        "password_hash": "...",
        "token_version": 2,
    }
}
```

JWT:

``` python
payload = {
    "sub": "alice",
    "ver": 2,
    "iat": now,
    "exp": expires_at,
}
```

Verification:

``` python
if payload["ver"] != user["token_version"]:
    raise HTTPException(
        status_code=401,
        detail="Token revoked",
    )
```

Example:

``` text
First login

user.token_version = 1
JWT-A.ver = 1

          ↓

Second login

user.token_version = 2
JWT-B.ver = 2
```

Now:

``` text
JWT-A.ver = 1
current version = 2
        ↓
      reject

JWT-B.ver = 2
current version = 2
        ↓
      accept
```

Tradeoff:

> A new login invalidates every previous device/session.

That may or may not match product requirements.

------------------------------------------------------------------------

# 28. Per-Device / Per-Session Design

A more flexible production design models sessions separately:

``` text
Alice
 │
 ├── session_A → Laptop
 │      └── active
 │
 ├── session_B → Phone
 │      └── active
 │
 └── session_C → Old laptop
        └── revoked
```

A JWT can contain a session identifier, often using a dedicated claim
chosen by the application.

Then authentication can verify:

``` text
JWT valid?
    ↓
which user?
    ↓
which session?
    ↓
is session still active?
    ↓
accept/reject
```

This enables features such as:

``` text
"Log out this device"
"Show logged-in devices"
"Log out all other devices"
"Revoke compromised session"
```

This introduces server-side state, which is one reason real
authentication systems are more than just JWT signing.

------------------------------------------------------------------------

# 29. Password Hashing vs JWT Signing

These are separate cryptographic concepts.

## Password hashing

Purpose:

> Verify passwords without storing plaintext passwords.

``` text
password
 ↓
Argon2
 ↓
password hash
```

Used during registration/login.

## JWT signing

Purpose:

> Make unauthorized token modification detectable.

``` text
claims + signing secret
        ↓
signed JWT
```

Used when issuing/verifying access tokens.

Memory rule:

``` text
Argon2
  → protects password storage

JWT signature
  → protects token integrity
```

------------------------------------------------------------------------

# 30. Credentials, Hashes, Tokens, and Secrets

Know exactly where each belongs.

  ---------------------------------------------------------------------------------
  Item           Example           Stored where?    Sent to client?  Purpose
  -------------- ----------------- ---------------- ---------------- --------------
  Password       `mypassword123`   Do not persist   User submits     Prove identity
                                   plaintext        during           
                                                    login/register   

  Password hash  `$argon2id$...`   User             No               Verify
                                   store/database                    passwords

  JWT access     `eyJ...`          Client; server   Yes              Authenticate
  token                            may be stateless                  API requests
                                   about it                          

  JWT signing    random secret     Server           Never            Sign/verify
  secret                           secret/config                     HS256 JWTs
                                   manager                           

  `sub`          `alice`           Inside JWT       Visible as JWT   Identify token
                                                    claim            subject

  `iat`          timestamp         Inside JWT       Visible as JWT   Token issue
                                                    claim            time

  `exp`          timestamp         Inside JWT       Visible as JWT   Token
                                                    claim            expiration
  ---------------------------------------------------------------------------------

------------------------------------------------------------------------

# 31. HTTP Statuses Used

Useful mental model:

``` text
201 Created
    → registration succeeded

401 Unauthorized
    → authentication credentials were missing/invalid/expired

409 Conflict
    → username already exists

422 Unprocessable Content
    → FastAPI/Pydantic request validation failed

502 Bad Gateway
    → application could not successfully obtain the upstream LLM result
```

Exact API error design can evolve, but keep authentication failures
distinct from input-validation and upstream-provider failures.

------------------------------------------------------------------------

# 32. What Is Not Production-Grade Yet?

The authentication *shape* is useful, but the current implementation is
not a complete production authentication system.

The largest issue:

``` python
users = {}
```

## Problem 1 --- Restart loses users

``` text
register Alice
 ↓
stored in process memory
 ↓
restart server
 ↓
memory cleared
 ↓
Alice disappears
```

## Problem 2 --- Multiple workers

``` text
Worker A              Worker B

users = {}            users = {}

Alice registers
   ↓
stored on A

request reaches B
   ↓
Alice absent
```

Production persistence should live in a shared durable datastore.

------------------------------------------------------------------------

# 33. Production Evolution

The useful evolution is:

``` text
CURRENT

authentication.py
      ↓
in-memory dictionary
```

toward:

``` text
PRODUCTION

API/auth service
      ↓
user repository/data-access layer
      ↓
database
```

The higher-level flow remains:

``` text
REGISTER
password → hash → persistent user record

LOGIN
find user → verify password → issue token

REQUEST
verify token → resolve current user/session → protected operation
```

This is why learning the flow before adding PostgreSQL is useful.

------------------------------------------------------------------------

# 34. Additional Production Enhancements

Important future enhancements include:

## Durable user storage

Replace the dictionary with PostgreSQL or another appropriate persistent
datastore.

Store:

``` text
user id
username/email
password hash
account state
created/updated timestamps
```

Never plaintext passwords.

## Stable user identifiers

Instead of:

``` text
sub = username
```

production systems commonly prefer:

``` text
sub = immutable user ID
```

because usernames/emails may change.

## HTTPS

Bearer tokens and passwords are credentials. Protect them in transit
with TLS/HTTPS.

## Strong secret management

Move signing secrets from developer `.env` files to deployment secret
management.

Support key rotation as the system matures.

## Additional JWT validation

Depending on architecture, validate claims such as:

``` text
iss → issuer
aud → audience
```

along with required `sub`, `iat`, and `exp`.

## Short-lived access tokens

Limit the impact of stolen tokens.

## Refresh/session strategy

Only when long-lived login is needed. This requires careful design
around refresh-token storage, rotation, revocation, and reuse.

## Rate limiting

Especially important for:

``` text
/login
/register
/chat
```

Authentication does not prevent an authenticated account from abusing
expensive LLM calls.

## Authorization

Add roles/permissions only when the product needs different privileges.

## Session/revocation support

Needed for:

``` text
logout
revoke stolen token/session
logout other devices
disable account immediately
```

## Audit/security logging

Useful events:

``` text
login failures
successful logins
authentication failures
session revocations
suspicious request rates
```

Never log:

``` text
passwords
full JWT access tokens
JWT_SECRET
API keys
```

------------------------------------------------------------------------

# 35. Authentication Does Not Replace Rate Limiting

Authentication answers:

``` text
Who is making this request?
```

It does not answer:

``` text
How many expensive requests should this user be allowed to make?
```

For an LLM service:

``` text
Authenticated Alice
      ↓
100,000 /chat requests
```

is still a potential abuse/cost problem.

A mature request path may eventually resemble:

``` text
Request
 ↓
validation
 ↓
authentication
 ↓
authorization
 ↓
rate/quota checks
 ↓
protected operation
 ↓
LLM
```

------------------------------------------------------------------------

# 36. Trust Boundaries

A useful architecture mindset is to ask:

> At this point in the request, what do I actually trust?

Before JWT verification:

``` text
Client-provided token
    ↓
UNTRUSTED
```

After successful cryptographic verification:

``` text
JWT claims
    ↓
cryptographically verified
```

But application state is still checked:

``` text
sub
 ↓
current user/session lookup
 ↓
current account state
```

Only then should the application proceed to protected work.

------------------------------------------------------------------------

# 37. End-to-End Architecture

``` text
                         CLIENT
                           │
           ┌───────────────┼─────────────────┐
           │               │                 │
           ▼               ▼                 ▼
       /register          /login            /chat
           │               │                 │
           ▼               ▼                 │
       validation       validation            │
           │               │                 │
           ▼               ▼                 │
      create user      find user              │
           │               │                 │
           ▼               ▼                 │
    password hashing   password verify        │
           │               │                 │
           ▼               ▼                 │
       user store       identity OK           │
                           │                  │
                           ▼                  │
                       create JWT             │
                           │                  │
                           ▼                  │
                         client               │
                           │                  │
                           └─ Bearer JWT ─────┘
                                              │
                                              ▼
                                         HTTPBearer
                                              │
                                              ▼
                                        extract JWT
                                              │
                                              ▼
                                         jwt.decode
                                              │
                         ┌────────────────────┼───────────────────┐
                         ▼                    ▼                   ▼
                    signature               exp            required claims
                         │                    │                   │
                         └────────────────────┼───────────────────┘
                                              ▼
                                            sub
                                              │
                                              ▼
                                      current user lookup
                                              │
                                              ▼
                                        authenticated
                                              │
                                              ▼
                                           /chat
                                              │
                                              ▼
                                         LLM Harness
                                              │
                                              ▼
                                         LLM Provider
```

------------------------------------------------------------------------

# 38. Testing Checklist

Use Swagger `/docs`.

## Registration

-   Valid new user → `201`
-   Duplicate username → `409`
-   Too-short username/password → validation rejection

## Login

-   Unknown username → `401`
-   Wrong password → `401`
-   Correct credentials → JWT returned

## `/chat`

-   No Bearer token → rejected
-   Valid JWT → works
-   Modify a JWT character → rejected
-   Expired JWT → `401`
-   Token missing required claims → rejected

## In-memory limitation

-   Register Alice
-   Restart server
-   Try logging in
-   Alice is gone

This demonstrates why persistence is the next data-layer improvement.

## Multiple login behavior

-   Login once → JWT-A
-   Login again → JWT-B
-   Before expiration, both should currently work

This demonstrates that our implementation does not revoke earlier tokens
on a new login.

------------------------------------------------------------------------

# 39. Revision Questions

You should be able to answer these without looking at code:

1.  What is the difference between authentication and authorization?
2.  Why should passwords be hashed instead of stored in plaintext?
3.  Why is password hashing different from encryption?
4.  What role does Argon2 play?
5.  What happens during registration?
6.  What happens during login?
7.  Why don't we send the password with every `/chat` request?
8.  What is a JWT?
9.  What does `sub` mean?
10. What does `iat` mean?
11. What does `exp` mean?
12. Why is a JWT signed?
13. Is a signed JWT encrypted?
14. What is `JWT_SECRET`?
15. Why must the client never receive `JWT_SECRET`?
16. What does `Authorization: Bearer <token>` mean?
17. What does FastAPI `HTTPBearer()` do?
18. What does `jwt.decode()` do?
19. Why are `HTTPBearer()` and `jwt.decode()` separate concepts?
20. What does `Depends(get_current_user)` do?
21. Why does `/chat` not execute when authentication fails?
22. Why should authentication happen before the LLM call?
23. Why do we look up the user after verifying the JWT?
24. Can the same user have multiple valid JWTs?
25. Why does a second login not automatically invalidate the first JWT?
26. What is token revocation?
27. What is a token-version strategy?
28. Why might per-device sessions be better than one user-level token
    version?
29. Why is an in-memory user dictionary not production-grade?
30. What changes when the dictionary is replaced by PostgreSQL?
31. Which authentication concepts remain unchanged after adding a
    database?
32. Why does authentication not solve LLM abuse/rate-limiting problems?

------------------------------------------------------------------------

# 40. Interview-Level Explanation

A concise explanation of the system:

> The service supports first-time registration and login. During
> registration, the password is processed with a password-hashing
> algorithm such as Argon2 and only the resulting password hash is
> stored. During login, the submitted password is verified against that
> stored hash. If the credentials are correct, the server issues a
> signed, expiring JWT containing claims such as `sub`, `iat`, and
> `exp`.
>
> The client sends the access token on protected requests using the
> `Authorization: Bearer <token>` header. FastAPI uses a dependency to
> extract the Bearer token, verify its JWT signature and expiration,
> require the expected claims, extract the subject, and resolve the
> current user. Only after this dependency succeeds does `/chat` execute
> and call the LLM harness.
>
> This ensures unauthenticated requests are rejected before expensive
> LLM inference. The current user store is intentionally in-memory for
> learning, so the next persistence step is replacing that dictionary
> with a database without changing the fundamental registration,
> password verification, JWT, and authentication flow.

------------------------------------------------------------------------

# 41. Final Cheat Sheet

``` text
AUTHENTICATION
Who are you?

AUTHORIZATION
What are you allowed to do?

REGISTER
validate → hash password → store hash

LOGIN
find user → verify password → issue JWT

ARGON2
password-hashing algorithm

PASSWORD HASH
server-side verifier representation; not plaintext password

JWT
signed token carrying claims

sub
subject / identity

iat
issued-at time

exp
expiration time

JWT SIGNATURE
detects unauthorized token modification

JWT_SECRET
server-side HS256 signing secret

BEARER TOKEN
credential presented in Authorization header

HTTPBearer
extracts Bearer credentials from HTTP request

jwt.decode
verifies/decodes JWT according to configured checks

Depends(get_current_user)
authentication gate before endpoint execution

401
authentication credentials not accepted

MULTIPLE JWTs
same user can currently have multiple valid tokens simultaneously

REVOCATION
server-side mechanism/rule for invalidating a token/session before exp

IN-MEMORY USERS
good for learning, not durable/shared production storage
```

------------------------------------------------------------------------

# 42. The One Mental Model to Remember

``` text
FIRST-TIME REGISTRATION

password
   ↓
validate
   ↓
Argon2 hash
   ↓
store password hash


LOGIN

username + password
       ↓
find user
       ↓
verify password against hash
       ↓
identity confirmed
       ↓
create signed JWT
       ↓
client receives access token


PROTECTED REQUEST

Authorization: Bearer <JWT>
       ↓
extract token
       ↓
verify signature
       ↓
check expiration/required claims
       ↓
extract sub
       ↓
resolve current user/session
       ↓
authentication succeeds
       ↓
protected endpoint
       ↓
LLM Harness
       ↓
LLM Provider
```

The most important architectural principle from this block is:

> **Never perform the expensive protected LLM operation until the
> request has successfully crossed the authentication boundary.**
