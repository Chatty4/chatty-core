import json
import logging
from enum import StrEnum
from typing import Any

from django.core.serializers.json import DjangoJSONEncoder
from django.utils import timezone
from redis.exceptions import RedisError

from shared.redis import get_redis_client

logger = logging.getLogger(__name__)

CHANNEL = "core.events"


class EventType(StrEnum):
    MEMBERSHIP_CHANGED = "membership.changed"
    TEAM_MEMBER_CHANGED = "team.member.changed"
    CHANNEL_UPDATED = "channel.updated"
    TEAM_DELETED = "team.deleted"
    USER_DEACTIVATED = "user.deactivated"


async def publish(event_type: EventType, data: dict[str, Any]) -> None:
    """
    Publish one event. Call it only after the change is committed. If Redis fails, log it
    and return: the request still succeeds and chatty-chat's cache TTL fixes the data later.
    """
    message = json.dumps(
        {"type": event_type, "occurred_at": timezone.now(), "data": data}, cls=DjangoJSONEncoder
    )

    try:
        await get_redis_client().publish(CHANNEL, message)
    except RedisError:
        logger.exception("Failed to publish %s on %s", event_type, CHANNEL)
