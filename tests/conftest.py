import pytest
from asgiref.sync import sync_to_async
from django.db import connections


@pytest.fixture(autouse=True)
async def close_thread_db_connections():
    # Code wrapped in sync_to_async opens its own DB connection in a worker thread. The test
    # client never closes it, and an open connection stops pytest from dropping the test database.
    yield
    await sync_to_async(connections.close_all)()
