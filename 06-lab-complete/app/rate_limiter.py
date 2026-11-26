"""
Rate limiting (tiêu chí 7) — Sliding window 60 giây trên Redis sorted set.
"""
import hashlib
import time
import uuid

import redis
from fastapi import HTTPException

from app.config import settings
from app.redis_client import r

WINDOW_SECONDS = 60


def check_rate_limit(key: str) -> None:
    """Giới hạn tối đa RATE_LIMIT_PER_MINUTE request / 60s cho mỗi API key."""
    if r is None:
        raise HTTPException(status_code=503, detail="Rate limiter storage unavailable")

    key_hash = hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]
    redis_key = f"rate_limit:{key_hash}"
    now = time.time()
    window_start = now - WINDOW_SECONDS

    try:
        r.zremrangebyscore(redis_key, 0, window_start)
        current = r.zcard(redis_key)

        if current >= settings.rate_limit_per_minute:
            oldest = r.zrange(redis_key, 0, 0, withscores=True)
            retry_after = WINDOW_SECONDS
            if oldest:
                retry_after = max(1, min(WINDOW_SECONDS, int(oldest[0][1] + WINDOW_SECONDS - now) + 1))
            raise HTTPException(
                status_code=429,
                detail="Rate limit exceeded",
                headers={"Retry-After": str(retry_after)},
            )

        member = f"{now}:{uuid.uuid4().hex[:8]}"
        r.zadd(redis_key, {member: now})
        r.expire(redis_key, WINDOW_SECONDS)
    except HTTPException:
        raise
    except redis.RedisError:
        raise HTTPException(status_code=503, detail="Rate limiter storage unavailable")
