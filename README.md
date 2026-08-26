# Chaka

> **Chaka** means "bridge" in Quechua.

[![PyPI](https://img.shields.io/pypi/v/chaka.svg)](https://pypi.org/project/chaka/)
[![CI](https://github.com/puentesarrin/chaka/actions/workflows/ci.yml/badge.svg)](https://github.com/puentesarrin/chaka/actions/workflows/ci.yml)

Chaka is a self-hosted, real-time **relay server** for notifications and voice over a single WebSocket. Sender clients publish notification payloads (or stream push-to-talk audio); receiver clients get them in real time. It is a small, dependency-light FastAPI application with a server-rendered admin UI for managing access tokens, channels, and logs.

It is transport-agnostic about *what* you relay — any JSON notification payload and any binary audio stream. The reference clients are Android apps (a notification forwarder and a receiver), but any WebSocket or HTTP client that follows [the protocol](https://github.com/puentesarrin/chaka/blob/main/PROTOCOL.md) works.

## Features

- **Real-time notification fan-out** over WebSocket, with an HTTP `POST /api/notify` alternative for server-side sources.
- **Missed-message replay** — the server tracks `last_delivered_at` per token and replays up to 100 missed notifications on reconnect (single batched frame).
- **Push-to-talk voice** — named voice channels carried on the same WebSocket as binary frames, with a per-channel single-transmitter lock, mute, and live peer presence.
- **Token-based auth** with four independent permissions: `can_send`, `can_receive`, `can_talk`, `can_hear`.
- **Admin UI** (session login) — user accounts with hashed passwords, token CRUD and permissions, live connected-client monitoring, voice channels, notification history with per-token delivery/ack tracking, and log tailing.
- **Operational niceties** — rotating file logs, an optional push **heartbeat** to any status-page/uptime monitor (Uptime Kuma, Healthchecks.io, …), optional Sentry error reporting.

See [PROTOCOL.md](https://github.com/puentesarrin/chaka/blob/main/PROTOCOL.md) for the full wire protocol (frames, permissions, close codes).

## Architecture

```
 senders (WS can_send / HTTP POST /api/notify)
        │
        ▼
   ┌─────────────────────────────────────────────┐
   │  Chaka (FastAPI, single process)            │
   │   • /ws  WebSocket endpoint                 │
   │   • ConnectionManager (in-memory, asyncio)  │
   │   • admin UI + REST API (Jinja2 templates)  │
   └─────────────────────────────────────────────┘
        │ persist                  │ broadcast
        ▼                          ▼
        MySQL / PostgreSQL         receivers (WS can_receive) / voice peers (can_talk/can_hear)
```

- **`ConnectionManager`** (`chaka/manager.py`) holds all live WebSocket connections and per-channel voice state in memory, guarded by a single `asyncio.Lock`. One connection per token is enforced.
- **Persistence** is for tokens, notification history, delivery/ack records, connection events, and voice-session metadata — not for live routing, which is in-memory.
- The server is designed to run **single-process** (`--workers 1`). Cross-process/cross-instance fan-out is **not implemented**.

## Tech stack

| Concern | Choice |
|---|---|
| Language / runtime | Python 3.11+ |
| Web framework | FastAPI + Uvicorn |
| Realtime | `websockets` (via FastAPI WebSocket) |
| ORM / DB driver | SQLAlchemy 2.0 (async) + `aiomysql` (**MySQL**) or `asyncpg` (**PostgreSQL**) |
| Migrations | Alembic |
| Templates | Jinja2 (server-rendered admin UI) |
| Validation | Pydantic 2 |
| Monitoring (optional) | Push heartbeat (Uptime Kuma-compatible), Sentry |

> Note: the project targets **MySQL** (`aiomysql`) and **PostgreSQL** (`asyncpg`) — switch by changing `DATABASE_URL` and installing the matching driver. Both are exercised end to end: migrations, and every HTTP/WebSocket route, against a real instance of each engine. `DateTime` columns are naive UTC throughout (`chaka.clock.utcnow()`), which `aiomysql` accepted silently but `asyncpg` enforces strictly against `TIMESTAMP WITHOUT TIME ZONE` — write through `chaka.clock` rather than `datetime.now(UTC)` directly if you're extending the schema.

## Configuration

All configuration is via environment variables (a `.env` file is loaded automatically). Copy `.env.example` to `.env` and edit:

| Variable | Required | Purpose | Default |
|---|---|---|---|
| `DATABASE_URL` | yes | SQLAlchemy async DB URL | `mysql+aiomysql://user:pass@localhost:3306/chaka` or `postgresql+asyncpg://user:pass@localhost:5432/chaka` |
| `SECRET_KEY` | recommended | Signs admin session cookies; generated per start if unset (see below) | _(ephemeral)_ |
| `ADMIN_USER` | yes | Bootstrap admin username (used only until the first user exists) | `admin` |
| `ADMIN_PASSWORD` | yes | Bootstrap admin password — **change this** | `changeme` |
| `SESSION_COOKIE` | no | Session cookie name | `chaka_session` |
| `SESSION_MAX_AGE` | no | Session lifetime (seconds) | `43200` (12 h) |
| `SESSION_COOKIE_SECURE` | no | Send the session cookie only over HTTPS | `false` |
| `LOG_FILE` | no | Rotating application log path | `./chaka.log` |
| `LOG_MAX_BYTES` | no | Log rotation size (5 MB) | `5242880` |
| `LOG_BACKUP_COUNT` | no | Rotated log files kept | `5` |
| `HEARTBEAT_URL` | no | Push-heartbeat URL (status-page/uptime monitor); blank disables it | _(disabled)_ |
| `HEARTBEAT_INTERVAL` | no | Heartbeat interval (seconds) | `60` |
| `HEARTBEAT_LOG_FILE` | no | Heartbeat log path | `./heartbeat.log` |
| `SENTRY_DSN` | no | Sentry DSN; blank disables Sentry | _(disabled)_ |
| `SENTRY_TRACES_SAMPLE_RATE` | no | Sentry traces sample rate | `0.2` |
| `TITLE` | no | App title (admin UI / OpenAPI) | `Chaka` |
| `WEBSOCKET_PATH` | no | WebSocket route path | `/ws` |
| `STATIC_DIR` | no | Override the static-assets directory | _(bundled)_ |
| `TEMPLATES_DIR` | no | Override the admin-templates directory | _(bundled)_ |

## Install & run (from PyPI)

```bash
pip install chaka          # MySQL (aiomysql) — bundled by default
pip install "chaka[postgres]"   # or PostgreSQL (asyncpg)

chaka init                 # copy static/templates here, write .env, run migrations
# edit .env — set DATABASE_URL and admin credentials
chaka serve                # serves on http://127.0.0.1:8000
```

`chaka init` scaffolds a customizable server in the current directory. If you
don't need to edit the bundled assets you can skip it — just provide the config
(above), run `chaka db upgrade` to create the schema, and `chaka serve`.

Open the admin UI, log in with `ADMIN_USER` / `ADMIN_PASSWORD`, and create a
token on the **Tokens** tab (the value is shown once). Point a client at
`ws://HOST:PORT/ws?token=YOUR_TOKEN`.

### Admin accounts

The admin UI authenticates against a `users` table — `username`, `email`,
`full_name`, `password_hash`, `is_active`, `created_at`, `last_login_at` —
with a signed, HttpOnly session cookie. Passwords are hashed with PBKDF2-HMAC-SHA256
(stdlib, per-user salt); the hash records its own cost, so raising it later
re-hashes each account on its next login instead of invalidating it.

**First login.** While the table is empty, `ADMIN_USER` / `ADMIN_PASSWORD` from
the environment still work, and the first successful login is saved as a real
user row. An existing deployment therefore keeps working across the upgrade —
run `chaka db upgrade` and sign in with the credentials you already have. Once
any user exists those environment credentials stop being accepted, so change the
bootstrapped account's email and password on the **Users** tab (or skip the
bootstrap entirely with `chaka user create`).

Every active user is a full admin. To keep an instance from locking itself out,
you cannot deactivate or delete your own account, nor the last active one.
Deactivating or deleting a user invalidates their session on the next request.

**`SECRET_KEY`** signs the session cookies. Leave it unset and Chaka generates
one per start: sessions then die on every restart, and each worker signs
differently. Set it in `.env` (`chaka init` writes a random one for you), keep it
secret, and note that changing it signs everyone out. Turn on
`SESSION_COOKIE_SECURE` once you serve Chaka over TLS.

Only the admin UI and its `/api` routes use sessions. Client-facing endpoints
are unchanged: `/ws`, `POST /api/notify`, and `POST /api/ack` still authenticate
with relay tokens.

### CLI

```
chaka serve [--host H] [--port P]      run the server
chaka init  [--path DIR]               copy assets + write .env + migrate
chaka db upgrade [--revision REV]      apply migrations

chaka user create --username U --email E [--full-name N] [--password P]
chaka user list                        list accounts
chaka user passwd --username U [--password P]
```

`--password` is prompted for (twice, hidden) when omitted.

## Use as a library

Build the app with the `create_app` factory and adapt it by **composition** —
inject your own collaborators, no subclassing required:

```python
from chaka.factory import create_app
from chaka.application import Settings

app = create_app()  # env-driven
app = create_app(Settings(title='Acme Relay'))  # explicit config
app = create_app(manager=MyManager(), routers=[(my_router, '/api')])
```

`create_app` returns a `ChakaApp` (an ASGI app with `.run()`), so
`uvicorn mymodule:app` works. For deeper changes, subclass
`ChakaApplicationFactory` and override a build step (`get_manager`,
`get_handler`, `default_routers`, `_make_logger`, …):

```python
from chaka.factory import ChakaApplicationFactory


class MyFactory(ChakaApplicationFactory):
    def get_manager(self, voice_log):
        return MyManager(voice_log=voice_log)


app = MyFactory().create_app()
```

## Develop from a clone

```bash
git clone https://github.com/puentesarrin/chaka.git
cd chaka

python3 -m venv venv
source venv/bin/activate
pip install -e ".[dev]"          # runtime deps + ruff, pytest

cp .env.example .env
# edit .env — set DATABASE_URL and admin credentials

alembic upgrade head                         # or: chaka db upgrade
uvicorn main:app --host 0.0.0.0 --port 8000 --reload   # or: chaka serve
```

Lint and format (config in `pyproject.toml`, `[tool.ruff]`):

```bash
ruff check .        # lint
ruff format .       # format (single quotes, 120 cols)
```

## Tests

The suite is pure-unit and mock-based — no database or network required (the
in-memory backend, `NullVoiceLog`, fake repositories, and factory injection make
every layer testable in isolation):

```bash
pip install -e ".[dev]"
pytest                                   # run the suite
pytest --cov=chaka --cov-report=term-missing   # with coverage
```

Config lives in `pyproject.toml` (`[tool.pytest.ini_options]`, `asyncio_mode = "auto"`
so async tests need no decorator). CI (`.github/workflows/ci.yml`) runs ruff +
pytest on Python 3.11 and 3.12 for every push and pull request.

## Migrations

```bash
chaka db upgrade                                      # installed: apply latest
alembic upgrade head                                  # from a clone: apply latest
alembic revision --autogenerate -m "describe change"  # after model changes (clone)
```

## Production deployment (systemd + nginx)

The `deploy/` directory contains templates:

- `deploy/chaka.service` — systemd unit (expects the app at `/opt/chaka` with a venv at `/opt/chaka/venv` and a `chaka` service user; adjust to taste).
- `deploy/nginx.conf` — TLS reverse proxy with the WebSocket upgrade headers and a long `proxy_read_timeout` for `/ws`. Replace `chaka.example.com` with your domain.

```bash
# install into a venv at /opt/chaka and set up the DB:
python3 -m venv /opt/chaka/venv
/opt/chaka/venv/bin/pip install chaka
# create /opt/chaka/.env with DATABASE_URL + admin credentials, then:
/opt/chaka/venv/bin/chaka db upgrade

# service:
sudo cp deploy/chaka.service /etc/systemd/system/chaka.service
sudo systemctl daemon-reload
sudo systemctl enable --now chaka
sudo systemctl status chaka
sudo journalctl -u chaka -f

# TLS + reverse proxy
sudo certbot --nginx -d chaka.example.com
sudo cp deploy/nginx.conf /etc/nginx/sites-available/chaka
sudo ln -s /etc/nginx/sites-available/chaka /etc/nginx/sites-enabled/chaka
sudo nginx -t && sudo systemctl reload nginx
```

Run the server bound to `127.0.0.1` behind nginx. Use a **single worker** — the connection manager is in-process, so multiple workers would not share connections. `chaka serve` runs one worker; if you invoke uvicorn directly, pass `--workers 1`.

## Status & limitations

- **Single-process only.** No cross-process/cross-instance fan-out.
- **No roles.** Every active user account is a full admin; there is no read-only or scoped access.
- **Best-effort delivery** — notifications are persisted and replayed on reconnect (up to 100), but there is no guaranteed/ack-driven retransmission; voice audio is relayed live and not stored.

## License

MIT — see [LICENSE](https://github.com/puentesarrin/chaka/blob/main/LICENSE).
