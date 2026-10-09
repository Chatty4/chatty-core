from asgiref.sync import sync_to_async
from uuid import UUID

from django.db import IntegrityError

from authn.schemas import TokenPairSchema
from authn.services import AuthnService
from shared.codes import ErrorCode
from shared.exceptions import Conflict, RateLimited, Unauthorized, UserInactive
from shared.redis import is_rate_limited, rate_limit
from users.models import User
from users.repositories import UserRepository

REGISTER_LIMIT = 10
REGISTER_WINDOW = 60 * 60

LOGIN_FAIL_LIMIT = 5
LOGIN_FAIL_WINDOW = 15 * 60


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
    async def login(email: str, password: str, ip: str) -> TokenPairSchema:
        for key in (f"login_fail:{email}", f"login_fail:{ip}"):
            retry_after = await is_rate_limited(key, LOGIN_FAIL_LIMIT)
            if retry_after:
                raise RateLimited(retry_after)

        user = await UserRepository.get_by_email(email)
        valid = user is not None and await sync_to_async(user.check_password)(password)

        if not valid:
            retry_after = 0
            for key in (f"login_fail:{email}", f"login_fail:{ip}"):
                retry_after = retry_after or await rate_limit(
                    key, LOGIN_FAIL_LIMIT, LOGIN_FAIL_WINDOW
                )
            if retry_after:
                raise RateLimited(retry_after)
            raise Unauthorized(ErrorCode.INVALID_CREDENTIALS)

        if not user.is_active:
            raise UserInactive()

        return await AuthnService().issue_tokens(user)

    @staticmethod
    async def deactivate(user_ids: list[UUID]) -> list[UUID]:
        """no user.deactivated event yet. CHAT-172 publishes it here with transaction.on_commit"""
        return await UserRepository.deactivate_user(user_ids)
