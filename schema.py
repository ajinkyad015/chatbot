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


class CreateConversationResponse(BaseModel):
    conversation_id: int


class ChatRequest(BaseModel):
    conversation_id: int
    message: str = Field(min_length=1, max_length=10_000)


class Usage(BaseModel):
    input_tokens: int
    output_tokens: int


class ChatResponse(BaseModel):
    response: str
    model: str
    usage: Usage
    latency_ms: int