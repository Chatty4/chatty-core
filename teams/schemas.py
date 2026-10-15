from dataclasses import dataclass
from datetime import datetime
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
