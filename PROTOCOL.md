# Chaka Protocol

## Authentication

All connections use token-based auth. Each token has independent boolean permissions: `can_send`, `can_receive`, `can_talk`, and `can_hear`.

- `can_send` — may publish notification payloads (WebSocket or `POST /api/notify`).
- `can_receive` — receives broadcast notifications and missed-message replay.
- `can_talk` — may transmit voice audio. **Implies `can_hear`** — the token API forces `can_hear = true` whenever `can_talk` is set.
- `can_hear` — may join voice channels and receive audio.

Transports:

- WebSocket: `?token=XXX` query param
- HTTP: `Authorization: Bearer XXX` header
- Admin-only endpoints: HTTP Basic auth

WebSocket close codes:

- `4401` — invalid or inactive token (checked at connect; permissions are **not** checked at connect, only per action)
- `4409` — token already connected (one connection per token enforced)
- `1008` — connection closed by the server because the token was revoked or regenerated

---

## WebSocket Channel — `GET /ws`

A single connection handles both notifications and real-time voice. Text frames carry JSON messages; binary frames carry audio.

```
/ws?token=XXX&client=<client-id>&version=<version>
```

Query params:

| Param | Required | Description |
|---|---|---|
| `token` | yes | Auth token |
| `client` | no | Free-form application identifier (e.g. a forwarder app, a receiver app, a browser extension). |
| `version` | no | Application version string, e.g. `1.2.6`. Logged on connect for diagnostics. |

Both `client` and `version` are informational — the server logs them on connect and exposes them in the connected-clients API, but does not use them to gate any behaviour.

### Server → Client frames (JSON text)

**Handshake — sent immediately on connect:**
```json
{
  "type": "hello",
  "can_send": true,
  "can_receive": false,
  "can_talk": true,
  "can_hear": true,
  "channels": [{"id": 1, "number": 1, "name": "Channel 1"}]
}
```
`channels` is included only when `can_talk` or `can_hear` is `true`, and lists all enabled channels ordered by number.

**Replay — sent after `hello` if `can_receive` and missed messages exist:**
```json
{
  "type": "replay",
  "count": 3,
  "has_more": false,
  "messages": [
    {"msg_id": "<uuid>", "message": {...}},
    ...
  ]
}
```
Up to **100** messages received since the token's `last_delivered_at`. `has_more` is `true` when more than 100 messages were pending (only the oldest 100 are sent; the rest are not replayed).

**Single delivery — broadcast to all connected `can_receive` clients:**
```json
{"type": "single", "msg_id": "<uuid>", "received_at": "<iso8601>", "message": {"scope": "...", "title": "...", "body": "...", "package": "...", "timestamp": 1234567890, "id": "..."}}
```

**Voice control frames:**

| Frame | Sent to | Trigger |
|---|---|---|
| `{"type": "channels_updated", "channels": [{"id": 1, "number": 1, "name": "..."}]}` | All voice-capable (`can_hear`) clients | Admin creates, renames, disables, or deletes a channel |
| `{"type": "voice_joined", "channel_id": 1, "clients": [{"token_name": "...", "transmitting": false, "muted": false}, ...]}` | The joining client | Client sends `voice_join` |
| `{"type": "voice_peer_joined", "channel_id": 1, "token_name": "..."}` | Other clients already in the channel | Client sends `voice_join` |
| `{"type": "voice_peer_left", "channel_id": 1, "token_name": "..."}` | Remaining clients in the channel | Client sends `voice_leave`, switches channel, or disconnects |
| `{"type": "voice_peer_muted", "channel_id": 1, "token_name": "..."}` | Other clients in the same channel | Client sends `voice_mute` |
| `{"type": "voice_peer_unmuted", "channel_id": 1, "token_name": "..."}` | Other clients in the same channel | Client sends `voice_unmute` |
| `{"type": "talking", "token_name": "...", "channel_id": 1}` | Other clients in the same channel | Transmitter sends its first audio chunk |
| `{"type": "silent", "token_name": "...", "channel_id": 1}` | Other clients in the same channel | Transmitter sends `\x00` or disconnects |
| `{"type": "busy", "token_name": "..."}` | The sender | Channel transmitter slot already taken; audio chunk dropped |
| `{"type": "voice_ejected"}` | The affected client | Admin revokes the client's voice permission while it is connected |

