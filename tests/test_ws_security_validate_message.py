import asyncio
import pytest
from types import SimpleNamespace

from core.websocket_security import WebSocketSecurityManager


class DummyWS:
    client_state = SimpleNamespace(name="CONNECTED")

    async def send_json(self, obj):
        return True


@pytest.mark.asyncio
async def test_validate_message_normalizes_flat_task_submit():
    mgr = WebSocketSecurityManager()
    # Імітуємо прийняте з'єднання
    conn = await mgr.accept_connection(
        SimpleNamespace(client=("127.0.0.1", 0), headers={}),
        {
            "user_id": "u1",
            "username": "svc",
            "permissions": ["tasks.execute"],
            "session_id": "s1",
        },
    )
    # Вкладаємо фейковий websocket
    conn.websocket = DummyWS()
    mgr.connections[conn.client_id] = conn

    flat = {
        "type": "task_submit",
        "task_id": "t-1",
        "task_type": "ping",
        "task_data": {"a": 1},
        "priority": "normal",
        "timeout": 5,
        "max_retries": 0,
        "worker_requirements": [],
        "created_at": "2025-01-01T00:00:00Z",
        "executor_type": "worker",
    }

    msg = await mgr.validate_message(conn.client_id, __import__("json").dumps(flat))
    assert msg is not None
    assert msg.type == "task_submit"
    assert isinstance(msg.data, dict)
    assert msg.data.get("task_id") == "t-1"
