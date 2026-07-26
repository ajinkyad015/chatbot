from fastapi import Depends, FastAPI, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

import models
from database import Base, engine, get_db

from authentication import (
    authenticate_user,
    create_access_token,
    create_user,
    get_current_user,
)
from llm_harness import generate, LLMError
from schema import (
    ChatRequest,
    ChatResponse,
    CreateConversationResponse,
    LoginRequest,
    RegisterRequest,
    TokenResponse,
    Usage,
)
from database import Base, engine
import models

app = FastAPI()
Base.metadata.create_all(bind=engine)

MAX_CONTEXT_MESSAGES = 20

RATE_LIMIT_REQUESTS = 1
RATE_LIMIT_WINDOW_SECONDS = 60
@app.get("/health")
def health():
    return {"status": "ok"}

from redis_client import redis_client


@app.get("/health/redis")
async def redis_health():
    pong = await redis_client.ping()

    return {
        "redis": "ok",
        "ping": pong,
    }

@app.post("/register", status_code=201)
def register(body: RegisterRequest):
    user = create_user(
        username=body.username,
        password=body.password,
    )

    return {
        "username": user["username"],
    }


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
@app.post(
    "/conversations",
    response_model=CreateConversationResponse,
    status_code=201,
)
def create_conversation(
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    username = current_user["username"]

    conversation = models.Conversation(
        user_id=username,
    )

    db.add(conversation)
    db.commit()
    db.refresh(conversation)

    return CreateConversationResponse(
        conversation_id=conversation.id,
    )

@app.post("/chat", response_model=ChatResponse)
async def chat(
    body: ChatRequest,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    username = current_user["username"]

    # 1. Load the requested conversation.
    conversation = db.get(
        models.Conversation,
        body.conversation_id,
    )

    if conversation is None:
        raise HTTPException(
            status_code=404,
            detail="Conversation not found",
        )

    # 2. Authorization: verify ownership.
    if conversation.user_id != username:
        raise HTTPException(
            status_code=403,
            detail="You do not have access to this conversation",
        )

        username = current_user["username"]

    rate_limit_key = f"rate_limit:{username}"

    request_count = await redis_client.incr(rate_limit_key)

    if request_count == 1:
        await redis_client.expire(
            rate_limit_key,
            RATE_LIMIT_WINDOW_SECONDS,
        )

    ttl = await redis_client.ttl(rate_limit_key)

    print(
        f"[RATE LIMIT] user={username} "
        f"count={request_count}/{RATE_LIMIT_REQUESTS} "
        f"ttl={ttl}s"
    )

    if request_count > RATE_LIMIT_REQUESTS:
        raise HTTPException(
            status_code=429,
            detail="Too many requests",
        )

    # 3. Load recent conversation history.
    statement = (
        select(models.Message)
        .where(
            models.Message.conversation_id == conversation.id
        )
        .order_by(models.Message.id.desc())
        .limit(MAX_CONTEXT_MESSAGES)
    )

    history = list(
        db.scalars(statement).all()
    )

    # Query was newest -> oldest.
    # LLM needs oldest -> newest.
    history.reverse()

    # 4. Convert DB rows into the format expected by the LLM harness.
    messages = [
        {
            "role": message.role,
            "content": message.content,
        }
        for message in history
    ]

    current_message = {
        "role": "user",
        "content": body.message,
    }

    messages.append(current_message)

    # 5. Call the existing LLM harness.
    try:
        result = await generate(messages)

    except LLMError:
        raise HTTPException(
            status_code=502,
            detail="LLM provider failed",
        )

    # 6. Persist user + assistant messages.
    user_message = models.Message(
        conversation_id=conversation.id,
        role="user",
        content=body.message,
    )

    assistant_message = models.Message(
        conversation_id=conversation.id,
        role="assistant",
        content=result.text,
    )

    db.add(user_message)
    db.add(assistant_message)
    db.commit()

    print(f"Messages in context: {len(messages)}")
    print(f"Input tokens: {result.input_tokens}")

    return ChatResponse(
        response=result.text,
        model=result.model,
        usage=Usage(
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
        ),
        latency_ms=round(result.latency * 1000),
    )