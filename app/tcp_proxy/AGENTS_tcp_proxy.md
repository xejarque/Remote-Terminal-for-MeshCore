# TCP Proxy Architecture

MeshCore companion protocol proxy: emulates a MeshCore radio over TCP,
translating the binary companion protocol into in-process RemoteTerm
operations. MeshCore clients (mobile apps, meshcore-cli, meshcore-ha)
connect to it and interact with RemoteTerm as if it were a physical radio.

Enable with `MESHCORE_TCP_PROXY_ENABLED=true`.

## Module Map

```text
app/tcp_proxy/
├── __init__.py           # start_tcp_proxy() / stop_tcp_proxy() lifecycle
├── protocol.py           # Constants, FrameParser, frame helpers
├── encoder.py            # Binary builders: contact, self_info, device_info
├── session.py            # ProxySession: per-client command dispatch + event handlers
├── server.py             # TCP server lifecycle, session registry, dispatch_event()
└── AGENTS_tcp_proxy.md   # This file
```

## Protocol (protocol.py)

- Frame format: `0x3C`/`0x3E` marker + 2-byte LE length + payload
- Command constants (`CMD_*`): client → proxy (first payload byte)
- Response constants (`RESP_*`): proxy → client
- Push constants (`PUSH_*`): unsolicited proxy → client notifications
- `FrameParser`: stateful streaming frame decoder (mirrors meshcore_py `tcp_cx.py`)
- Helpers: `frame_response`, `build_ok`, `build_error`, `pad`, `encode_path_byte`

## Encoder (encoder.py)

Stateless binary serializers that build companion-protocol payloads from
domain data. All functions return raw `bytes` (no frame wrapping).

- `build_contact` / `build_contact_from_dict`: Contact → RESP_CONTACT / PUSH_NEW_ADVERT
- `build_self_info` / `build_self_info_from_runtime`: radio config → RESP_SELF_INFO
- `build_device_info`: → RESP_DEVICE_INFO (fixed proxy identity)

## Session (session.py)

One `ProxySession` per connected TCP client. Maintains per-client state:

- **contacts**: cached favorite contacts from DB
- **channels**: cached channel list
- **channel_slots** / **key_to_idx**: bidirectional channel index ↔ key mapping
- **_msg_queue**: queued incoming messages for the pull-based delivery model

### Command Dispatch

Command byte → handler method via class-level dispatch table. Unsupported
commands return `ERR_UNSUPPORTED`.

### Message Delivery (Pull Model)

MeshCore mobile apps use a pull model for incoming messages:
1. Broadcast event arrives → session builds a V3 message frame → queues it
2. Session sends `PUSH_MSG_WAITING` (0x83) to notify the client
3. Client calls `CMD_SYNC_NEXT_MESSAGE` (0x0A) to pull the message
4. Session dequeues and sends the frame
5. Client calls again → `RESP_NO_MORE_MSGS` when queue is empty

### DM Send Flow

1. Parse destination prefix/key from binary payload
2. Resolve to full public key via contacts cache
3. Send immediate `RESP_MSG_SENT` + `PUSH_ACK` (fake ACK) so client doesn't retry
4. Fire-and-forget `_do_send_dm()` task calls `send_direct_message_to_contact()`
5. RemoteTerm handles actual radio lock, retries, and ACK tracking

## Server (server.py)

- TCP server lifecycle (`start` / `stop`) following the `radio_stats.py` pattern
- Session registry (`register` / `unregister`)
- `dispatch_event()`: called from `broadcast_event()` in `websocket.py` for
  `message`, `message_acked`, and `contact` events

## Data Flow

```
Client → TCP frame → FrameParser → ProxySession._dispatch
  → command handler → repository/service call → binary response → TCP frame

RemoteTerm event → broadcast_event → dispatch_event
  → ProxySession.on_event_* → push frame → TCP frame
```

## Integration Points

- `app/config.py`: `tcp_proxy_enabled`, `tcp_proxy_bind`, `tcp_proxy_port`
- `app/main.py`: conditional `start_tcp_proxy()` / `stop_tcp_proxy()` in lifespan
- `app/websocket.py`: `dispatch_event()` hook in `broadcast_event()` for message/ack/contact

## Design Constraints

- Never mutate RemoteTerm state from SET_CHANNEL (local slot mapping only)
- Only sync favorite contacts to clients
- Channel slots: pre-load favorites only, ERR_NOT_FOUND for empty slots
- DM sends return immediate fake ACK (RemoteTerm handles retries)
- Message delivery uses the pull model (PUSH_MSG_WAITING → SYNC_NEXT_MESSAGE)

## Config

| Variable | Default | Description |
|----------|---------|-------------|
| `MESHCORE_TCP_PROXY_ENABLED` | `false` | Enable the TCP companion protocol proxy |
| `MESHCORE_TCP_PROXY_BIND` | `0.0.0.0` | Bind address for the proxy TCP server |
| `MESHCORE_TCP_PROXY_PORT` | `5001` | Port for the proxy TCP server |

## Tests

```text
tests/
├── test_tcp_proxy_protocol.py      # FrameParser, frame helpers (pure, no async)
├── test_tcp_proxy_encoder.py       # Binary encoding against expected wire bytes
├── test_tcp_proxy_session.py       # Command handlers with mocked radio + repos
└── test_tcp_proxy_integration.py   # Real TCP server, end-to-end frame exchange
```
