import asyncio
import logging
from collections.abc import Awaitable, Callable

from asgiref.sync import sync_to_async
from django.db import connection
from django.http import JsonResponse
from django.views.decorators.http import require_GET

from shared.redis import get_redis_client

logger = logging.getLogger(__name__)


def ping_db() -> None:
    with connection.cursor() as cursor:
        cursor.execute("SELECT 1")


async def ping_redis() -> None:
    await get_redis_client().ping()


async def check(name: str, probe: Callable[[], Awaitable[None]]) -> str:
    try:
        async with asyncio.timeout(2):
            await probe()
        return "ok"
    except Exception:
        logger.exception("Health check failed: %s", name)
        return "error"


@require_GET
async def health(request) -> JsonResponse:
    db, redis = await asyncio.gather(
        check("db", sync_to_async(ping_db)),
        check("redis", ping_redis),
    )
    checks = {"db": db, "redis": redis}

    if all(result == "ok" for result in checks.values()):
        return JsonResponse({"status": "ok", **checks})
    return JsonResponse({"status": "degraded", **checks}, status=503)


def not_found(request, exception) -> JsonResponse:
    """Unknown URL: same error body as the rest of the API."""
    return JsonResponse({"error": {"code": "not_found", "message": "Not found"}}, status=404)
