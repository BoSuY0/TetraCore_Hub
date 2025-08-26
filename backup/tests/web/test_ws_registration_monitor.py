import os
import secrets
import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from hub_launcher import StreamHubLauncher


@pytest.fixture()
def app_client(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("REQUIRE_AUTHENTICATION", "true")
    monkeypatch.setenv("REDIS_ENABLED", "false")
    monkeypatch.setenv("ENCRYPTION_KEY", Fernet.generate_key().decode())
    monkeypatch.setenv("JWT_SECRET_KEY", secrets.token_urlsafe(48))
    monkeypatch.setenv("JWT_REFRESH_SECRET", secrets.token_urlsafe(48))
    # Allow TestClient host
    monkeypatch.setenv("DISABLE_TRUSTED_HOST_MW", "1")
    monkeypatch.setenv("ADMIN_USERNAME", "admin")
    # bcrypt hash for password: TetraCore@Admin123!
    monkeypatch.setenv(
        "ADMIN_PASSWORD",
        "$2b$12$Q7prO4MIkkDY3CW5WY66aODL68ePW1VVFwYzBSb9Hk8hxc8n.baP.",
    )

    launcher = StreamHubLauncher()
    app = launcher.create_app()
    return TestClient(app)


def test_monitor_registration_ack_flow(app_client: TestClient):
    # Login to obtain JWT
    login = app_client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "TetraCore@Admin123!"},
    )

    assert login.status_code == 200, login.text
    access_token = login.json()["tokens"]["access_token"]

    # Open WS with bearer subprotocol and send client_registration (monitor)
    with app_client.websocket_connect(
        "/ws", subprotocols=["bearer", access_token]
    ) as ws:
        # Надішлемо реєстраційне повідомлення monitor-клієнта
        reg = {
            "type": "client_registration",
            "client_type": "monitor",
            "client_id": "test-dashboard",
            "client_name": "PyTest Dashboard",
            "client_version": "1.0.0",
            "capabilities": [],
            "max_concurrent_tasks": 1,
            "auth_token": access_token,
            "client_info": {"test": True},
        }
        ws.send_json(reg)
        msg = ws.receive_json()
        assert isinstance(msg, dict)
        # Очікуємо або миттєвий ack, або системні оновлення, але ack має з’явитися першими
        assert msg.get("type") in (
            "registration_ack",
            "stats_update",
            "system_notification",
        )
