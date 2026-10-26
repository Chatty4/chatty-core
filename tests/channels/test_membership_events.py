from dataclasses import asdict

import pytest

from channels.schemas import MembershipAction, MembershipChanged
from channels.services import ChannelService
from shared.events import EventType
from shared.exceptions import AppError
from teams.models import TeamMember
from teams.services import TeamService
from tests.helpers import make_user

pytestmark = pytest.mark.django_db(transaction=True)

ADDED, REMOVED, SETTINGS = MembershipAction


def mc(user, channel_id, team_id, action):
    return (
        EventType.MEMBERSHIP_CHANGED,
        asdict(MembershipChanged(user.id, channel_id, team_id, action)),
    )


@pytest.fixture
async def world(published):
    """Ana owns the team, Bob and Carl are members."""
    ana, bob, carl = [await make_user(f"{n}@example.com") for n in ("ana", "bob", "carl")]
    team = await TeamService.create("A", ana.id)
    for user in (bob, carl):
        await TeamMember.objects.acreate(team_id=team.id, user=user, role=TeamMember.Role.MEMBER)
    published.clear()  # tests check only the events of the action under test
    return {"ana": ana, "bob": bob, "carl": carl, "team": team}


async def test_create_channel(world, published):
    channel = await ChannelService.create(world["team"].id, world["ana"].id, "random", "public", "")

    assert published == [mc(world["ana"], channel.id, world["team"].id, ADDED)]


async def test_create_with_taken_name_publishes_nothing(world, published):
    with pytest.raises(AppError):
        await ChannelService.create(world["team"].id, world["ana"].id, "general", "public", "")

    assert published == []


async def test_join_publishes_only_when_new(world, published):
    random = await ChannelService.create(world["team"].id, world["ana"].id, "random", "public", "")
    published.clear()

    await ChannelService.join(random.id, world["bob"].id)
    await ChannelService.join(random.id, world["bob"].id)

    assert published == [mc(world["bob"], random.id, world["team"].id, ADDED)]


async def test_leave_public_channel(world, published):
    random = await ChannelService.create(world["team"].id, world["ana"].id, "random", "public", "")
    await ChannelService.join(random.id, world["bob"].id)
    published.clear()

    await ChannelService.leave(random.id, world["bob"].id)

    assert published == [mc(world["bob"], random.id, world["team"].id, REMOVED)]


async def test_last_owner_leaving_private_channel_publishes_hand_off(world, published):
    t, ana, bob = world["team"].id, world["ana"], world["bob"]
    secret = await ChannelService.create(t, ana.id, "secret", "private", "")
    await ChannelService.add_members(secret.id, ana.id, [bob.id])
    published.clear()

    await ChannelService.leave(secret.id, ana.id)

    assert published == [mc(ana, secret.id, t, REMOVED), mc(bob, secret.id, t, SETTINGS)]


async def test_remove_member(world, published):
    t, ana, bob = world["team"].id, world["ana"], world["bob"]
    secret = await ChannelService.create(t, ana.id, "secret", "private", "")
    await ChannelService.add_members(secret.id, ana.id, [bob.id])
    published.clear()

    await ChannelService.remove_member(secret.id, ana.id, bob.id)

    assert published == [mc(bob, secret.id, t, REMOVED)]


async def test_leave_team_publishes_removed_for_every_channel(world, published):
    t, ana, bob = world["team"].id, world["ana"], world["bob"]
    general = world["team"].general_channel_id
    secret = await ChannelService.create(t, ana.id, "secret", "private", "")
    await ChannelService.join(general, bob.id)
    await ChannelService.add_members(secret.id, ana.id, [bob.id])
    dm = await ChannelService.open_dm(t, ana.id, [bob.id])
    published.clear()

    await TeamService.leave(t, bob.id)

    memberships = [e for e in published if e[0] == EventType.MEMBERSHIP_CHANGED]
    channel_ids = sorted([general, secret.id, dm.channel.id])
    assert memberships == [mc(bob, channel_id, t, REMOVED) for channel_id in channel_ids]


async def test_remove_from_team_publishes_removed_for_every_channel(world, published):
    t, ana, bob = world["team"].id, world["ana"], world["bob"]
    general = world["team"].general_channel_id
    secret = await ChannelService.create(t, ana.id, "secret", "private", "")
    await ChannelService.join(general, bob.id)
    await ChannelService.add_members(secret.id, ana.id, [bob.id])
    published.clear()

    await TeamService.remove_member(t, ana.id, bob.id)

    memberships = [e for e in published if e[0] == EventType.MEMBERSHIP_CHANGED]
    channel_ids = sorted([general, secret.id])
    assert memberships == [mc(bob, channel_id, t, REMOVED) for channel_id in channel_ids]


async def test_add_members_publishes_only_new_ones(world, published):
    t, ana, bob, carl = world["team"].id, world["ana"], world["bob"], world["carl"]
    secret = await ChannelService.create(t, ana.id, "secret", "private", "")
    await ChannelService.add_members(secret.id, ana.id, [bob.id])
    published.clear()

    await ChannelService.add_members(secret.id, ana.id, [bob.id, carl.id])

    assert published == [mc(carl, secret.id, t, ADDED)]


async def test_update_my_settings(world, published):
    t, ana = world["team"].id, world["ana"]
    general = world["team"].general_channel_id

    await ChannelService.update_my_settings(general, ana.id, "all", True, False)

    assert published == [mc(ana, general, t, SETTINGS)]


async def test_open_new_dm_publishes_for_every_member(world, published):
    t, ana, bob = world["team"].id, world["ana"], world["bob"]

    dm = await ChannelService.open_dm(t, ana.id, [bob.id])

    assert published == [mc(ana, dm.channel.id, t, ADDED), mc(bob, dm.channel.id, t, ADDED)]


async def test_reopen_dm_publishes_only_members_added_back(world, published):
    t, ana, bob = world["team"].id, world["ana"], world["bob"]
    dm = await ChannelService.open_dm(t, ana.id, [bob.id])
    await TeamService.leave(t, bob.id)
    await TeamMember.objects.acreate(team_id=t, user=bob, role=TeamMember.Role.MEMBER)
    published.clear()

    await ChannelService.open_dm(t, ana.id, [bob.id])
    await ChannelService.open_dm(t, ana.id, [bob.id])

    assert published == [mc(bob, dm.channel.id, t, ADDED)]
