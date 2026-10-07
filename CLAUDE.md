# chatty-core

Django + DRF service for Chatty: users, auth (JWT), teams, invites, channels, memberships and file uploads.
Public API at `/api/core/v1`, internal API for chatty-chat at `/internal`, health at `/health`.

Stack: Python 3.14, Django 6.1, DRF (async views via `shared.views.AsyncAPIView`), Postgres 17 (psycopg 3 + pool), Redis, MinIO, uvicorn (ASGI).

## Sources of truth

Contracts live in `../chatty-infra/docs`, not in this repo:
- `api-core.md`: public endpoints, error body, pagination
- `api-internal.md`: `/internal` endpoints and `X-Service-Token` auth
- `core-events.md` and `events.md`: Redis events we publish
- `decisions.md`: agreements with chatty-chat (D-01 ... D-08)

Implement exactly what the contract says. If an API, event or decision has to change, update the doc in a
chatty-infra PR first and link it from the chatty-core PR.

## Commands

```bash
docker compose -f ../chatty-infra/docker-compose.yml up -d    # Postgres, Redis, MinIO, Kafka
uvicorn config.asgi:application --reload                      # run (ASGI, not runserver)
pytest                                                        # tests
ruff check . && ruff format --check .                         # lint and format check
python manage.py makemigrations && python manage.py migrate   # migrations
```

## Project layout

Flat domain apps next to `config/`. Every domain app has the same layers:

```
config/                 settings.py (single file, driven by .env), urls.py, asgi.py, views.py (/health)
shared/                 code used by more than one app, no business rules
  views.py              AsyncAPIView: base class for every API view
  serializers.py        validated(): run a serializer and return validated_data
  exceptions.py         domain exceptions (NotFound, PermissionDenied, Conflict, ValidationFailed, ...)
  exception_handler.py  maps domain + DRF exceptions to the contract error body
  authentication.py     JWT (public API) and X-Service-Token (internal API)
  permissions.py
  pagination.py         cursor pagination from api-core.md
  events.py             Redis publisher for core.events (D-06, D-08)
  storage.py            MinIO client and presigned URLs
<app>/                  users, teams, channels, files, ...
  models.py             tables only: fields, constraints, indexes. No business logic
  repositories.py       the only place that queries the ORM
  services.py           business rules, transactions, events. No DRF, no request objects
  serializers.py        request validation and response shapes
  views.py              public API endpoints (thin)
  urls.py
  internal/             /internal endpoints for chatty-chat
    views.py
    serializers.py
    urls.py
  migrations/
tests/<app>/            test_services.py, test_views.py, test_internal.py, ...
```

Start each layer as one module. Turn it into a package (`services/__init__.py`, `services/invites.py`, ...)
when it grows past roughly 300 lines.

## Layers and dependency rule

Calls go one way only: `views -> services -> repositories -> models`.

- **views**: authenticate, validate input with a serializer, call one service function, serialize the result.
  No ORM, no business rules, no `if user.role == ...`.
- **serializers**: shape only (types, lengths, required fields). No DB queries inside validators;
  checks that need the DB ("name already taken") belong in services. Output serializers read objects
  that are already loaded; never trigger lazy queries from `.data`.
- **services**: plain Python functions that take ids/values and return models or dataclasses.
  They own permissions that depend on data (roles, membership), transactions and event publishing.
  They raise exceptions from `shared/exceptions.py`, never DRF exceptions or HTTP responses.
- **repositories**: small, named query functions (`get_team_member(team_id, user_id)`). Use
  `select_related` / `prefetch_related` here so services never cause N+1 queries.
