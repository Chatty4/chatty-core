import pytest
from asgiref.sync import sync_to_async

from authn.models import RefreshToken
from authn.services import AuthnService
from shared.exceptions import Unauthorized
from users.models import User

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture
async def user():
    return await sync_to_async(User.objects.create_user)(
        email="ana@example.com", display_name="Ana Pop", password="correct horse battery"
    )


async def test_other_device_refresh_after_password_change_keeps_this_device(user):
    service = AuthnService()
    this_device = await service.issue_tokens(user)
    other_device = await service.issue_tokens(user)

    await service.revoke_all_tokens(str(user.id), keep_raw_token=this_device.refresh_token)

    with pytest.raises(Unauthorized):
        await service.refresh_tokens(other_device.refresh_token)
    assert (await service.refresh_tokens(this_device.refresh_token)).refresh_token


async def test_replaying_logged_out_token_keeps_other_sessions(user):
    service = AuthnService()
    logged_out = await service.issue_tokens(user)
    other = await service.issue_tokens(user)

    await service.revoke_refresh_token(logged_out.refresh_token, str(user.id))

    with pytest.raises(Unauthorized):
        await service.refresh_tokens(logged_out.refresh_token)
    assert (await service.refresh_tokens(other.refresh_token)).refresh_token


async def test_reusing_rotated_token_deletes_every_session(user):
    service = AuthnService()
    stolen = await service.issue_tokens(user)
    other = await service.issue_tokens(user)
    await service.refresh_tokens(stolen.refresh_token)

    with pytest.raises(Unauthorized):
        await service.refresh_tokens(stolen.refresh_token)

    assert not await RefreshToken.objects.filter(user=user).aexists()
    with pytest.raises(Unauthorized):
        await service.refresh_tokens(other.refresh_token)


async def test_logout_with_rotated_token_is_a_no_op(user):
    service = AuthnService()
    tokens = await service.issue_tokens(user)
    await service.refresh_tokens(tokens.refresh_token)

    await service.revoke_refresh_token(tokens.refresh_token, str(user.id))

    assert await RefreshToken.objects.filter(user=user).acount() == 2
