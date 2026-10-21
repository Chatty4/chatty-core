from dataclasses import asdict
from datetime import timedelta

import pytest
from asgiref.sync import sync_to_async
from django.utils import timezone

from channels.models import Channel, ChannelMember
from channels.schemas import MembershipAction, MembershipChanged
from shared.events import EventType
from teams.models import TeamMember
from teams.services import TeamService
from users.models import User

pytestmark = pytest.mark.django_db(transaction=True)

OWNER, MEMBER = ChannelMember.Role.OWNER, ChannelMember.Role.MEMBER


async def make_user(email: str) -> User:
    return await sync_to_async(User.objects.create_user)(
        email=email, display_name="Ana Pop", password="correct horse battery"
    )


@pytest.fixture
async def setup():
    """Olga owns the team. Ana owns private #secret; Bob joined it before Carl."""
    names = ("olga", "ana", "bob", "carl")
    olga, ana, bob, carl = [await make_user(f"{n}@example.com") for n in names]
    team = await TeamService.create("Backend", olga.id)
    for user in (ana, bob, carl):
        await TeamMember.objects.acreate(team_id=team.id, user=user, role=TeamMember.Role.MEMBER)
    secret = await Channel.objects.acreate(
        team_id=team.id, name="secret", kind=Channel.Kind.PRIVATE
    )
    for hours, (user, role) in enumerate([(ana, OWNER), (bob, MEMBER), (carl, MEMBER)]):
        member = await ChannelMember.objects.acreate(
            channel=secret, user=user, role=role, notify_level=ChannelMember.NotifyLevel.ALL
        )
        await ChannelMember.objects.filter(pk=member.pk).aupdate(
            joined_at=timezone.now() + timedelta(hours=hours)
        )
    return team, secret, {"olga": olga, "ana": ana, "bob": bob, "carl": carl}


async def role_in(channel: Channel, user: User) -> str | None:
    member = await ChannelMember.objects.filter(channel=channel, user=user).afirst()
    return member.role if member else None


async def test_leaving_team_hands_private_channel_to_first_joined(setup):
    team, secret, u = setup

    await TeamService.leave(team.id, u["ana"].id)

    assert await role_in(secret, u["ana"]) is None
    assert await role_in(secret, u["bob"]) == OWNER
    assert await role_in(secret, u["carl"]) == MEMBER


async def test_removed_from_team_hands_private_channel_to_first_joined(setup):
    team, secret, u = setup

    await TeamService.remove_member(team.id, u["olga"].id, u["ana"].id)

    assert await role_in(secret, u["ana"]) is None
    assert await role_in(secret, u["bob"]) == OWNER


async def test_no_hand_off_when_another_owner_stays(setup):
    team, secret, u = setup
    await ChannelMember.objects.filter(channel=secret, user=u["carl"]).aupdate(role=OWNER)

    await TeamService.leave(team.id, u["ana"].id)

    assert await role_in(secret, u["bob"]) == MEMBER
    assert await role_in(secret, u["carl"]) == OWNER


async def test_leaving_empty_private_channel_is_fine(setup):
    team, _, u = setup
    alone = await Channel.objects.acreate(team_id=team.id, name="alone", kind=Channel.Kind.PRIVATE)
    await ChannelMember.objects.acreate(
        channel=alone, user=u["ana"], role=OWNER, notify_level=ChannelMember.NotifyLevel.ALL
    )

    await TeamService.leave(team.id, u["ana"].id)

    assert not await ChannelMember.objects.filter(channel=alone).aexists()


async def test_leaving_team_publishes_hand_off(setup, published):
    team, secret, u = setup

    await TeamService.leave(team.id, u["ana"].id)

    memberships = [d for t, d in published if t == EventType.MEMBERSHIP_CHANGED]
    assert memberships == [
        asdict(MembershipChanged(u["bob"].id, secret.id, team.id, MembershipAction.SETTINGS))
    ]
