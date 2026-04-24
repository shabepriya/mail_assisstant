import time
from typing import Annotated

from fastapi import APIRouter, Request

from app.models import HealthResponse

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
async def health(request: Request) -> HealthResponse:
    start: float = request.app.state.start  # type: ignore[attr-defined]
    return HealthResponse(status="ok", uptime_s=time.monotonic() - start)
