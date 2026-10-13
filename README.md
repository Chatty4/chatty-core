# chatty-core

Django service for Chatty: users and auth today; teams, channels and files next.
Python 3.14 · Django 6.1 · DRF (async) · Postgres 17 · Redis · uvicorn.

Contracts live in `chatty-infra/docs`: `api-core.md` (public), `api-internal.md` (`/internal`).

## Quick start (about 10 min)

Run from `chatty-core` in PowerShell:

1. Start the infra:
   ```bash
   docker compose -f ../chatty-infra/docker-compose.yml up -d
   ```
2. Install:
   ```bash
   python -m venv .venv; .venv\Scripts\Activate.ps1; pip install -r requirements.txt
   ```
3. Create `.env`, then set `SECRET_KEY` in it:
   ```bash
   cp .env.example .env
   ```
4. Create the JWT keys and give chatty-chat the public one:
   ```bash
   docker run --rm -v ${PWD}/keys:/keys alpine/openssl genrsa -out /keys/jwt_private.pem 2048
   docker run --rm -v ${PWD}/keys:/keys alpine/openssl rsa -in /keys/jwt_private.pem -pubout -out /keys/jwt_public.pem
   mkdir ../chatty-chat/keys; cp keys/jwt_public.pem ../chatty-chat/keys/
   ```
5. Create the tables:
   ```bash
   python manage.py migrate
   ```
6. Run:
   ```bash
   uvicorn config.asgi:application --reload
   ```

Done when `curl http://127.0.0.1:8000/health` returns `{"status": "ok", "db": "ok", "redis": "ok"}`.

## Endpoints that work

All under `/api/core/v1`. 🔒 = needs `Authorization: Bearer <access_token>`.

| Endpoint | What it does |
|---|---|
| `POST auth/register` | Create an account (10 per hour per IP) |
| `POST auth/login` | Get tokens (5 failures per 15 min, per email and per IP) |
| `POST auth/refresh` | New token pair; the old refresh token stops working |
| 🔒 `POST auth/logout` | Revoke this device's refresh token |
| 🔒 `POST auth/password` | Change password; logs out all other devices |
| 🔒 `GET me` / `PUT me` | View or edit my profile (`teams` is `[]` for now) |

Not built yet: teams, invites, channels, files, `/internal`.

## Daily commands

| Task | Command |
|---|---|
| Run in Docker instead | `docker compose -f ../chatty-infra/docker-compose.yml up -d core` |
| Test | `pytest` |
| Lint and format | `ruff check . && ruff format .` |
| Admin user | `python manage.py createsuperuser`, then open `/admin/` |
| New migration | `python manage.py makemigrations && python manage.py migrate` |
| Purge old tokens | `python manage.py purge_refresh_tokens` (default: older than 30 days) |

`purge_refresh_tokens` deletes refresh tokens that are expired **or** revoked and older than the cutoff.
Flags: `--days N` (default 30, must be ≥ 1), `--dry-run` (count without deleting).

```bash
# Preview what would be removed
python manage.py purge_refresh_tokens --days 60 --dry-run

# Delete tokens older than 60 days
python manage.py purge_refresh_tokens --days 60
```

## When something breaks

| You see | Fix |
|---|---|
| `Set the ... environment variable` | A variable is missing: compare `.env` with `.env.example` |
| `401` with a token that worked before | Keys changed: log in again |
| `429 rate_limited` while testing | `docker exec chatty-redis redis-cli --scan --pattern "login_fail:*"`, then `redis-cli DEL <key>` |
| Can't reach the DB or Redis | Use `127.0.0.1` in `.env`, never `localhost` (IPv6 stall on Windows) |
| Login takes ~1 s | Expected: password hashing is slow on purpose |

## Rules

- Never commit `.env` or `keys/`.
- One Jira ticket per branch: `CHAT-<n>/<short-name>`.
- `ruff check`, `ruff format --check` and `pytest` pass before you push.
- Architecture, async rules and conventions: `CLAUDE.md`.
