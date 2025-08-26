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


def test_api_health_metrics_clients(app_client: TestClient):
    # Health без токена має вимагати авторизацію або бути публічним (перевіряємо статус)
    r1 = app_client.get("/api/health")
    assert r1.status_code in (200, 401)

    # Логін
    login = app_client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "TetraCore@Admin123!"},
    )

    assert login.status_code == 200

    # Після логіну endpoints мають відповідати 200
    r2 = app_client.get("/api/metrics")
    assert r2.status_code == 200

    r3 = app_client.get("/api/clients")
    assert r3.status_code in (200, 204)
    if r3.status_code == 200:
        assert isinstance(r3.json(), list)
