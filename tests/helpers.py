"""Plain helpers shared by tests. Fixtures go in conftest.py; these are imported:

from tests.helpers import headers_for, make_user
"""

import io
import urllib.error
import urllib.request
import zipfile
from datetime import timedelta
from urllib.parse import urlsplit

from asgiref.sync import sync_to_async
from django.conf import settings
from django.utils import timezone
from PIL import Image

from authn.models import RefreshToken
from authn.services import AuthnService
from users.models import User


async def make_user(email: str) -> User:
    return await sync_to_async(User.objects.create_user)(
        email=email, display_name="Ana Pop", password="correct horse battery"
    )


async def headers_for(user: User) -> dict:
    tokens = await AuthnService().issue_tokens(user)
    return {"Authorization": f"Bearer {tokens.access_token}"}


AVATAR_UPLOAD = {"purpose": "avatar", "filename": "me.png", "mime": "image/png", "size": 5}


async def post_file(client, headers: dict, **changes):
    """POST /files with AVATAR_UPLOAD, plus any changed fields (a None value drops the field)."""
    body = {k: v for k, v in (AVATAR_UPLOAD | changes).items() if v is not None}
    return await client.post(
        "/api/core/v1/files", body, content_type="application/json", headers=headers
    )


def put_upload(url: str, data: bytes, headers: dict) -> int:
    """PUT like the browser does; returns the status. The URL is signed for the public address
    (D-16), which in the core container is the container itself, so the request goes to MinIO's
    internal address with the signed address as Host: MinIO checks the signature against Host."""
    signed = urlsplit(url)
    internal = urlsplit(settings.MINIO_INTERNAL_URL)
    request = urllib.request.Request(
        signed._replace(scheme=internal.scheme, netloc=internal.netloc).geturl(),
        data=data,
        method="PUT",
        headers=headers | {"Host": signed.netloc},
    )
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status
    except urllib.error.HTTPError as e:
        return e.code


def image_bytes(fmt: str, size: tuple[int, int] = (64, 64)) -> bytes:
    """A real image of noise (so it doesn't compress to almost nothing), e.g. fmt="PNG"."""
    buffer = io.BytesIO()
    Image.effect_noise(size, 64).convert("RGB").save(buffer, fmt)
    return buffer.getvalue()


def zip_bytes() -> bytes:
    """A zip like a .docx: a document, not a program."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("word/document.xml", "<w:document/>")
    return buffer.getvalue()


# The first bytes of programs (D-18). WINDOWS: a DOS header whose last 4 bytes (at 0x3C) point to
# the "PE" header right after it, at 0x40.
WINDOWS = b"MZ" + b"\x00" * 58 + (0x40).to_bytes(4, "little") + b"PE\0\0" + b"\x00" * 64
ELF = b"\x7fELF\x02\x01\x01" + b"\x00" * 57
MACH_O = b"\xcf\xfa\xed\xfe" + b"\x00" * 28


async def age_rotated_tokens(user: User) -> None:
    """Move rotated tokens past the grace window, so a reuse counts as theft."""
    await RefreshToken.objects.filter(user=user, revoked_at__isnull=False).aupdate(
        revoked_at=timezone.now() - timedelta(seconds=settings.JWT_REFRESH_REUSE_GRACE + 1)
    )
