"""Cursor pagination from the contract (chatty-infra/docs/api-core.md, Pagination).

A repository builds the filtered queryset and hands it to paginate(), which sorts it, reads and
writes the cursor, and returns one page:

    qs = TeamMember.objects.filter(team_id=team_id).select_related("user")
    return await paginate(qs, ("user__display_name", "user_id"), cursor, limit, "team_members", q)

The view validates `limit` and `cursor` with PageQuery (or a subclass that adds `q`).
"""

from collections.abc import Sequence
from operator import attrgetter
from typing import Any

from django.core import signing
from django.db.models import Field, Func, Model, QuerySet, Value
from django.db.models.lookups import GreaterThan
from rest_framework import serializers

from shared.codes import ErrorCode
from shared.exceptions import BadRequest


class PageQuery(serializers.Serializer):
    """`limit` and `cursor` query params. Endpoints with a `q` filter subclass it."""

    limit = serializers.IntegerField(min_value=1, max_value=200, default=50)
    cursor = serializers.CharField(required=False)


def _row(*items: Any) -> Func:
    # A row mixes column types, so it gets a generic Field as its type.
    return Func(*items, function="ROW", output_field=Field())


async def paginate[T: Model](
    qs: QuerySet[T],
    sort: Sequence[str],
    cursor: str | None,
    limit: int,
    endpoint: str,
    q: str | None = None,
) -> tuple[list[T], str | None]:
    """One page of `qs` in ascending `sort` order, and the cursor of the next page or None.

    `sort` must end with a unique field (an id) so ties don't skip or repeat rows. Relations in
    `sort` ("user__display_name") need select_related on `qs`: the cursor reads them.
    """
    # The salt is part of the signature, so a cursor only works for its endpoint and q.
    salt = f"{endpoint}:{q or ''}"
    if cursor:
        try:
            key = signing.loads(cursor, salt=salt)
        except signing.BadSignature:
            raise BadRequest(ErrorCode.INVALID_CURSOR, "Invalid cursor") from None
        if len(key) != len(sort):  # cursor made before the endpoint changed its sort
            raise BadRequest(ErrorCode.INVALID_CURSOR, "Invalid cursor")
        # ROW(a, b) > ROW(x, y): Postgres compares column by column and can use an index on (a, b).
        qs = qs.filter(GreaterThan(_row(*sort), _row(*map(Value, key))))

    # One extra row only tells us that a next page exists; it isn't returned.
    rows = [row async for row in qs.order_by(*sort)[: limit + 1]]
    if len(rows) <= limit:
        return rows, None
    rows = rows[:limit]
    # str() keeps datetime microseconds; "user__display_name" reads rows[-1].user.display_name.
    last = [str(attrgetter(field.replace("__", "."))(rows[-1])) for field in sort]
    return rows, signing.dumps(last, salt=salt)
