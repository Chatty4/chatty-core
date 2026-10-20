from datetime import timedelta
from io import StringIO

import pytest
from asgiref.sync import sync_to_async
from django.core.management import call_command
from django.core.management.base import CommandError
from django.utils import timezone

from authn.models import RefreshToken
from users.models import User

pytestmark = pytest.mark.django_db(transaction=True)

EMAIL = "purge@example.com"
PASSWORD = "correct horse battery"


@pytest.fixture
async def user():
    return await sync_to_async(User.objects.create_user)(
        email=EMAIL, display_name="Purge Test", password=PASSWORD
    )


def make_token(user, *, expires_at, revoked_at=None):
    return RefreshToken.objects.create(
        user=user,
        token_hash="x" * 63 + str(RefreshToken.objects.count()),
        expires_at=expires_at,
        revoked_at=revoked_at,
    )


@pytest.fixture
def user_sync(db):
    return User.objects.create_user(email=EMAIL, display_name="Purge Test", password=PASSWORD)


def test_expired_token_older_than_cutoff_is_deleted(user_sync):
    old = timezone.now() - timedelta(days=40)
    token = make_token(user_sync, expires_at=old)

    call_command("purge_refresh_tokens", "--days=30")

    assert not RefreshToken.objects.filter(pk=token.pk).exists()


def test_rotated_token_not_expired_is_kept(user_sync):
    # Reuse detection needs rotated tokens until they expire, whatever --days says
    token = make_token(
        user_sync,
        expires_at=timezone.now() + timedelta(days=29),
        revoked_at=timezone.now() - timedelta(days=2),
    )

    call_command("purge_refresh_tokens", "--days=1")

    assert RefreshToken.objects.filter(pk=token.pk).exists()


def test_active_recent_token_is_kept(user_sync):
    token = make_token(user_sync, expires_at=timezone.now() + timedelta(days=10))

    call_command("purge_refresh_tokens", "--days=30")

    assert RefreshToken.objects.filter(pk=token.pk).exists()


def test_recently_expired_token_within_window_is_kept(user_sync):
    recent = timezone.now() - timedelta(days=5)
    token = make_token(user_sync, expires_at=recent)

    call_command("purge_refresh_tokens", "--days=30")

    assert RefreshToken.objects.filter(pk=token.pk).exists()


def test_dry_run_does_not_delete(user_sync):
    old = timezone.now() - timedelta(days=40)
    token = make_token(user_sync, expires_at=old)

    out = StringIO()
    call_command("purge_refresh_tokens", "--days=30", "--dry-run", stdout=out)

    assert RefreshToken.objects.filter(pk=token.pk).exists()
    assert "Would delete 1 rows" in out.getvalue()


def test_invalid_days_raises_command_error(user_sync):
    with pytest.raises(CommandError, match="--days must be >= 1"):
        call_command("purge_refresh_tokens", "--days=0")


def test_deleted_count_is_reported(user_sync):
    old = timezone.now() - timedelta(days=40)
    make_token(user_sync, expires_at=old)
    make_token(user_sync, expires_at=old)

    out = StringIO()
    call_command("purge_refresh_tokens", "--days=30", stdout=out)

    assert "Deleted 2 rows" in out.getvalue()
