from dataclasses import dataclass
from uuid import UUID

from channels.models import ChannelMember
from teams.schemas import TeamResult
from users.models import User


@dataclass
class Me:
    """My profile and my teams, for GET and PUT /me."""

    user: User
    teams: list[TeamResult]


@dataclass
class TeamMembership:
    team_id: UUID
    role: str
    public_channel_ids: list[UUID]


@dataclass
class Memberships:
    user_id: UUID
    is_active: bool
    teams: list[TeamMembership]
    channels: list[ChannelMember]


@dataclass(frozen=True)
class UserDeactivated:
    """user.deactivated data."""

    user_id: UUID