- **internal/**: same rules as public views, but authenticated with `X-Service-Token` and never mounted
  under `/api/core/v1`.
- Another app's code is reached through its **services**, never its repositories or models' managers.
- `shared/` never imports from domain apps.

## Async rules

Async by default, with explicit sync islands.

- Every API view subclasses `shared.views.AsyncAPIView` and every handler (`get`, `post`, ...) is
  `async def`. Don't use plain DRF `APIView`, `ViewSet` or generic views: they are sync. Django raises
  `ImproperlyConfigured` if a view mixes sync and async handlers.
- `AsyncAPIView.dispatch` runs DRF's `initial()` (authentication, permissions, throttling) in a thread with
  `sync_to_async`. Authentication and permission classes, and the exception handler, are therefore sync
  code: they may use the sync ORM but must stay short.
- All `sync_to_async` work in a uvicorn worker shares one thread. Keep sync islands short; scale with workers.
- `AsyncAPIView.dispatch` mirrors DRF's `APIView.dispatch`. When upgrading DRF, compare the two and port
  any changes.
- Services and repositories are `async def` and use the async ORM: `aget`, `acreate`, `aupdate`, `adelete`,
  `aexists`, `acount`, `async for`, `[obj async for obj in qs]`.
- `transaction.atomic` is sync only. Write the transactional part as a sync function decorated with
  `@transaction.atomic` and call it with `await sync_to_async(fn)(...)`. Repository functions used inside it
  are sync and end in `_sync` (`create_team_sync`). This is the only place sync ORM calls are allowed.
- Never call a sync ORM method from async code (Django raises `SynchronousOnlyOperation`).
  Watch for hidden queries: accessing a foreign key that wasn't loaded (`member.user.email`) is a sync query.
- Redis events are published only after commit: `transaction.on_commit(lambda: publish(...))`.
  If publishing fails, log it and let the request succeed (D-08).
- External I/O uses async clients (`redis.asyncio`, `httpx.AsyncClient`). Blocking SDKs (e.g. the MinIO
  client) are wrapped in `sync_to_async`.

## Conventions

- IDs are `UUIDField(primary_key=True, default=uuid.uuid4)` (D-01). Times are UTC, ISO 8601 in JSON.
- Custom `users.User` with a UUID primary key is `AUTH_USER_MODEL`. Never reference `auth.User`;
  use `settings.AUTH_USER_MODEL` in models and `get_user_model()` elsewhere.
- Errors always use the contract body: `{"error": {"code", "message", "fields"?}}`. Codes come from
  `api-core.md`; add new ones there first.
- Lists that can grow use cursor pagination (`limit` default 50, max 200, `next_cursor`).
- Settings: one `config/settings.py`. Every difference between environments comes from `.env` via
  django-environ. No secrets in code. Production-only security settings sit under `if not DEBUG:`.
- New environment variables are added to `.env.example` in the same commit.
- Local URLs use `127.0.0.1`, never `localhost`. Docker publishes the infra ports on IPv4 only, and Windows
  tries `localhost` as IPv6 (`::1`) first, so every connection stalls until it falls back (with the DB pool
  this ends in `PoolTimeout`). Applies to `DATABASE_URL` and future Redis, MinIO and Kafka URLs.
- Type hints on all function signatures. Double quotes, line length 100 (ruff).
- Names: services are verbs (`create_invite`, `join_channel`), repositories describe the query
  (`get_channel_by_id`, `list_team_members`).

## Tests

- pytest + pytest-django + pytest-asyncio (`asyncio_mode = "auto"`), against the real Postgres container.
- Tests are `async def`; API tests use the `async_client` fixture.
- Mark DB tests with `@pytest.mark.django_db`; use `transaction=True` when the code under test uses
  `transaction.atomic` or `on_commit`.
- The autouse fixture in `tests/conftest.py` closes connections opened inside `sync_to_async`; without it
  the test database can't be dropped. Keep it.
- Test services directly for business rules, and views for status codes and response shapes from the contract.
- Every bug fix comes with a test that fails without the fix.

## Workflow

- One Jira ticket per branch and PR. Branch: `CHAT-<n>/<short-name>`. Commit messages start with `CHAT-<n>:`.
- Use the PR template from the `.github` repo. Before pushing: `ruff check .`, `ruff format --check .`, `pytest`.
- One `requirements.txt` with every package pinned (`pip freeze`), dev tools included.
- Never edit a migration that is already on `main`; add a new one.

## Don'ts

- Don't run `migrate` on `core_db` before the custom User model exists.
- Don't put logic in models, views or serializers.
- Don't read or write chatty-chat's database or Kafka topics; talk to chatty-chat only through the contracts.
- Don't commit `.env`, keys or tokens. Don't log tokens, passwords or presigned URLs.
