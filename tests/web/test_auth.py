"""Auth integration tests: bcrypt hash + login flow."""
import os
import pytest
from fastapi.testclient import TestClient

from hub_launcher import StreamHubLauncher


@pytest.fixture()
def app_with_auth(monkeypatch):
    # Minimal secure configuration for auth endpoints
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("SECRET_PROVIDER", "env")
    monkeypatch.setenv("REQUIRE_AUTHENTICATION", "true")

    # JWT and encryption keys (test-only values)
    monkeypatch.setenv("ENCRYPTION_KEY", "oNzmRFrNzXqkj00TCa8jY7MJX39HWSoiVnf2WlnXVTg=")
    monkeypatch.setenv("JWT_SECRET_KEY", "test-jwt-secret-key-32chars-long-1234567890")
    monkeypatch.setenv("JWT_REFRESH_SECRET", "test-refresh-secret-key-32chars-long-1234567890")
    # Allow TestClient host
    monkeypatch.setenv("DISABLE_TRUSTED_HOST_MW", "1")

    # Admin creds: use bcrypt hash (12 rounds) for password "TetraCore@Admin123!"
    # If you need a new hash, generate via: python -c "import bcrypt; print(bcrypt.hashpw(b'TetraCore@Admin123!', bcrypt.gensalt(12)).decode())"
    monkeypatch.setenv("ADMIN_USERNAME", "admin")
    monkeypatch.setenv("ADMIN_PASSWORD", "$2b$12$Q7prO4MIkkDY3CW5WY66aODL68ePW1VVFwYzBSb9Hk8hxc8n.baP.")

    # Redis disabled for this test
    monkeypatch.setenv("REDIS_ENABLED", "false")

    launcher = StreamHubLauncher()
    app = launcher.create_app()
    client = TestClient(app)
    return client


def test_login_with_bcrypt_success(app_with_auth: TestClient):
    resp = app_with_auth.post(
        "/api/auth/login",
        json={"username": "admin", "password": "TetraCore@Admin123!"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data.get("success") is True
    assert "tokens" in data and data["tokens"].get("access_token")


def test_login_wrong_password(app_with_auth: TestClient):
    resp = app_with_auth.post(
        "/api/auth/login",
        json={"username": "admin", "password": "wrongpass"},
    )
    assert resp.status_code == 401
