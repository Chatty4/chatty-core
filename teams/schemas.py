from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass
class CreateTeamResult:
    id: UUID
    name: str
    icon_file_id: UUID | None
    role: str
    member_count: int
    general_channel_id: UUID
    created_at: datetime


@dataclass
class TeamResult:
    id: UUID
    name: str
    icon_file_id: UUID | None
    role: str
    member_count: int
    created_at: datetime
