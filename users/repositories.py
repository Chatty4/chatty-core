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
    async def get_by_email(email: str) -> User | None:
        return await User.objects.filter(email=email).afirst()
