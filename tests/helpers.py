"""Plain helpers shared by tests. Fixtures go in conftest.py; these are imported:

from tests.helpers import headers_for, make_user
"""

from datetime import timedelta

from asgiref.sync import sync_to_async
from django.conf import settings
from django.utils import timezone

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


async def age_rotated_tokens(user: User) -> None:
    """Move rotated tokens past the grace window, so a reuse counts as theft."""
    await RefreshToken.objects.filter(user=user, revoked_at__isnull=False).aupdate(
        revoked_at=timezone.now() - timedelta(seconds=settings.JWT_REFRESH_REUSE_GRACE + 1)
    )
