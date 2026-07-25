
from pydantic import BaseModel
class LoginRequest(BaseModel):
    username: str
    password: str


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
