from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass
class UploadResult:
    file_id: UUID
    upload_url: str
    upload_method: str
    upload_headers: dict[str, str]
    expires_at: datetime
