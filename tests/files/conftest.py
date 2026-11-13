import pytest

from shared.redis import get_redis_client
from teams.models import Team, TeamMember
from tests.helpers import headers_for, make_user


@pytest.fixture(autouse=True)
async def redis_client():
    # POST /files checks a rate limit; each test has its own event loop, so the cached client
    # must not outlive the test
    get_redis_client.cache_clear()
    yield
    await get_redis_client().aclose()
    get_redis_client.cache_clear()


@pytest.fixture
async def user():
    return await make_user("ana@example.com")


@pytest.fixture
async def auth(user):
    return await headers_for(user)


@pytest.fixture
async def team(user):
    team = await Team.objects.acreate(name="Backend", created_by=user)
    await TeamMember.objects.acreate(team=team, user=user, role=TeamMember.Role.OWNER)
    return team
