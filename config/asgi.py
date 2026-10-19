import os
from typing import Any

from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

_django_app = get_asgi_application()


async def application(scope: dict[str, Any], receive: Any, send: Any) -> None:
    if scope["type"] == "lifespan":
        await _handle_lifespan(receive, send)
    else:
        await _django_app(scope, receive, send)


async def _handle_lifespan(receive: Any, send: Any) -> None:
    while True:
        event = await receive()
        if event["type"] == "lifespan.startup":
            await send({"type": "lifespan.startup.complete"})
        elif event["type"] == "lifespan.shutdown":
            from asgiref.sync import sync_to_async
            from django.db import connection

            from shared.redis import close_redis_client

            await close_redis_client()
            await sync_to_async(connection.close_pool)()  # type: ignore[attr-defined]  # Postgres backend only
            await send({"type": "lifespan.shutdown.complete"})
            return
