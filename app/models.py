from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    query: str = Field(..., max_length=500)
    force_refresh: bool = Field(default=False)


class ChatResponse(BaseModel):
    response: str
    request_id: str
    email_count: int
    filtered_count: int
    cache_age_s: float
    tokens_used: int
    stale: bool = False


class ErrorResponse(BaseModel):
    error: str
    request_id: str


class HealthResponse(BaseModel):
    status: str = "ok"
    uptime_s: float
