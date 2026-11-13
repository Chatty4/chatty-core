import math
import uuid
from datetime import datetime, timedelta
from pathlib import PurePath
from uuid import UUID

from asgiref.sync import sync_to_async
from django.db import transaction
from django.utils import timezone

from files.models import File
from files.repositories import FileRepository
from files.schemas import UploadResult
from shared import storage
from shared.codes import ErrorCode
from shared.exceptions import BadRequest, RateLimited
from shared.redis import rate_limit
from teams.services import TeamService

UPLOAD_LIMIT = 30  # POST /files per user
UPLOAD_WINDOW = 60
MAX_PENDING_UPLOADS = 20  # started and not confirmed yet, per user

MB = 1024 * 1024
IMAGE_TYPES = {"image/png", "image/jpeg", "image/webp", "image/gif"}
MAX_IMAGE_SIZE = 2 * MB  # avatars and team icons
MAX_ATTACHMENT_SIZE = 25 * MB

# D-18: programs and installers, refused for every purpose. Confirm also checks the bytes.
BLOCKED_EXTENSIONS = {
    ".exe", ".dll", ".com", ".scr", ".cpl", ".msi", ".msp", ".msix", ".appx", ".bat", ".cmd",
    ".ps1", ".vbs", ".vbe", ".wsf", ".hta", ".lnk", ".jar", ".apk", ".dmg", ".pkg",
}  # fmt: skip
BLOCKED_TYPES = {
    "application/x-msdownload",
    "application/x-msdos-program",
    "application/x-dosexec",
    "application/vnd.microsoft.portable-executable",
    "application/x-msi",
    "application/x-ms-installer",
    "application/x-executable",
    "application/x-sharedlib",
    "application/x-mach-binary",
    "application/java-archive",
    "application/vnd.android.package-archive",
    "application/x-apple-diskimage",
}

_KEY_PREFIXES = {
    File.Purpose.AVATAR: "avatars",
    File.Purpose.TEAM_ICON: "team-icons",
    File.Purpose.ATTACHMENT: "attachments",
}


class FileService:
    @staticmethod
    async def create_upload(
        user_id: UUID, purpose: str, team_id: UUID | None, filename: str, mime: str, size: int
    ) -> UploadResult:
        """Step 1 of an upload: a pending file and a PUT URL for uploads/{file_id} (D-15).
        The serializer has already checked the shape and cleaned the filename."""
        retry_after = await rate_limit(f"files_upload:{user_id}", UPLOAD_LIMIT, UPLOAD_WINDOW)
        if retry_after:
            raise RateLimited(retry_after)

        FileService._check_type_and_size(purpose, filename, mime, size)
        if team_id is not None:
            await TeamService.require_member(team_id, user_id)

        # The id comes first: the final key contains it.
        file_id = uuid.uuid4()
        file = await sync_to_async(FileService._create_upload_sync)(
            file_id,
            owner_id=user_id,
            team_id=team_id,
            purpose=purpose,
            object_key=FileService._object_key(purpose, user_id, team_id, file_id),
            filename=filename,
            mime=mime,
            size=size,
            now=timezone.now(),
        )
        # After the commit: signing makes no network call, and needs no lock.
        return UploadResult(
            file_id=file.id,
            upload_url=storage.presign_put(f"uploads/{file.id}", mime, size),
            upload_method="PUT",
            upload_headers={"Content-Type": mime, "Content-Length": str(size)},
            expires_at=file.upload_expires_at,
        )

    @staticmethod
    def _check_type_and_size(purpose: str, filename: str, mime: str, size: int) -> None:
        if FileService._is_program(filename, mime):
            raise BadRequest(
                ErrorCode.TYPE_NOT_ALLOWED, "Programs and installers can't be uploaded"
            )
        if purpose == File.Purpose.ATTACHMENT:
            if size > MAX_ATTACHMENT_SIZE:
                raise BadRequest(
                    ErrorCode.FILE_TOO_LARGE,
                    f"Attachments can be at most {MAX_ATTACHMENT_SIZE // MB} MB",
                )
            return
        if mime not in IMAGE_TYPES:
            raise BadRequest(
                ErrorCode.TYPE_NOT_ALLOWED, f"Use one of: {', '.join(sorted(IMAGE_TYPES))}"
            )
        if size > MAX_IMAGE_SIZE:
            raise BadRequest(
                ErrorCode.FILE_TOO_LARGE, f"Images can be at most {MAX_IMAGE_SIZE // MB} MB"
            )

    @staticmethod
    def _is_program(filename: str, mime: str) -> bool:
        """D-18 by name and declared type. Windows ignores trailing dots and spaces in a name, so
        "setup.exe." still runs: they are dropped before the extension is read. Parameters such
        as "; charset=binary" are dropped from the type."""
        extension = PurePath(filename.rstrip(". ")).suffix.lower()
        declared = mime.split(";")[0].strip().lower()
        return extension in BLOCKED_EXTENSIONS or declared in BLOCKED_TYPES

    @staticmethod
    def _object_key(purpose: str, user_id: UUID, team_id: UUID | None, file_id: UUID) -> str:
        """The file's final key; confirm copies the upload there (D-15)."""
        owner = user_id if purpose == File.Purpose.AVATAR else team_id
        return f"{_KEY_PREFIXES[File.Purpose(purpose)]}/{owner}/{file_id}"

    @staticmethod
    @transaction.atomic
    def _create_upload_sync(
        file_id: UUID,
        *,
        owner_id: UUID,
        team_id: UUID | None,
        purpose: str,
        object_key: str,
        filename: str,
        mime: str,
        size: int,
        now: datetime,
    ) -> File:
        """Counts and inserts under the user's row lock, so the cap of open uploads is exact."""
        if FileRepository.count_pending_sync(owner_id, now) >= MAX_PENDING_UPLOADS:
            expiry = FileRepository.first_pending_expiry_sync(owner_id, now)
            assert expiry is not None  # the count above found open uploads
            raise RateLimited(max(1, math.ceil((expiry - now).total_seconds())))

        return FileRepository.create_sync(
            file_id,
            owner_id=owner_id,
            team_id=team_id,
            purpose=purpose,
            object_key=object_key,
            filename=filename,
            mime=mime,
            size=size,
            upload_expires_at=now + timedelta(seconds=storage.UPLOAD_URL_SECONDS),
        )
