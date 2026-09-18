# WebSocket Server (`ws-agent`)

A lightweight asynchronous WebSocket server built with `uv` and `websockets` (Python 3.13+) that handles two message types: **`msg`** (text) and **`call`** (audio).

## Protocol Specification

The server accepts and broadcasts JSON objects matching either of the following schemas:

### 1. `msg` (Text)
```json
{
  "type": "msg",
  "body": {
    "text": "Hello, world!"
  }
}
```

### 2. `call` (Audio)
```json
{
  "type": "call",
  "body": {
    "audio": "<base64_encoded_audio_or_audio_stream_data>"
  }
}
```

> **Note:** Payloads sent as top-level fields (e.g. `{"type": "msg", "text": "hello"}`) or under `"data"` are also automatically parsed and normalized.

---

## Running the Server

Using `uv`:

```bash
uv run python main.py
```

Environment variables:
- `WS_HOST` (default: `0.0.0.0`)
- `WS_PORT` (default: `8765`)

---

## Testing

Run the included test client script:

```bash
uv run python test_client.py
```
