# TetraCore Hub

A task hub for the TetraCore project. Clients such as the TetraCore Telegram bot send tasks
over WebSocket or REST. The hub routes each task to a connected worker, such as
[TetraCore Worker](https://github.com/BoSuY0/TetraCore_Worker), and tracks its progress and
result. Redis stores the tasks and carries messages inside the hub.

TetraCore is my learning project. I built it with the help of AI tools.

## What is in this repository

| Part | Where | Status |
| --- | --- | --- |
| Go hub | `cmd/`, `internal/`, `pkg/`, `sdk/go/`, `web/admin/` | Current version |
| Python StreamHub | `core/`, `models/`, `hub_launcher.py`, `config.py` | First version (FastAPI, asyncio) |
| Rust prototype | `rust/` | Early experiment, not finished |

## How it works

1. Clients and workers connect to `/ws` and register with a `client_registration` message.
2. A client sends a `task` message or calls `POST /api/v1/tasks`. The hub replies with `task_ack`.
3. The hub saves the task in Redis and sends it to a worker that handles this task type.
4. The worker sends `task_progress` and `task_result` messages.
   The hub forwards progress to the client and saves the result.
   The Python version also sends the result to the client over WebSocket.
   With the Go hub, the client reads it from `GET /api/v1/tasks/{id}`.

## Features of the Go hub

- WebSocket connections for clients and workers, with heartbeats and machine tokens
- JWT login with refresh tokens, and API keys
- Users, roles and permissions
- Task queue with cancel, retry and a dead-letter queue
- Task templates and a secrets store encrypted with AES-GCM
- Plugins in Lua
- Health checks (`/health`, `/ready`, `/live`) and a small admin page at `/admin/`

The code for two-factor authentication, webhooks, scheduled tasks and the audit log is in
`internal/usecase/`, but it is not connected to the HTTP API yet.

## Run the Go hub

You need Go 1.22 or newer and a Redis server on `localhost:6379`.

```bash
git clone https://github.com/BoSuY0/TetraCore_Hub.git
cd TetraCore_Hub
cp .env.example .env    # then set your own JWT_SECRET and ADMIN_PASSWORD
go run ./cmd/hub
```

Check that it works:

```bash
curl http://localhost:8000/health
```

Main settings in `.env`:

| Variable | Meaning |
| --- | --- |
| `ENVIRONMENT` | `development`, `production` or `testing` |
| `PORT` | HTTP port, `8000` by default |
| `REDIS_URL` | Redis address, for example `redis://localhost:6379` |
| `JWT_SECRET` | Secret for signing access tokens |
| `ADMIN_USERNAME`, `ADMIN_PASSWORD` | The first admin user |

## Run the Python version

You need Python 3.12 or 3.13 and the same `.env` file.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python hub_launcher.py dev
```

## Tests

```bash
go test ./...    # Go hub
pytest           # Python version
```

## Related repositories

- [TetraCore Worker](https://github.com/BoSuY0/TetraCore_Worker): a Go worker that runs tasks from this hub
- TetraCore Bot: the Telegram bot client (private for now)

## License

[MIT](LICENSE)
