# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
