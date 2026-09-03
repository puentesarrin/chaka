# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.5.0] - 2026-09-03

### Added

- Close code **`4410`** for a displaced connection, so a client can tell "you were replaced" from "your network dropped". A client that receives it was replaced deliberately and should **not** reconnect immediately; every other kind of drop reconnects as before. See `PROTOCOL.md`.
- `IBackend.register_displacing()` performs the take-over. It ships with a default implementation built from the existing primitives, so a backend written against the previous interface keeps working; `InMemoryBackend` overrides it to do the eviction and the registration under one lock, leaving no instant in which two sessions hold the same token.
- Disconnect logging records the token, how long the connection was held and the WebSocket close code. It previously logged only the `ws_id`, which is why diagnosing a disconnection problem needed external probes rather than the logs.

### Changed

- **A reconnecting client now displaces the older connection instead of being rejected.** One connection per token is unchanged — the newcomer wins rather than the incumbent. When a socket dies silently the server only learns of it when its ping times out, and until then the client was locked out: measured on a live deployment at a median of 17 seconds and up to 24, against 625 rejections for 123 connections in a day. Preferring a session that may be a ghost over a client that is demonstrably present had it backwards.
- Displacing a session that is in a voice channel now runs the same teardown a normal disconnect does: its peers get `voice_peer_left`, and an open transmission is ended and its `voice_log` row closed. The displaced handler cannot do this itself — by the time it wakes up its session is already out of the registry and every teardown call is a no-op.
- `IConnectionManager.connect()` now returns `(ws_id, displaced)`. The displaced session is handed back rather than closed, because closing needs the same lock the registry holds. **Breaking for anyone implementing the interface**; the shipped manager and handler are updated.
- `4409` is now returned only when registration genuinely fails, which should not happen in normal operation. A reconnecting client used to receive it and no longer does.

[0.5.0]: https://github.com/puentesarrin/chaka/releases/tag/v0.5.0

## [0.4.0] - 2026-08-26

### Added

- **Admin user accounts.** A new `users` table (`username`, `email`, `full_name`, `password_hash`, `is_active`, `created_at`, `last_login_at`) replaces the single hard-coded admin. Passwords are hashed with PBKDF2-HMAC-SHA256 from the standard library, with a per-user salt and a cost recorded in the hash, so raising it later re-hashes each account on its next login rather than invalidating it. No new dependency.
- **Session login** for the admin UI: `GET`/`POST /login`, `POST /logout`, and a signed, HttpOnly, `SameSite=Lax` session cookie (`SECRET_KEY`, `SESSION_COOKIE`, `SESSION_MAX_AGE`, `SESSION_COOKIE_SECURE`). Deactivating or deleting a user invalidates their session on the next request.
- **Users tab** in the admin UI — create, edit, activate/deactivate, change password, delete — and `/api/users` behind the same session auth.
- **`chaka user create | list | passwd`** for managing accounts from the command line; `chaka init` now writes a random `SECRET_KEY` into the generated `.env`.
- **`chaka db downgrade --revision REV`**, the counterpart to `chaka db upgrade`.

### Changed

- **The admin UI and its `/api` routes now authenticate with a session cookie instead of HTTP Basic.** Client-facing endpoints are untouched: `/ws`, `POST /api/notify`, and `POST /api/ack` still use relay tokens. Scripts that called an admin `/api` route with Basic credentials must log in through `POST /login` and reuse the cookie.
- `ADMIN_USER` / `ADMIN_PASSWORD` are now **bootstrap credentials**: they are accepted only while the `users` table is empty, and the first successful login is persisted as a real user account. An existing deployment upgrades by running `chaka db upgrade` and signing in with the credentials it already has.
- **SQLite is now the default database.** `aiosqlite` is a base dependency and `DATABASE_URL` defaults to `sqlite+aiosqlite:///./chaka.db`, so a fresh install runs with no database server. MySQL and PostgreSQL move to extras: `pip install chaka[mysql]` and `pip install chaka[postgres]`. Existing deployments are unaffected as long as `DATABASE_URL` is set — but an upgrade must install the matching extra, since `aiomysql` is no longer pulled in by default.