`voice_ejected` does **not** close the WebSocket. The connection stays alive; only voice access is revoked. Clients must clear all voice state and hide the voice UI on receipt.

### Client → Server

**Send notification — `can_send` tokens only, raw JSON payload (no `type` field):**
```json
{"scope": "...", "title": "...", "body": "...", "package": "...", "timestamp": 1234567890, "id": "..."}
```
`timestamp` is epoch milliseconds; the server derives `received_at` from it.

**Join voice channel — `can_talk` or `can_hear` tokens only:**
```json
{"type": "voice_join", "channel_id": 1}
```
A client must join a channel before sending or receiving audio. The server ignores the frame if the channel doesn't exist or is disabled. Joining a new channel automatically leaves the previous one.

**Leave voice channel — `can_talk` or `can_hear` tokens only:**
```json
{"type": "voice_leave"}
```
Ends any active transmission and removes the client from the channel.

**Mute/unmute self — `can_talk` tokens only:**
```json
{"type": "voice_mute"}
{"type": "voice_unmute"}
```
The server updates the muted flag and broadcasts `voice_peer_muted`/`voice_peer_unmuted` to other clients in the same channel.

**Audio data — `can_talk` tokens only:** raw binary frames, streamed continuously while transmitting. Relayed to all other clients in the same channel except those that are muted. Audio format is defined by the clients (the reference Android clients use 16 kHz mono PCM 16-bit); the server relays bytes opaquely and does not transcode.

**End-of-transmission — `can_talk` tokens only:** a single zero byte `\x00`.

**Transmitter lock — per channel, not global:**
- Each channel independently enforces one active transmitter at a time via its own `current_transmitter` slot.
- Two different channels can have simultaneous transmitters.
- Within a channel, if a second client sends audio while the slot is taken, it receives a `busy` frame and its data is dropped. The ongoing transmission is unaffected.
- The lock only protects state mutation (claiming the transmitter slot, collecting recipients). Binary relay happens outside the lock, so holding it does not block other channels.
- A client can be in only one channel at a time.

---

## HTTP Endpoints

| Method | Path | Auth | Description |
|---|---|---|---|
| `POST` | `/api/notify` | Bearer (`can_send`) | Send a notification. Optional header `X-Source` (default `"device"`) |
| `POST` | `/api/ack` | Bearer (`can_receive`) | ACK delivery |
| `POST` | `/api/send` | Admin Basic | Send from the admin UI. Optional `token_ids` array to target specific clients. |

**`POST /api/notify` — request body:**
```json
{"scope": "...", "title": "...", "body": "...", "package": "...", "timestamp": 1234567890}
```

**`POST /api/send` — request body:**
```json
{"scope": "...", "title": "...", "body": "...", "package": "...", "timestamp": 1234567890, "token_ids": [1, 3]}
```
All fields except `title` are optional. `token_ids` restricts delivery to those specific connected clients (matched by `token_id`, must have `can_receive`). Omit `token_ids` or set it to `null` to broadcast to all `can_receive` clients.

**`POST /api/notify` and `POST /api/send` — response:**
```json
{"sent": 2, "msg_id": "<uuid>"}
```
`sent` reflects how many clients actually received the message in this request. For targeted sends, clients in `token_ids` that are not connected or lack `can_receive` are silently skipped.

**`POST /api/ack` — request body:**
```json
{"msg_ids": ["<uuid>", "<uuid>"]}
```

**`POST /api/ack` — response:**
```json
{"acked": 2}
```

---

