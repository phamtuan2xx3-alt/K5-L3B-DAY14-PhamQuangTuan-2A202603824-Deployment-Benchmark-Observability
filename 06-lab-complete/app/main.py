"""
Production AI Agent — Part 6 Final Project.
"""
import json
import logging
import signal
import sys
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.auth import verify_api_key
from app.config import settings
from app.cost_guard import check_budget, record_cost
from app.rate_limiter import check_rate_limit
from app.redis_client import r as redis_conn, redis_healthy
from utils.mock_llm import ask as llm_ask


class JsonFormatter(logging.Formatter):
    """Định dạng mỗi dòng log của app thành 1 JSON object hợp lệ."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "lvl": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        extra_fields = getattr(record, "fields", None)
        if isinstance(extra_fields, dict):
            payload.update(extra_fields)
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def _configure_logger() -> logging.Logger:
    app_logger = logging.getLogger("production_agent")
    app_logger.handlers.clear()
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    app_logger.addHandler(handler)
    app_logger.setLevel(getattr(logging, settings.log_level, logging.INFO))
    app_logger.propagate = False
    return app_logger


logger = _configure_logger()


def _log_event(event: str, level: int = logging.INFO, **fields) -> None:
    logger.log(level, event, extra={"fields": {"event": event, **fields}})


_previous_sigterm = signal.getsignal(signal.SIGTERM)


def _handle_sigterm(signum, frame) -> None:
    _log_event("sigterm_received", signal=signum)
    if callable(_previous_sigterm):
        _previous_sigterm(signum, frame)


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        signal.signal(signal.SIGTERM, _handle_sigterm)
    except ValueError:
        pass
    _log_event("startup", environment=settings.environment, port=settings.port)
    yield
    _log_event("graceful_shutdown", environment=settings.environment)
    if redis_conn is not None:
        try:
            redis_conn.close()
        except Exception:
            pass


app = FastAPI(title="Production AI Agent", lifespan=lifespan)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    start = time.perf_counter()
    status = 500
    try:
        response = await call_next(request)
        status = response.status_code
        return response
    finally:
        elapsed_ms = round((time.perf_counter() - start) * 1000, 2)
        _log_event(
            "http_request",
            method=request.method,
            path=request.url.path,
            status=status,
            ms=elapsed_ms,
        )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    _log_event("unhandled_error", level=logging.ERROR, path=request.url.path, error=str(exc))
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


class AskRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)
    user_id: Optional[str] = Field(default=None, max_length=128)


@app.get("/health")
def health():
    """Liveness probe: luôn trả 200 khi process còn sống (không phụ thuộc Redis)."""
    return {"status": "ok", "environment": settings.environment}


@app.get("/ready")
def ready():
    """Readiness probe: 200 khi Redis sẵn sàng, 503 khi mất kết nối Redis."""
    if not redis_healthy():
        raise HTTPException(status_code=503, detail="Redis not ready")
    return {"status": "ready", "redis": "ok"}


@app.post("/ask")
def ask(body: AskRequest, api_key: str = Depends(verify_api_key)):
    check_rate_limit(api_key)
    check_budget()

    answer = llm_ask(body.question)
    input_tokens = max(1, len(body.question) // 4)
    output_tokens = max(1, len(answer) // 4)
    cost = record_cost(input_tokens, output_tokens)

    _log_event(
        "ask_completed",
        user_id=body.user_id or "anonymous",
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost_usd=round(cost, 8),
    )

    return {
        "question": body.question,
        "answer": answer,
        "usage": {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cost_usd": round(cost, 8),
        },
    }
