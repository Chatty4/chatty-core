import json
import logging
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from redis.exceptions import ConnectionError as RedisConnectionError

from shared.events import CHANNEL, EventType, publish
from shared.redis import get_redis_client


class RecordingRedis:
    def __init__(self):
        self.sent: list[tuple[str, str]] = []

    async def publish(self, channel: str, message: str) -> int:
        self.sent.append((channel, message))
        return 0


class DownRedis:
    def __getattr__(self, name):
        raise RedisConnectionError("redis down")


@pytest.fixture
def recording(monkeypatch):
    fake = RecordingRedis()
    monkeypatch.setattr("shared.events.get_redis_client", lambda: fake)
    return fake


async def test_envelope_shape(recording):
    team_id = uuid4()

    await publish(EventType.TEAM_DELETED, {"team_id": team_id})

    [(channel, message)] = recording.sent
    event = json.loads(message)
    assert channel == "core.events"
    assert set(event) == {"type", "occurred_at", "data"}
    assert event["type"] == "team.deleted"
    assert event["data"] == {"team_id": str(team_id)}


async def test_occurred_at_is_utc_now(recording):
    await publish(EventType.USER_DEACTIVATED, {"user_id": uuid4()})

    occurred_at = json.loads(recording.sent[0][1])["occurred_at"]
    assert occurred_at.endswith("Z")
    sent_at = datetime.fromisoformat(occurred_at)
    assert abs(datetime.now(UTC) - sent_at) < timedelta(seconds=5)


async def test_redis_down_is_logged_and_does_not_raise(monkeypatch, caplog):
    monkeypatch.setattr("shared.events.get_redis_client", lambda: DownRedis())

    with caplog.at_level(logging.ERROR, logger="shared.events"):
        await publish(EventType.TEAM_DELETED, {"team_id": uuid4()})

    assert "Failed to publish team.deleted" in caplog.text


# --- real Redis ---


@pytest.fixture
async def real_redis():
    # each test has its own event loop, so the cached client must not outlive the test
    get_redis_client.cache_clear()
    yield get_redis_client()
    await get_redis_client().aclose()
    get_redis_client.cache_clear()


async def test_subscriber_receives_the_event(real_redis):
    pubsub = real_redis.pubsub()
    await pubsub.subscribe(CHANNEL)
    await pubsub.get_message(timeout=1)  # the subscribe confirmation
    team_id = uuid4()

    await publish(EventType.TEAM_DELETED, {"team_id": team_id})

    message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=2)
    await pubsub.aclose()
    assert message is not None
    assert json.loads(message["data"])["data"] == {"team_id": str(team_id)}
