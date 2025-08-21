import pytest
from core.websocket_security import WebSocketSecurityManager, ClientRegistrationMessage, TaskSubmitMessage


@pytest.mark.asyncio
async def test_security_accepts_flat_and_nested_messages():
    mgr = WebSocketSecurityManager()

    # Плоский client_registration
    flat_reg = {
        "type": "client_registration",
        "client_id": "c1",
        "client_type": "worker_api",
        "client_name": "API",
        "client_version": "1.0.0"
    }

    # Вкладений client_registration
    nested_reg = {
        "type": "client_registration",
        "data": {
            "client_id": "c2",
            "client_type": "worker_api",
            "client_name": "API",
            "client_version": "1.0.0"
        }
    }

    # Вкладений task_submit
    nested_submit = {
        "type": "task_submit",
        "data": {
            "task_id": "t1",
            "task_type": "ping",
            "task_data": {"a": 1},
            "priority": "normal",
            "timeout": 10,
            "max_retries": 1,
            "worker_requirements": [],
            "created_at": "2025-01-01T00:00:00Z",
            "executor_type": "worker"
        }
    }

    # Плоский task_submit (має бути нормалізований у validate_message)
    flat_submit = {
        "type": "task_submit",
        "task_id": "t2",
        "task_type": "ping",
        "task_data": {"a": 2},
        "priority": "normal",
        "timeout": 10,
        "max_retries": 1,
        "worker_requirements": [],
        "created_at": "2025-01-01T00:00:00Z",
        "executor_type": "worker"
    }

    # Перевіряємо конструктори моделей напряму (без websocket)
    assert isinstance(ClientRegistrationMessage(**nested_reg), ClientRegistrationMessage)
    # Плоский client_registration має бути прийнятий через validate_message, тут він викличе ValueError
    with pytest.raises(Exception):
        ClientRegistrationMessage(**flat_reg)

    assert isinstance(TaskSubmitMessage(**nested_submit), TaskSubmitMessage)
    # Плоский task_submit так само напряму викличе ValueError
    with pytest.raises(Exception):
        TaskSubmitMessage(**flat_submit)

