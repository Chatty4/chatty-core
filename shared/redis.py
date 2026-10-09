import logging
from functools import lru_cache

from django.conf import settings
from redis.asyncio import Redis
from redis.exceptions import RedisError

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def get_redis_client() -> Redis:
    return Redis.from_url(settings.REDIS_URL, decode_responses=True, socket_timeout=3)


async def close_redis_client() -> None:
    client = get_redis_client()
    get_redis_client.cache_clear()
    await client.aclose()


async def rate_limit(key: str, limit: int, window: int) -> int:
    """Returns seconds until reset if blocked, 0 if allowed."""
    redis = get_redis_client()
    count = await redis.incr(key)
    if count == 1:
        await redis.expire(key, window)
    if count > limit:
        return max(await redis.ttl(key), 1)
    return 0


async def clear_rate_limit(key: str) -> None:
    try:
        await get_redis_client().delete(key)
    except RedisError:
        logger.warning("Failed to clear rate limit key %s", key)


async def is_rate_limited(key: str, limit: int) -> int:
    """Returns seconds until reset if currently over limit, 0 otherwise. Does not increment."""
    redis = get_redis_client()
    count_str = await redis.get(key)
    if count_str and int(count_str) > limit:
        return max(await redis.ttl(key), 1)
    return 0
