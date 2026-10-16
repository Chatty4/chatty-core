from dataclasses import dataclass

from teams.schemas import TeamResult
from users.models import User


@dataclass
class Me:
    """My profile and my teams, for GET and PUT /me."""

    user: User
    teams: list[TeamResult]
