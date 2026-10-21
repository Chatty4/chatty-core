"""End to end: a real change in chatty-core reaches a subscriber on the real Redis."""

import json

import pytest

from channels.models import Channel
from channels.services import ChannelService
from shared.events import CHANNEL
from shared.events import publish as real_publish
from shared.redis import get_redis_client
from teams.models import TeamMember
from teams.services import TeamService
from tests.helpers import make_user

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture
async def real_redis(monkeypatch):
    # undo the autouse `published` recorder for this test only, so events really go to Redis
    monkeypatch.setattr("shared.events.publish", real_publish)
    # each test has its own event loop, so the cached client must not outlive the test
    get_redis_client.cache_clear()
    yield get_redis_client()
    await get_redis_client().aclose()
    get_redis_client.cache_clear()


async def test_channel_join_reaches_a_redis_subscriber(real_redis):
    ana, bob = await make_user("ana@example.com"), await make_user("bob@example.com")
    team = await TeamService.create("A", ana.id)
    await TeamMember.objects.acreate(team_id=team.id, user=bob, role=TeamMember.Role.MEMBER)
    random = await Channel.objects.acreate(team_id=team.id, name="random", kind=Channel.Kind.PUBLIC)
    pubsub = real_redis.pubsub()
    await pubsub.subscribe(CHANNEL)
    await pubsub.get_message(timeout=1)  # the subscribe confirmation

    await ChannelService.join(random.id, bob.id)

    message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=2)
    await pubsub.aclose()
    assert message is not None
    event = json.loads(message["data"])
    assert event["type"] == "membership.changed"
    assert event["data"] == {
        "user_id": str(bob.id),
        "channel_id": str(random.id),
        "team_id": str(team.id),
        "action": "added",
    }
