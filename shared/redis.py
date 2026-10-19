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
    """Returns seconds until reset if blocked, 0 if allowed. Fails open if Redis is down."""
    try:
        redis = get_redis_client()
        async with redis.pipeline(transaction=False) as pipe:
            await pipe.incr(key)
            await pipe.expire(key, window, nx=True)
            count, _ = await pipe.execute()
        if count > limit:
            return max(await redis.ttl(key), 1)
    except RedisError:
        # error, not warning: requests are now let through without a rate limit
        logger.error("Rate limit check failed for %s, allowing request", key)
    return 0


async def clear_rate_limit(key: str) -> None:
    try:
        await get_redis_client().delete(key)
    except RedisError:
        logger.warning("Failed to clear rate limit key %s", key)


async def undo_rate_limit(key: str) -> None:
    """Take back one rate_limit() hit, e.g. for a request that turned out fine."""
    try:
        redis = get_redis_client()
        if await redis.decr(key) <= 0:
            await redis.delete(key)  # also cleans up if the key expired and decr created -1
    except RedisError:
        logger.warning("Failed to undo rate limit key %s", key)
