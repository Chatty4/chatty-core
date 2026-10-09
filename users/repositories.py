from uuid import UUID

from asgiref.sync import sync_to_async

from users.models import User


class UserRepository:
    @staticmethod
    async def email_exists(email: str) -> bool:
        return await User.objects.filter(email=email).aexists()

    @staticmethod
    async def create_user(email: str, display_name: str, password: str) -> User:
        # create_user is sync (save + password hashing), so it runs in the sync thread
        return await sync_to_async(User.objects.create_user)(email, display_name, password)

    @staticmethod
    async def deactivate_user(user_ids: list[UUID]) -> list[UUID]:
        """Deactivate the active users among user_ids and return their ids."""
        active = User.objects.filter(id__in=user_ids, is_active=True)
        ids = [user_id async for user_id in active.values_list("id", flat=True)]
        await User.objects.filter(id__in=ids).aupdate(is_active=False)

        return ids
