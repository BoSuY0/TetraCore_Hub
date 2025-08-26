"""Basic smoke tests for health and protected endpoints."""

import os
import secrets
import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from hub_launcher import StreamHubLauncher


@pytest.fixture()
def app_client(monkeypatch):
    # Minimal app for testing
    monkeypatch.setenv("ENVIRONMENT", "development")
    monkeypatch.setenv("REQUIRE_AUTHENTICATION", "true")
    monkeypatch.setenv("REDIS_ENABLED", "false")
    monkeypatch.setenv("ENCRYPTION_KEY", Fernet.generate_key().decode())
    monkeypatch.setenv("JWT_SECRET_KEY", secrets.token_urlsafe(48))
    monkeypatch.setenv("JWT_REFRESH_SECRET", secrets.token_urlsafe(48))
    # Allow TestClient host
    monkeypatch.setenv("DISABLE_TRUSTED_HOST_MW", "1")
    monkeypatch.setenv("ADMIN_USERNAME", "admin")
    monkeypatch.setenv("ADMIN_PASSWORD", "admin")  # dev allows plain for convenience

    launcher = StreamHubLauncher()
    app = launcher.create_app()
    client = TestClient(app)
    return client


def test_health_public(app_client: TestClient):
    r = app_client.get("/api/health")
    assert r.status_code in (200, 401, 403)


def test_protected_clients_requires_token(app_client: TestClient):
    r = app_client.get("/api/clients")
    # Should be unauthorized without token
    assert r.status_code == 401
