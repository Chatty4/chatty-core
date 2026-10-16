# chatty-core

Django service for Chatty: users, auth, teams, invites and channels today; DMs and files next.
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
4. Create the JWT keys with chatty-infra's setup (needs Docker; safe to run again):
   ```bash
   ..\chatty-infra\setup.bat
   ```
   Its "JWT keys" step creates `keys/jwt_private.pem` and `keys/jwt_public.pem` once, makes them readable
   by the core container, and copies the public key to `chatty-chat/keys`. Keys that already exist are kept,
   because new keys log everyone out.
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
Exact requests, responses and errors: `chatty-infra/docs/api-core.md`.

**Auth and profile**

| Endpoint | What it does |
|---|---|
| `POST auth/register` | Create an account (10 per hour per IP) |
| `POST auth/login` | Get tokens (5 failures per 15 min, per email and per IP) |
| `POST auth/refresh` | New token pair; the old refresh token stops working |
| 🔒 `POST auth/logout` | Revoke this device's refresh token |
| 🔒 `POST auth/password` | Change password; logs out all other devices |
| 🔒 `GET me` / `PUT me` | View or edit my profile, with my teams and my role in each |

**Teams and invites** (all 🔒)

| Endpoint | What it does |
|---|---|
| `POST teams` / `GET teams` | Create a team (I become owner, `general` is created) / list my teams |
| `GET` / `PUT` / `DELETE teams/{team_id}` | View, rename (owner/admin) or delete (owner only) a team |
| `GET teams/{team_id}/members` | Team directory, searchable and paginated; `user_ids` to look up people |
| `PUT` / `DELETE teams/{team_id}/members/{user_id}` | Change someone's role / remove them (owner/admin) |
| `POST teams/{team_id}/leave` | Leave a team (the last owner can't) |
| `POST` / `GET teams/{team_id}/invites` | Create an invite link / list them |
| `DELETE invites/{invite_id}` | Revoke an invite link |

**Channels** (all 🔒)

| Endpoint | What it does |
|---|---|
| `GET teams/{team_id}/channels` | My sidebar: channels and DMs I'm in |
| `GET teams/{team_id}/channels/browse` | Public channels I haven't joined, searchable and paginated |
| `POST teams/{team_id}/channels` | Create a public or private channel (I become owner) |
| `GET channels/{channel_id}` | Channel details and my settings in it |
| `PUT channels/{channel_id}` | Rename or change the topic (channel owner, team owner or admin) |
| `POST channels/{channel_id}/archive` | Make it read-only; `general` can't be archived |
| `POST channels/{channel_id}/join` / `leave` | Join a public channel / leave one; the last owner of a private channel hands it to the member who joined first |
| `GET` / `POST channels/{channel_id}/members` | List members (paginated) / add up to 50 team members |
| `DELETE channels/{channel_id}/members/{user_id}` | Remove someone (channel owner, team owner or admin) |

Not built yet: opening an invite link (`GET` / `POST invites/{invite_code}...`), DMs, channel settings
(`PUT channels/{channel_id}/me`), files, `/internal`, and Redis events (`core.events`).

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
| `PermissionError: ... jwt_private.pem` in Docker | Keys made by hand are readable only by root. Run `..\chatty-infra\setup.bat` once |
| `429 rate_limited` while testing | `docker exec chatty-redis redis-cli --scan --pattern "login_fail:*"`, then `redis-cli DEL <key>` |
| Can't reach the DB or Redis | Use `127.0.0.1` in `.env`, never `localhost` (IPv6 stall on Windows) |
| Login takes ~1 s | Expected: password hashing is slow on purpose |

## Rules

- Never commit `.env` or `keys/`.
- One Jira ticket per branch: `CHAT-<n>/<short-name>`.
- `ruff check`, `ruff format --check` and `pytest` pass before you push.
- Architecture, async rules and conventions: `CLAUDE.md`.
