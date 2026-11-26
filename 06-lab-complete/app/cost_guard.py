"""
Cost guard (tiêu chí 8) — Theo dõi và giới hạn chi phí LLM trên Redis.
"""
from datetime import datetime, timezone

import redis
from fastapi import HTTPException

from app.config import settings
from app.redis_client import r

# Giá USD / 1K tokens (tham khảo gpt-4o-mini)
PRICE_INPUT_PER_1K = 0.00015
PRICE_OUTPUT_PER_1K = 0.0006


def _budget_key() -> str:
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return f"cost_guard:daily:{day}"


def check_budget() -> None:
    """Gọi TRƯỚC khi gọi LLM. Hết budget → raise HTTPException(status_code=402)."""
    if r is None:
        raise HTTPException(status_code=503, detail="Cost guard storage unavailable")

    try:
        current_spent = float(r.get(_budget_key()) or 0.0)
    except (redis.RedisError, ValueError):
        raise HTTPException(status_code=503, detail="Cost guard storage unavailable")

    if current_spent >= settings.daily_budget_usd:
        raise HTTPException(
            status_code=402,
            detail="Daily LLM budget exceeded",
        )


def record_cost(input_tokens: int, output_tokens: int) -> float:
    """Gọi SAU khi gọi LLM. Cộng chi phí vào tổng trong Redis và trả về chi phí request."""
    cost = (
        (input_tokens / 1000.0) * PRICE_INPUT_PER_1K
        + (output_tokens / 1000.0) * PRICE_OUTPUT_PER_1K
    )
    if r is not None and cost > 0:
        try:
            key = _budget_key()
            r.incrbyfloat(key, cost)
            r.expire(key, 48 * 3600)
        except redis.RedisError:
            pass
    return cost
