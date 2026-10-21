from dataclasses import asdict
from uuid import UUID

from asgiref.sync import sync_to_async
from django.contrib.auth.hashers import make_password
from django.db import IntegrityError, transaction

from authn.schemas import TokenPairSchema
from authn.services import AuthnService
from channels.repositories import ChannelMemberRepository, ChannelRepository
from shared import events
from shared.codes import ErrorCode
from shared.events import EventType
from shared.exceptions import (
    BadRequest,
    Conflict,
    NotFound,
    RateLimited,
    Unauthorized,
    UserInactive,
)
from shared.redis import clear_rate_limit, rate_limit, undo_rate_limit
from teams.repositories import TeamMemberRepository
from teams.services import InviteService, TeamService
from users.models import User
from users.repositories import UserRepository
from users.schemas import Me, Memberships, TeamMembership, UserDeactivated

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
    async def get_me(user: User) -> Me:
        return Me(user, await TeamService.list_for_user(user.id))

    @staticmethod
    async def get_memberships(user_id: UUID) -> Memberships:
        """
        Teams and channels for chatty-chat's access checks.
        A deactivated user is returned too, with is_active False.
        """
        user = await sync_to_async(UserRepository.get_by_id_sync)(user_id)
        if user is None:
            raise NotFound(ErrorCode.USER_NOT_FOUND)

        team_members = await TeamMemberRepository.list_for_user(user_id)
        team_ids = [m.team_id for m in team_members]  # type: ignore[attr-defined]
        public_ids = await ChannelRepository.list_public_ids_by_team(team_ids)
        channels = await ChannelMemberRepository.list_for_user_in_teams(team_ids, user_id)

        return Memberships(
            user_id=user.id,
            is_active=user.is_active,
            teams=[
                TeamMembership(m.team_id, m.role, public_ids[m.team_id])  # type: ignore[attr-defined]
                for m in team_members
            ],
            channels=channels,
        )

    @staticmethod
    async def update_profile(
        user: User, display_name: str, timezone: str, avatar_file_id: UUID | None
    ) -> Me:
        user = await UserRepository.update_profile(user, display_name, timezone, avatar_file_id)
        return await UserService.get_me(user)

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
        hashed = await sync_to_async(make_password, thread_sensitive=False)(new_password)
        await sync_to_async(UserService._revoke_and_set_password_sync)(user, hashed, refresh_token)

    @staticmethod
    @transaction.atomic
    def _revoke_and_set_password_sync(user: User, hashed: str, keep_raw_token: str) -> None:
        """The kept token is checked and locked first, so this device can't rotate it while its
        other tokens are deleted."""
        AuthnService().check_own_refresh_token_sync(keep_raw_token, str(user.id))
        AuthnService().revoke_all_tokens_sync(str(user.id), keep_raw_token)
        UserRepository.set_password_sync(user, hashed)

    @staticmethod
    async def deactivate(user_ids: list[UUID]) -> list[UUID]:
        """Deactivate the users and return the ones that were active. Publishes user.deactivated
        for each of those once their sessions, team ownership and invites are cleaned up."""
        deactivated = await UserRepository.deactivate_user(user_ids)
        # All selected ids, not only the newly deactivated, so users deactivated
        # before these fixes also lose their leftover sessions and hand off their teams
        for user_id in user_ids:
            await AuthnService().revoke_all_tokens(str(user_id))
            await TeamService.hand_off_ownership(user_id)
            await InviteService.revoke_all_created_by(user_id)
        for user_id in deactivated:
            await events.publish(EventType.USER_DEACTIVATED, asdict(UserDeactivated(user_id)))
        return deactivated

    @staticmethod
    async def login(email: str, password: str, ip: str) -> tuple[TokenPairSchema, User]:
        # Email + IP, not email alone: wrong guesses from one IP can't lock the real user out
        pair_key, ip_key = f"login_fail:{email}:{ip}", f"login_fail:{ip}"
        user = await UserRepository.get_by_email(email)

        # Count the attempt before any hash work, so requests over the limit (parallel ones
        # included) are rejected without hashing.
        retry_after = 0
        for key in (pair_key, ip_key):
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
            await clear_rate_limit(pair_key)
            await undo_rate_limit(ip_key)
            tokens = await AuthnService().issue_tokens(user)
            return tokens, user

        raise Unauthorized(ErrorCode.INVALID_CREDENTIALS)

    @staticmethod
    async def refresh_token(refresh_token: str) -> TokenPairSchema:
        return await AuthnService().refresh_tokens(refresh_token)

    @staticmethod
    async def logout(refresh_token: str, user_id: UUID) -> None:
        await AuthnService().revoke_refresh_token(refresh_token, str(user_id))
