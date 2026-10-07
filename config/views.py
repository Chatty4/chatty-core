import asyncio
import logging

from asgiref.sync import sync_to_async
from django.db import connection
from django.http import JsonResponse
from django.views.decorators.http import require_GET

logger = logging.getLogger(__name__)


def ping_db() -> None:
    with connection.cursor() as cursor:
        cursor.execute("SELECT 1")


@require_GET
async def health(request) -> JsonResponse:
    try:
        async with asyncio.timeout(2):
            await sync_to_async(ping_db)()
        db = "ok"
    except Exception:
        logger.exception("Database health check failed")
        db = "error"

    if db == "ok":
        return JsonResponse({"status": "ok", "db": db})
    return JsonResponse({"status": "degraded", "db": db}, status=503)
