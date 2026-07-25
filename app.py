# app.py
import os
from datetime import datetime, timedelta, timezone

import jwt
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException

from llm_harness import generate, LLMError

from schema import LoginRequest, ChatRequest, ChatResponse, Usage
from authentication import authenticate, DEMO_USERNAME, DEMO_PASSWORD, JWT_SECRET, JWT_ALGORITHM, TOKEN_EXPIRE_MINUTES
load_dotenv()

app = FastAPI()

@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/login")
def login(body: LoginRequest):
    if (
        body.username != DEMO_USERNAME
        or body.password != DEMO_PASSWORD
    ):
        raise HTTPException(
            status_code=401,
            detail="Invalid credentials",
        )

    expires_at = datetime.now(timezone.utc) + timedelta(
        minutes=TOKEN_EXPIRE_MINUTES
    )

    payload = {
        "sub": body.username,
        "exp": expires_at,
    }

    token = jwt.encode(
        payload,
        JWT_SECRET,
        algorithm=JWT_ALGORITHM,
    )

    return {
        "access_token": token,
        "token_type": "bearer",
    }


@app.post("/chat", response_model=ChatResponse)
async def chat(
    body: ChatRequest,
    username: str = Depends(authenticate),
):
    result = await generate(body.message)

    return ChatResponse(
        response=result.text,
        model=result.model,
        usage=Usage(
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
        ),
        latency_ms=round(result.latency * 1000),
    )