import pytest

from shared.redis import clear_rate_limit, get_redis_client, rate_limit

KEY = "test:rl"
LIMIT = 3
WINDOW = 60


@pytest.fixture(autouse=True)
async def reset():
    # Fresh client per test — each pytest function gets its own event loop, so the cached
    # client from the previous test holds connections on the wrong (closed) loop.
    get_redis_client.cache_clear()
    get_redis_client()
    yield
    await clear_rate_limit(KEY)
    await get_redis_client().aclose()
    get_redis_client.cache_clear()


async def test_under_limit_returns_zero():
    for _ in range(LIMIT):
        assert await rate_limit(KEY, LIMIT, WINDOW) == 0


async def test_over_limit_returns_retry_after():
    for _ in range(LIMIT + 1):
        result = await rate_limit(KEY, LIMIT, WINDOW)
    assert result > 0


async def test_retry_after_is_within_window():
    for _ in range(LIMIT + 1):
        result = await rate_limit(KEY, LIMIT, WINDOW)
    assert 0 < result <= WINDOW


async def test_window_ttl_set_on_first_increment():
    await rate_limit(KEY, LIMIT, WINDOW)
    ttl = await get_redis_client().ttl(KEY)
    assert 0 < ttl <= WINDOW


async def test_clear_resets_counter():
    for _ in range(LIMIT):
        await rate_limit(KEY, LIMIT, WINDOW)

    await clear_rate_limit(KEY)

    assert await rate_limit(KEY, LIMIT, WINDOW) == 0


async def test_clear_on_missing_key_is_silent():
    await clear_rate_limit("test:rl:nonexistent")  # must not raise


async def test_independent_keys_do_not_share_counters():
    other = "test:rl:other"
    try:
        for _ in range(LIMIT + 1):
            await rate_limit(KEY, LIMIT, WINDOW)

        assert await rate_limit(other, LIMIT, WINDOW) == 0
    finally:
        await clear_rate_limit(other)
