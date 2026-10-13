from uuid import UUID

from asgiref.sync import sync_to_async
from django.contrib.auth.hashers import make_password

from users.models import User


class UserRepository:
    @staticmethod
    async def email_exists(email: str) -> bool:
        return await User.objects.filter(email=email).aexists()

    @staticmethod
    async def create_user(email: str, display_name: str, password: str) -> User:
        hashed = await sync_to_async(make_password, thread_sensitive=False)(password)
        return await User.objects.acreate(
            email=email,
            display_name=display_name,
            password=hashed,
        )

    @staticmethod
    async def get_by_email(email: str) -> User | None:
        return await User.objects.filter(email=email).afirst()

    @staticmethod
    def get_by_id_sync(user_id: UUID) -> User | None:
        return User.objects.filter(id=user_id).first()

    @staticmethod
    async def deactivate_user(user_ids: list[UUID]) -> list[UUID]:
        """Deactivate the active users among user_ids and return their ids."""
        active = User.objects.filter(id__in=user_ids, is_active=True)
        ids = [user_id async for user_id in active.values_list("id", flat=True)]
        await User.objects.filter(id__in=ids).aupdate(is_active=False)

        return ids

    @staticmethod
    async def update_profile(
        user: User, display_name: str, timezone: str, avatar_id: UUID | None
    ) -> User:
        user.display_name = display_name
        user.timezone = timezone
        user.avatar_id = avatar_id
        await user.asave(update_fields=["display_name", "timezone", "avatar_id"])

        return user

    @staticmethod
    async def set_password(user: User, password: str) -> None:
        await sync_to_async(user.set_password, thread_sensitive=False)(password)
        await user.asave(update_fields=["password"])
