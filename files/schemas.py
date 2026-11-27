from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from files.models import File


@dataclass
class UploadResult:
    file_id: UUID
    upload_url: str
    upload_method: str
    upload_headers: dict[str, str]
    expires_at: datetime


@dataclass
class FileCopy:
    """A new file that copy makes from source; its row is saved after the object is copied."""

    source: File
    file_id: UUID
    object_key: str
