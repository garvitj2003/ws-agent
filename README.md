# WebSocket Agent Hub (`ws-agent`)

A lightweight asynchronous WebSocket Agent Hub built with `uv`, `websockets` (Python 3.13+), `SQLAlchemy 2.0`, `PostgreSQL`, and `Alembic`.

## Architecture & Capabilities

1. **Multi-Device Routing Mesh**: Point-to-point, role targeting (`mobile`, `laptop`), and broadcast (`*`).
2. **Standard Protocol Envelope**: Strict contract with `id`, `type`, `timestamp`, `source`, `target`, and `body`.
3. **Database & Action System**:
   - Hybrid DB architecture: Strongly-typed action handlers (`reminder.*`, `task.*`, `event.*`) + sandboxed read-only SQL execution (`query.sql`).
   - Reminders lifecycle: `pending` -> `triggered` -> `completed` / `dismissed` / `cancelled`.
   - Dedicated PostgreSQL database mapped to port **`5435`** to prevent any port collisions on shared servers.

---

## Protocol Envelope Contract

```json
{
  "id": "uuid-v4",
  "type": "msg | call | register | action | action_result | ack | ping",
  "timestamp": "2026-09-19T15:49:42.000Z",
  "source": "mobile:garvit-phone",
  "target": "server",
  "body": {
    "action": "reminder.create",
    "data": {
      "title": "Call Mom",
      "scheduledAt": "2026-09-20T20:00:00+05:30"
    }
  }
}
```

---

## Action Domains

### 1. Reminders (`reminder.*`)
- `reminder.create`: Sets scheduled reminder (initial status: `pending`). Spawns async background trigger timer.
- `reminder.get`: Get reminder by ID.
- `reminder.list`: List reminders (filter by status `pending`, `dismissed`, etc.).
- `reminder.dismiss`: Mark reminder as `dismissed`.
- `reminder.complete`: Mark reminder as `completed`.
- `reminder.delete`: Delete reminder.

### 2. Tasks (`task.*`)
- `task.create`: Create todo task with priority (`low`, `medium`, `high`, `urgent`).
- `task.get`: Get task by ID.
- `task.list`: List tasks (filter by `status`, `priority`).
- `task.complete`: Mark task completed.
- `task.delete`: Delete task.

### 3. Events (`event.*`)
- `event.create`: Create calendar event.
- `event.list`: List upcoming events.
- `event.delete`: Delete event.

### 4. Sandboxed Read-Only SQL (`query.sql`)
- `query.sql`: Executes safe read-only queries with AST validation and a 3-second statement timeout.

---

## Running with Docker Compose

Starts both PostgreSQL (port `5435`) and the WebSocket Agent Server (port `8765`):

```bash
docker compose up -d --build
```

View logs:
```bash
docker compose logs -f
```

---

## Testing

Run the automated integration test suite:

```bash
uv run python test_client.py
```
