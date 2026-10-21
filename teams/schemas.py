from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID


@dataclass
class TeamResult:
    id: UUID
    name: str
    icon_file_id: UUID | None
    role: str
    member_count: int
    created_at: datetime


@dataclass
class CreateTeamResult(TeamResult):
    general_channel_id: UUID


@dataclass
class TeamDetailResult:
    id: UUID
    name: str
    icon_file_id: UUID | None
    my_role: str
    member_count: int
    created_by: UUID | None
    created_at: datetime


@dataclass
class BaseInviteResult:
    id: UUID
    code: str
    url: str
    created_by: UUID | None
    max_uses: int
    uses: int
    expires_at: datetime | None
    created_at: datetime


@dataclass
class InviteResult(BaseInviteResult):
    team_id: UUID


@dataclass
class TeamPreview:
    name: str
    icon_url: str | None
    member_count: int


@dataclass
class InviteLookupResult:
    code: str
    valid: bool
    reason: str | None
    team: TeamPreview
    expires_at: datetime | None


@dataclass
class JoinTeamResult:
    team_id: UUID
    name: str
    role: str
    already_member: bool
    channel_ids: list[UUID]


@dataclass(frozen=True)
class TeamDeleted:
    """team.deleted data."""

    team_id: UUID


class TeamMemberAction(StrEnum):
    JOINED = "joined"
    LEFT = "left"
    REMOVED = "removed"
    ROLE_CHANGED = "role_changed"


@dataclass(frozen=True)
class TeamMemberChanged:
    """team.member.changed data. role is the role after the change, None when left or removed."""

    user_id: UUID
    team_id: UUID
    action: TeamMemberAction
    role: str | None
