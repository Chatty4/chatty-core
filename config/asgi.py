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
            try:
                from shared.redis import get_redis_client

                get_redis_client()
            except Exception as exc:
                await send({"type": "lifespan.startup.failed", "message": str(exc)})
                return
            await send({"type": "lifespan.startup.complete"})
        elif event["type"] == "lifespan.shutdown":
            from shared.redis import close_redis_client

            await close_redis_client()
            await send({"type": "lifespan.shutdown.complete"})
            return
