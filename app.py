from fastapi import Depends, FastAPI, HTTPException

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