import secrets
import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from hub_launcher import StreamHubLauncher


@pytest.fixture()
def app_client_prod(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("REQUIRE_AUTHENTICATION", "true")
    monkeypatch.setenv("REDIS_ENABLED", "false")
    monkeypatch.setenv("ENCRYPTION_KEY", Fernet.generate_key().decode())
    monkeypatch.setenv("JWT_SECRET_KEY", secrets.token_urlsafe(48))
    monkeypatch.setenv("JWT_REFRESH_SECRET", secrets.token_urlsafe(48))
    # Allow TestClient host
    monkeypatch.setenv("DISABLE_TRUSTED_HOST_MW", "1")
    monkeypatch.setenv("ADMIN_USERNAME", "admin")
    monkeypatch.setenv("ADMIN_PASSWORD", "admin")

    launcher = StreamHubLauncher()
    app = launcher.create_app()
    return TestClient(app)


def test_authenticate_monitor_by_ws_jwt(app_client_prod: TestClient):
    # Монітор має бути авторизований JWT, без перевірки hub auth_token
    login = app_client_prod.post(
        "/api/auth/login", json={"username": "admin", "password": "admin"}
    )
    assert login.status_code == 200
    access_token = login.json()["tokens"]["access_token"]

    with app_client_prod.websocket_connect(
        "/ws", subprotocols=["bearer", access_token]
    ) as ws:
        reg = {
            "type": "client_registration",
            "client_type": "monitor",
            "client_id": "m1",
            "client_name": "Dash",
            "client_version": "1.0.0",
            "auth_token": None,
        }
        ws.send_json(reg)
        data = ws.receive_json()
        assert data.get("type") in ("registration_ack", "stats_update", "system_notification")


def test_invalid_client_type_gets_error(app_client_prod: TestClient):
    # При неправильному client_type очікуємо error
    login = app_client_prod.post(
        "/api/auth/login", json={"username": "admin", "password": "admin"}
    )
    assert login.status_code == 200
    access_token = login.json()["tokens"]["access_token"]

    with app_client_prod.websocket_connect(
        "/ws", subprotocols=["bearer", access_token]
    ) as ws:
        reg = {
            "type": "client_registration",
            "client_type": "unknown-type",
            "client_id": "x1",
            "client_name": "X",
            "client_version": "1.0.0",
            "auth_token": access_token,
        }
        ws.send_json(reg)
        data = ws.receive_json()
        assert data.get("type") == "error"
        assert data.get("error_code") == "INVALID_CLIENT_TYPE"