import pytest
from rest_framework.serializers import ValidationError

from shared.codes import ErrorCode
from shared.exceptions import BadRequest
from shared.pagination import PageQuery, paginate
from shared.serializers import validated
from teams.models import Team, TeamMember
from users.models import User

NAMES = ["ana", "ana", "ana", "bob", "dan"]
BY_NAME = ("display_name", "id")


async def make_users() -> None:
    for i, name in enumerate(NAMES):
        await User.objects.acreate(email=f"u{i}@example.com", display_name=name)


async def walk(qs, sort, limit=2) -> list:
    """Follow next_cursor until the last page and return every row seen."""
    seen, cursor = [], None
    while True:
        rows, cursor = await paginate(qs, sort, cursor, limit, "users")
        seen += rows
        if cursor is None:
            return seen


def test_limit_defaults_to_50():
    assert validated(PageQuery, {}) == {"limit": 50}


@pytest.mark.parametrize("limit", [0, 201, "abc"])
def test_limit_outside_1_to_200_is_rejected(limit):
    with pytest.raises(ValidationError) as caught:
        validated(PageQuery, {"limit": limit})

    assert "limit" in caught.value.detail


@pytest.mark.django_db(transaction=True)
async def test_last_page_has_no_next_cursor():
    await make_users()

    rows, cursor = await paginate(User.objects.all(), BY_NAME, None, 5, "users")

    assert len(rows) == 5
    assert cursor is None


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("sort", [BY_NAME, ("date_joined", "id")])
async def test_walking_every_page_returns_each_row_once_in_order(sort):
    # Repeated names exercise the tie-break on id; date_joined exercises microseconds.
    await make_users()

    seen = await walk(User.objects.all(), sort)

    assert [u.id for u in seen] == [u.id async for u in User.objects.order_by(*sort)]


@pytest.mark.django_db(transaction=True)
async def test_sort_can_follow_a_relation():
    await make_users()
    team = await Team.objects.acreate(name="t")
    async for user in User.objects.all():
        await TeamMember.objects.acreate(team=team, user=user)
    qs = TeamMember.objects.filter(team=team).select_related("user")
    sort = ("user__display_name", "user_id")

    seen = await walk(qs, sort)

    assert [m.user_id for m in seen] == [m.user_id async for m in qs.order_by(*sort)]


@pytest.mark.django_db(transaction=True)
async def test_empty_q_and_no_q_are_the_same_filter():
    await make_users()
    _, cursor = await paginate(User.objects.all(), BY_NAME, None, 2, "users", q="")

    rows, _ = await paginate(User.objects.all(), BY_NAME, cursor, 2, "users")

    assert [u.display_name for u in rows] == ["ana", "bob"]


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize(
    ("endpoint", "q", "sort", "change"),
    [
        ("other", None, BY_NAME, None),  # another endpoint
        ("users", "bo", BY_NAME, None),  # another q
        ("users", None, BY_NAME, lambda c: "x" + c),  # edited
        ("users", None, BY_NAME, lambda c: "garbage"),  # broken
        ("users", None, ("display_name", "date_joined", "id"), None),  # sort changed since
    ],
)
async def test_bad_cursor_raises_invalid_cursor(endpoint, q, sort, change):
    await make_users()
    _, cursor = await paginate(User.objects.all(), BY_NAME, None, 2, "users")
    if change:
        cursor = change(cursor)

    with pytest.raises(BadRequest) as caught:
        await paginate(User.objects.all(), sort, cursor, 2, endpoint, q)

    assert caught.value.code == ErrorCode.INVALID_CURSOR
