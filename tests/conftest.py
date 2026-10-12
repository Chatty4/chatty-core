import pytest
from asgiref.sync import sync_to_async
from django.db import connections


@pytest.fixture(autouse=True)
async def close_thread_db_connections():
    # Code wrapped in sync_to_async opens its own DB connection in a worker thread. The test
    # client never closes it, and an open connection stops pytest from dropping the test database.
    yield
    await sync_to_async(connections.close_all)()


@pytest.fixture(autouse=True)
def fast_password_hasher(settings):
    # Django's default PBKDF2 takes ~1s per hash; tests don't need real hashing strength.
    settings.PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
