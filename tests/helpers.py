"""Plain helpers shared by tests. Fixtures go in conftest.py; these are imported:

from tests.helpers import headers_for, make_user
"""

from asgiref.sync import sync_to_async

from authn.services import AuthnService
from users.models import User


async def make_user(email: str) -> User:
    return await sync_to_async(User.objects.create_user)(
        email=email, display_name="Ana Pop", password="correct horse battery"
    )


async def headers_for(user: User) -> dict:
    tokens = await AuthnService().issue_tokens(user)
    return {"Authorization": f"Bearer {tokens.access_token}"}