## HTTP Endpoints — Channel Management (Admin)

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/channels` | List all channels with live client stats |
| `POST` | `/api/channels` | Create a channel: `{"number": 2, "name": "Channel 2"}` |
| `PATCH` | `/api/channels/{id}` | Update name or enabled state: `{"name": "...", "is_enabled": false}` |
| `DELETE` | `/api/channels/{id}` | Delete a channel — `409` if any clients are currently in it |

Channel lifecycle rules:
- **Disable (`is_enabled: false`)** — the server immediately force-ejects all clients currently in the channel (ends their transmission, removes them, sends `voice_peer_left` to remaining peers), then pushes `channels_updated` to all voice-capable clients so they drop the channel from their UI.
- **Delete** — blocked with `409 Conflict` if any clients are in the channel. Disable first, then delete once empty. Deletion also pushes `channels_updated`.
- **Create / rename** — pushes `channels_updated` to all voice-capable clients.

---

## HTTP Endpoints — Token Management (Admin)

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/tokens` | Create a token: `{"name": "..."}` |
| `PATCH` | `/api/tokens/{id}` | Rename: `{"name": "..."}` |
| `PATCH` | `/api/tokens/{id}/permissions` | Update permissions: `{"can_send": bool, "can_receive": bool, "can_talk": bool, "can_hear": bool}` |
| `DELETE` | `/api/tokens/{id}` | Revoke token — closes active connection with code `1008` |
| `POST` | `/api/tokens/{id}/restore` | Restore a revoked token |
| `POST` | `/api/tokens/{id}/regenerate` | Issue a new token value — closes active connection with code `1008` |

### Permission-change semantics

This is the one area where it matters *when* a change takes effect, because the server snapshots a connection's permissions into memory at connect time:

- **`can_send` / `can_receive` changes** — written to the database but **not** applied to a live connection. They take effect on the client's **next (re)connect**. (A live socket keeps the send/receive rights it had at connect.)
- **Voice revocation** (both `can_talk` and `can_hear` turned off) **while connected** — applied **live**: the server ends any active transmission, removes the client from its channel (broadcasting `voice_peer_left`), updates the in-memory flags, and sends `{"type": "voice_ejected"}`. The WebSocket is **not** closed.
- **Voice grant** — takes effect on the client's **next reconnect**; no push is sent to live connections.
- **Revoke (`DELETE`) and regenerate** — force-close the live socket with code `1008`.

> Note: an earlier draft of the docs claimed all permission changes apply live. That is accurate only for voice revocation and token revoke/regenerate; `can_send`/`can_receive` changes apply on reconnect.

---

## Message Type Reference

| Type | Direction | Format | Permission |
|---|---|---|---|
| `hello` | S→C | JSON text | — (sent to every client on connect) |
| `replay` | S→C | JSON text | `can_receive` |
| `single` | S→C | JSON text | `can_receive` |
| `channels_updated` | S→C | JSON text | `can_hear` |
| `voice_joined` | S→C | JSON text | `can_hear` |
| `voice_peer_joined` | S→C | JSON text | `can_hear` |
| `voice_peer_left` | S→C | JSON text | `can_hear` |
| `talking` | S→C | JSON text | `can_hear` |
| `silent` | S→C | JSON text | `can_hear` |
| `busy` | S→C | JSON text | `can_talk` |
| `voice_peer_muted` | S→C | JSON text | `can_hear` |
| `voice_peer_unmuted` | S→C | JSON text | `can_hear` |
| `voice_ejected` | S→C | JSON text | `can_hear` |
| *(notification payload)* | C→S | JSON text | `can_send` |
| `voice_join` | C→S | JSON text | `can_talk` or `can_hear` |
| `voice_leave` | C→S | JSON text | `can_talk` or `can_hear` |
| `voice_mute` | C→S | JSON text | `can_talk` |
| `voice_unmute` | C→S | JSON text | `can_talk` |
| *(audio)* | C→S→C | binary bytes | `can_talk` (send), relayed to channel peers |
| `\x00` | C→S | binary sentinel | `can_talk` |
