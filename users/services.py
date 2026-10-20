from uuid import UUID

from asgiref.sync import sync_to_async
from django.contrib.auth.hashers import make_password
from django.db import IntegrityError, transaction

from authn.schemas import TokenPairSchema
from authn.services import AuthnService
from shared.codes import ErrorCode
from shared.exceptions import BadRequest, Conflict, RateLimited, Unauthorized, UserInactive
from shared.redis import clear_rate_limit, rate_limit, undo_rate_limit
from teams.services import InviteService, TeamService
from users.models import User
from users.repositories import UserRepository
from users.schemas import Me

REGISTER_LIMIT = 10
REGISTER_WINDOW = 60 * 60

LOGIN_FAIL_LIMIT = 5
LOGIN_FAIL_WINDOW = 15 * 60

CHANGE_PW_FAIL_LIMIT = 5
CHANGE_PW_FAIL_WINDOW = 15 * 60


class UserService:
    @staticmethod
    async def register(email: str, display_name: str, password: str, ip: str) -> User:
        retry_after = await rate_limit(f"register:{ip}", REGISTER_LIMIT, REGISTER_WINDOW)
        if retry_after:
            raise RateLimited(retry_after)

        if await UserRepository.email_exists(email):
            raise Conflict(ErrorCode.EMAIL_TAKEN)

        try:
            return await UserRepository.create_user(email, display_name, password)
        except IntegrityError:  # two requests with the same email at the same time
            raise Conflict(ErrorCode.EMAIL_TAKEN)

    @staticmethod
    async def login(email: str, password: str, ip: str) -> tuple[TokenPairSchema, User]:
        fail_keys = (f"login_fail:{email}", f"login_fail:{ip}")
        user = await UserRepository.get_by_email(email)

        # Count the attempt before any hash work, so requests over the limit (parallel ones
        # included) are rejected without hashing.
        retry_after = 0
        for key in fail_keys:
            retry_after = retry_after or await rate_limit(key, LOGIN_FAIL_LIMIT, LOGIN_FAIL_WINDOW)
        if retry_after:
            raise RateLimited(retry_after, ErrorCode.TOO_MANY_ATTEMPTS)
        # Unknown email: spend ~1.2 s on a dummy hash to prevent timing-based
        # account enumeration
        if user is None:
            await sync_to_async(User().set_password, thread_sensitive=False)(password)
        elif not user.is_active:
            # Only a correct password may reveal that the account is deactivated
            if await user.acheck_password(password):
                raise UserInactive()
        elif await user.acheck_password(password):
            await clear_rate_limit(f"login_fail:{email}")
            await undo_rate_limit(f"login_fail:{ip}")
            tokens = await AuthnService().issue_tokens(user)
            return tokens, user

        raise Unauthorized(ErrorCode.INVALID_CREDENTIALS)

    @staticmethod
    async def refresh_token(refresh_token: str) -> TokenPairSchema:
        return await AuthnService().refresh_tokens(refresh_token)

    @staticmethod
    async def logout(refresh_token: str, user_id: UUID) -> None:
        await AuthnService().revoke_refresh_token(refresh_token, str(user_id))

    @staticmethod
    async def deactivate(user_ids: list[UUID]) -> list[UUID]:
        """no user.deactivated event yet. CHAT-172 publishes it here with transaction.on_commit"""
        deactivated = await UserRepository.deactivate_user(user_ids)
        # All selected ids, not only the newly deactivated, so users deactivated
        # before these fixes also lose their leftover sessions and hand off their teams
        for user_id in user_ids:
            await AuthnService().revoke_all_tokens(str(user_id))
            await TeamService.hand_off_ownership(user_id)
            await InviteService.revoke_all_created_by(user_id)
        return deactivated

    @staticmethod
    async def get_me(user: User) -> Me:
        return Me(user, await TeamService.list_for_user(user.id))

    @staticmethod
    async def update_profile(
        user: User, display_name: str, timezone: str, avatar_file_id: UUID | None
    ) -> Me:
        user = await UserRepository.update_profile(user, display_name, timezone, avatar_file_id)
        return await UserService.get_me(user)

    @staticmethod
    @transaction.atomic
    def _revoke_and_set_password_sync(user: User, hashed: str, keep_raw_token: str) -> None:
        AuthnService().revoke_all_tokens_sync(str(user.id), keep_raw_token)
        UserRepository.set_password_sync(user, hashed)

    @staticmethod
    async def change_password(
        user: User, old_password: str, new_password: str, refresh_token: str
    ) -> None:
        key = f"change_pw_fail:{user.id}"
        retry_after = await rate_limit(key, CHANGE_PW_FAIL_LIMIT, CHANGE_PW_FAIL_WINDOW)
        if retry_after:
            raise RateLimited(retry_after)

        if not await user.acheck_password(old_password):
            raise BadRequest(ErrorCode.WRONG_PASSWORD)

        await clear_rate_limit(key)
        await AuthnService().check_own_refresh_token(refresh_token, str(user.id))
        hashed = await sync_to_async(make_password, thread_sensitive=False)(new_password)
        await sync_to_async(UserService._revoke_and_set_password_sync)(user, hashed, refresh_token)
