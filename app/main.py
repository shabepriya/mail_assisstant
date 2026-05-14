import time
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

from app.api.v1.router import router as v1_router
from app.cache import EmailCache
from app.config import get_settings
from app.logging_config import setup_logging
from app.pending_calendar import PendingCalendarStore
from app.pending_reply import PendingReplyStore
from app.routes import chat as chat_routes
from app.routes import health as health_routes
from app.security.idempotency import IdempotencyStore


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    setup_logging(settings.log_level)
    app.state.http_client = httpx.AsyncClient(timeout=settings.email_api_timeout, trust_env=False)
    app.state.cache = EmailCache(settings.cache_ttl_seconds)
    app.state.pending_calendar = PendingCalendarStore(settings.calendar_pending_ttl_seconds)
    app.state.pending_reply = PendingReplyStore(settings.reply_pending_ttl_seconds)
    app.state.idempotency = IdempotencyStore()
    app.state.start = time.monotonic()
    yield
    await app.state.http_client.aclose()


app = FastAPI(title="AI Email Assistant", lifespan=lifespan)

_settings = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=_settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(HTTPException)
async def http_exception_handler(_request: Request, exc: HTTPException) -> JSONResponse:
    detail = exc.detail
    if isinstance(detail, dict) and "error" in detail and "request_id" in detail:
        return JSONResponse(status_code=exc.status_code, content=detail)
    if isinstance(detail, dict):
        return JSONResponse(status_code=exc.status_code, content=detail)
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": str(detail)},
    )


app.include_router(health_routes.router)
app.include_router(chat_routes.router)
app.include_router(v1_router)


@app.get("/")
async def index_page() -> FileResponse:
    """Serve chat UI (routers registered above take precedence for /health, /ai)."""
    return FileResponse("static/index.html")
