from fastapi import Depends, FastAPI, HTTPException, Request
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
    StatelessRequest,
)
from database import Base, engine
import models
from redis_client import redis_client

import hashlib
import json
import time
import uuid

from logging_config import logger

app = FastAPI()

@app.middleware("http")
async def add_request_id(request: Request, call_next):
    request_id = str(uuid.uuid4())

    request.state.request_id = request_id

    response = await call_next(request)

    response.headers["X-Request-ID"] = request_id

    return response

Base.metadata.create_all(bind=engine)

MAX_CONTEXT_MESSAGES = 20
CACHE_TTL_SECONDS = 60
RATE_LIMIT_REQUESTS = 1
RATE_LIMIT_WINDOW_SECONDS = 60

### block 1 health endpoint
@app.get("/health")
def health():
    return {"status": "ok"}


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
    request: Request,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):  
    request_start = time.perf_counter()
    request_id = request.state.request_id
    username = current_user["username"]
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

    # redis rate limiting;
    rate_limit_key = f"rate_limit:{username}"

    request_count = await redis_client.incr(rate_limit_key)

    if request_count == 1:
        await redis_client.expire(
            rate_limit_key,
            RATE_LIMIT_WINDOW_SECONDS,
        )

    ttl = await redis_client.ttl(rate_limit_key)

    # print(
    #     f"[RATE LIMIT] user={username} "
    #     f"count={request_count}/{RATE_LIMIT_REQUESTS} "
    #     f"ttl={ttl}s"
    # )

    if request_count > RATE_LIMIT_REQUESTS:
        total_latency_ms = round(
            (time.perf_counter() - request_start) * 1000
        )

        logger.warning(
            "Chat request rate limited",
            extra={
                "event_data": {
                    "event": "chat_request_rate_limited",
                    "request_id": request_id,
                    "user_id": username,
                    "conversation_id": body.conversation_id,
                    "rate_limited": True,
                    "total_latency_ms": total_latency_ms,
                    "status": "failed",
                }
            },
        )

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

    except LLMError as e:
        total_latency_ms = round(
            (time.perf_counter() - request_start) * 1000
        )

        logger.error(
            "Chat request failed",
            extra={
                "event_data": {
                    "event": "chat_request_failed",
                    "request_id": request_id,
                    "user_id": username,
                    "conversation_id": body.conversation_id,
                    "error_type": type(e).__name__,
                    "total_latency_ms": total_latency_ms,
                    "status": "failed",
                }
            },
        )

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

    total_latency_ms = round(
        (time.perf_counter() - request_start) * 1000
    )

    llm_latency_ms = round(result.latency * 1000)
    
    logger.info(
        "Chat request completed",
        extra={
            "event_data": {
                "event": "chat_request_completed",
                "request_id": request_id,
                "user_id": username,
                "conversation_id": conversation.id,
                "model": result.model,
                "input_tokens": result.input_tokens,
                "output_tokens": result.output_tokens,
                "llm_latency_ms": llm_latency_ms,
                "total_latency_ms": total_latency_ms,
                "cache_hit": False,
                "attempts": result.attempts,
                "rate_limited": False,
                "status": "success",
            }
        },
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

@app.post("/chat/stateless")
async def stateless_chat(
    body: StatelessRequest,
    request: Request,
    current_user: dict = Depends(get_current_user),
    
):
    request_id = request.state.request_id
    username = current_user["username"]
    # Same effective input -> same deterministic cache key.
    message_hash = hashlib.sha256(
        body.message.encode("utf-8")
    ).hexdigest()

    cache_key = f"llm_cache:{message_hash}"

    # 1. Check Redis.
    cached = await redis_client.get(cache_key)

    if cached is not None:
        logger.info(
            "LLM cache hit",
            extra={
                "event_data": {
                    "event": "llm_cache_hit",
                    "request_id": request_id,
                    "user_id": username,
                    "cache_hit": True,
                }
            },
        )

        return {
            "response": cached,
            "cache_hit": True,
        }

    # 2. Cache miss -> call LLM.
    logger.info(
        "LLM cache miss",
        extra={
            "event_data": {
                "event": "llm_cache_miss",
                "request_id": request_id,
                "user_id": username,
                "cache_hit": False,
            }
        },
    )

    result = await generate([
        {
            "role": "user",
            "content": body.message,
        }
    ])

    # 3. Store response temporarily.
    await redis_client.set(
        cache_key,
        result.text,
        ex=CACHE_TTL_SECONDS,
    )


    return {
        "response": result.text,
        "cache_hit": False,
    }