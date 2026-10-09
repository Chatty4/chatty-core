from django.db import IntegrityError

from shared.codes import ErrorCode
from shared.exceptions import Conflict
from users.models import User
from users.repositories import UserRepository


class UserService:
    @staticmethod
    async def register(email: str, display_name: str, password: str) -> User:
        if await UserRepository.email_exists(email):
            raise Conflict(ErrorCode.EMAIL_TAKEN)

        try:
            return await UserRepository.create_user(email, display_name, password)
        except IntegrityError:  # two requests with the same email at the same time
            raise Conflict(ErrorCode.EMAIL_TAKEN)
