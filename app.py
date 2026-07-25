# app.py
from fastapi import FastAPI
from pydantic import BaseModel

from llm_harness import generate, LLMError

app = FastAPI()


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


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/chat", response_model=ChatResponse)
async def chat(body: ChatRequest):
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