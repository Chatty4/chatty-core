# chatty-core

Django service for Chatty: users, teams, invites, channels, memberships and file uploads.

- Public API: `/api/core/v1` (contract: `chatty-infra/docs/api-core.md`)
- Internal API for chatty-chat: `/internal` (contract: `chatty-infra/docs/api-internal.md`)
- Health check: `GET /health`

Stack: Python 3.14, Django 6.1, Django REST Framework (async views), Postgres 17, uvicorn (ASGI).

## Requirements

- Python 3.14
- Docker, with the infra from `chatty-infra` running (Postgres, Redis, MinIO, Kafka)

## Setup

```bash
# 1. Start the infra
docker compose -f ../chatty-infra/docker-compose.yml up -d

# 2. Create the virtual environment and install the packages
python -m venv .venv
.venv\Scripts\Activate.ps1          # Windows PowerShell
pip install -r requirements.txt

# 3. Create your .env and set a SECRET_KEY
cp .env.example .env
python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
```

Use `127.0.0.1` in `.env` URLs, not `localhost` (Docker publishes the infra ports on IPv4 only).

## JWT keys

Generate the RS256 key pair once per environment (requires Docker):

```bash
docker run --rm -v ${PWD}/keys:/keys alpine/openssl genrsa -out /keys/jwt_private.pem 2048
docker run --rm -v ${PWD}/keys:/keys alpine/openssl rsa -in /keys/jwt_private.pem -pubout -out /keys/jwt_public.pem
```

## Run

```bash
uvicorn config.asgi:application --reload
```

Check it: `curl http://127.0.0.1:8000/health` returns `{"status": "ok", "db": "ok"}`.

## Tests

```bash
pytest
```

Tests run against the Postgres container. pytest-django creates a `test_core_db` database and drops it at the end.

## Lint and format

```bash
ruff check .
ruff format .
```

## Docker

```bash
docker build -t chatty-core .
docker run --rm -p 8000:8000 --network chatty_default \
  -e SECRET_KEY=change-me \
  -e ALLOWED_HOSTS=127.0.0.1,localhost \
  -e DATABASE_URL=postgres://core_user:core_pass@core-db:5432/core_db \
  chatty-core
```

The container joins the infra network (`chatty_default`), so it reaches Postgres as `core-db`, not `127.0.0.1`.

## Contributing

Read `CLAUDE.md` for the architecture, async rules and conventions. One Jira ticket per branch and PR
(`CHAT-<n>/<short-name>`), and `ruff check`, `ruff format --check` and `pytest` must pass before you push.
