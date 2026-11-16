from uuid import UUID

from files.models import File


def can_use_as_avatar(file: File, user_id: UUID) -> bool:
    """A ready avatar I uploaded."""
    return _is_usable(file) and file.purpose == File.Purpose.AVATAR and file.owner_id == user_id


def can_use_as_team_icon(file: File, team_id: UUID) -> bool:
    """A ready team icon uploaded for this team."""
    return _is_usable(file) and file.purpose == File.Purpose.TEAM_ICON and file.team_id == team_id


def _is_usable(file: File) -> bool:
    return file.status == File.Status.READY and file.deleted_at is None
