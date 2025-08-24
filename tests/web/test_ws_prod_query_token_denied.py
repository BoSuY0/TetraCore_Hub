import os
import pytest
from fastapi.testclient import TestClient
import secrets
from cryptography.fernet import Fernet
from hub_launcher import StreamHubLauncher
from starlette.websockets import WebSocketDisconnect


@pytest.fixture()
def app_client(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("REQUIRE_AUTHENTICATION", "true")
    monkeypatch.setenv("DISABLE_TRUSTED_HOST_MW", "1")
    # Required secrets for production initialization
    monkeypatch.setenv("ENCRYPTION_KEY", Fernet.generate_key().decode())
    monkeypatch.setenv("JWT_SECRET_KEY", secrets.token_urlsafe(48))
    monkeypatch.setenv("JWT_REFRESH_SECRET", secrets.token_urlsafe(48))
    # Disable Redis usage in tests
    monkeypatch.setenv("REDIS_ENABLED", "false")
    monkeypatch.setenv("ADMIN_USERNAME", "admin")
    # bcrypt hash for password: TetraCore@Admin123!
    monkeypatch.setenv(
        "ADMIN_PASSWORD",
        "$2b$12$Q7prO4MIkkDY3CW5WY66aODL68ePW1VVFwYzBSb9Hk8hxc8n.baP.",
    )

    launcher = StreamHubLauncher()
    app = launcher.create_app()
    return TestClient(app)


def test_ws_query_token_denied_in_production(app_client: TestClient):
    with pytest.raises(WebSocketDisconnect):
        with app_client.websocket_connect("/ws?token=abc"):
            pass
