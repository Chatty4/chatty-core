from uuid import UUID

from django.db import IntegrityError

from shared.codes import ErrorCode
from shared.exceptions import Conflict, RateLimited
from shared.redis import rate_limit
from users.models import User
from users.repositories import UserRepository

REGISTER_LIMIT = 10
REGISTER_WINDOW = 60 * 60


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
    async def deactivate(user_ids: list[UUID]) -> list[UUID]:
        """no user.deactivated event yet. CHAT-172 publishes it here with transaction.on_commit"""
        return await UserRepository.deactivate_user(user_ids)
