# Chaka

> **Chaka** means "bridge" in Quechua.

Chaka is a self-hosted, real-time **relay server** for notifications and voice over a single WebSocket. Sender clients publish notification payloads (or stream push-to-talk audio); receiver clients get them in real time. It is a small, dependency-light FastAPI application with a server-rendered admin UI for managing access tokens, channels, and logs.

It is transport-agnostic about *what* you relay — any JSON notification payload and any binary audio stream. The reference clients are Android apps (a notification forwarder and a receiver), but any WebSocket or HTTP client that follows [the protocol](PROTOCOL.md) works.

## Features

- **Real-time notification fan-out** over WebSocket, with an HTTP `POST /api/notify` alternative for server-side sources.
- **Missed-message replay** — the server tracks `last_delivered_at` per token and replays up to 100 missed notifications on reconnect (single batched frame).
- **Push-to-talk voice** — named voice channels carried on the same WebSocket as binary frames, with a per-channel single-transmitter lock, mute, and live peer presence.
- **Token-based auth** with four independent permissions: `can_send`, `can_receive`, `can_talk`, `can_hear`.
- **Admin UI** (HTTP Basic) — token CRUD and permissions, live connected-client monitoring, voice channels, notification history with per-token delivery/ack tracking, and log tailing.
- **Operational niceties** — rotating file logs, an optional push **heartbeat** to any status-page/uptime monitor (Uptime Kuma, Healthchecks.io, …), optional Sentry error reporting.

See [PROTOCOL.md](PROTOCOL.md) for the full wire protocol (frames, permissions, close codes).

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
     MySQL                 receivers (WS can_receive) / voice peers (can_talk/can_hear)
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
| ORM / DB driver | SQLAlchemy 2.0 (async) + `aiomysql` (**MySQL**) |
| Migrations | Alembic |
| Templates | Jinja2 (server-rendered admin UI) |
| Validation | Pydantic 2 |
| Monitoring (optional) | Push heartbeat (Uptime Kuma-compatible), Sentry |

> Note: the project is written and tested against **MySQL** (`aiomysql`). SQLAlchemy's async layer could in principle target another backend (e.g. PostgreSQL via `asyncpg`) by changing `DATABASE_URL` and the driver, but that is **untested** here and migrations have only been exercised on MySQL.

## Configuration

All configuration is via environment variables (a `.env` file is loaded automatically). Copy `.env.example` to `.env` and edit:

| Variable | Required | Purpose | Default |
|---|---|---|---|
| `DATABASE_URL` | yes | SQLAlchemy async DB URL | `mysql+aiomysql://user:pass@localhost:3306/chaka` |
| `ADMIN_USER` | yes | Admin UI Basic-auth user | `admin` |
| `ADMIN_PASSWORD` | yes | Admin UI Basic-auth password — **change this** | `changeme` |
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
pip install chaka

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

### CLI

```
chaka serve [--host H] [--port P]      run the server
chaka init  [--path DIR]               copy assets + write .env + migrate
chaka db upgrade [--revision REV]      apply migrations
```

## Use as a library

Build the app with the `create_app` factory and adapt it by **composition** —
inject your own collaborators, no subclassing required:

```python
from chaka.factory import create_app
from chaka.application import Settings

app = create_app()                                       # env-driven
app = create_app(Settings(title="Acme Relay"))           # explicit config
app = create_app(manager=MyManager(), routers=[(my_router, "/api")])
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
- **Single admin account** (HTTP Basic) governing all tokens; no per-user accounts.
- **Best-effort delivery** — notifications are persisted and replayed on reconnect (up to 100), but there is no guaranteed/ack-driven retransmission; voice audio is relayed live and not stored.

## License

MIT — see [LICENSE](LICENSE).