### Fixed

- Autoincrementing `BigInteger` primary keys (`notification_log.id`, `voice_log.id`) inserted `NULL` on SQLite: only a key declared exactly `INTEGER` is a rowid alias there. They now use `models.BigId` (`BigInteger` with an `Integer` variant for SQLite); the DDL on MySQL and PostgreSQL is unchanged (`BIGINT` / `BIGSERIAL`).
- SQLite connections now set `PRAGMA foreign_keys=ON`, without which the schema's `ondelete` rules would silently not fire, and `PRAGMA journal_mode=WAL` so readers don't block the writer.

### Migrations

- `0003_users` — creates the `users` table. Nothing is seeded.

[0.4.0]: https://github.com/puentesarrin/chaka/releases/tag/v0.4.0

## [0.3.0] - 2026-08-09

### Added

- **PostgreSQL support**, alongside MySQL. Install with `chaka[postgres]` (`asyncpg`) and point `DATABASE_URL` at `postgresql+asyncpg://...` — no other changes needed. `aiomysql` stays a base dependency, so existing MySQL-only installs are unaffected.

### Fixed

- Every `DateTime` write used a timezone-aware `datetime.now(UTC)` against columns declared without `timezone=True`. `aiomysql` accepted this silently; `asyncpg` rejects it outright against `TIMESTAMP WITHOUT TIME ZONE`. Centralized as `chaka.clock.utcnow()` (naive UTC) and used at every write site.
- `NotificationRepository.create()` defaulted `forwarded_at` to `None` against a `NOT NULL` column with no server-side default. `POST /api/notify` and `POST /api/send` never passed it, so every HTTP-triggered notification hit this — masked on MySQL depending on `sql_mode`, surfaced immediately on PostgreSQL.

[0.3.0]: https://github.com/puentesarrin/chaka/releases/tag/v0.3.0

## [0.2.0] - 2026-07-02

### Added

- Templates and static assets now **fall back to Chaka's bundled files**. When `TEMPLATES_DIR` / `STATIC_DIR` point at a custom directory, any file not found there resolves from Chaka's packaged `templates/` / `static/`. Consumers can override only the assets they customize (e.g. branding) instead of copying the whole set. Backward-compatible: a default install serves Chaka's own assets exactly as before.

[0.2.0]: https://github.com/puentesarrin/chaka/releases/tag/v0.2.0

## [0.1.0] - 2026-07-01

Initial release.

### Added

- Real-time **notification fan-out** over a single WebSocket (`/ws`), plus an HTTP `POST /api/notify` alternative for server-side sources.
- **Missed-message replay** — per-token `last_delivered_at` tracking replays up to 100 missed notifications on reconnect in one batched frame.
- **Push-to-talk voice** — named voice channels carried on the same WebSocket as binary frames, with a per-channel single-transmitter lock, mute, and live peer presence.
- **Token-based auth** with four independent permissions: `can_send`, `can_receive`, `can_talk`, `can_hear`.
- **Delivery acknowledgement** endpoint (`POST /api/ack`), with CORS support for browser-extension clients.
- **Admin UI** (HTTP Basic): token CRUD and permissions, live connected-client monitoring, voice-channel management, notification history with per-token delivery/ack tracking, and log tailing.
- **Operational niceties**: rotating file logs, an optional push **heartbeat** to any status-page/uptime monitor, and optional Sentry error reporting.
- **`chaka` CLI**: `serve`, `init` (scaffold assets + `.env` + migrate), and `db upgrade`.
- **Library API**: the `create_app` factory with composition-based injection (`manager`, `handler`, `routers`, `settings`) and an overridable `ChakaApplicationFactory`; pluggable `IBackend`, `IConnectionManager`, `IVoiceLog`, and `IWebSocketHandler` contracts.
- MySQL persistence via SQLAlchemy 2.0 (async) with Alembic migrations.
- Mock-based test suite (pytest) and GitHub Actions CI running ruff + pytest on Python 3.11 and 3.12.

[0.1.0]: https://github.com/puentesarrin/chaka/releases/tag/v0.1.0
