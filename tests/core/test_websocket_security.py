import types
import time
import os
import pytest
import secrets
import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from hub_launcher import StreamHubLauncher


class FakeClient:
    def __init__(self, host: str = "127.0.0.1"):
        self.host = host


class FakeWebSocket:
    def __init__(self, headers: dict | None = None, host: str = "127.0.0.1"):
        self.headers = types.MappingProxyType(headers or {})
        self.client = FakeClient(host)

    async def close(self, code: int = 1000, reason: str = ""):
        return

    async def send_json(self, data: dict):
        return


def _make_hmac_headers(
    secret: str, client_id: str = "client-1", client_type: str = "worker"
) -> dict:
    ts = str(int(time.time()))
    nonce = "nonce-test"
    canonical = f"{client_id}|{ts}|{nonce}|{client_type}|1.0.0"
    import hmac, hashlib

    sig = hmac.new(
        secret.encode("utf-8"), canonical.encode("utf-8"), hashlib.sha256
    ).hexdigest()
    return {
        "Authorization": f"Bearer {secret}",
        "X-Client-Id": client_id,
        "X-Timestamp": ts,
        "X-Nonce": nonce,
        "X-Client-Type": client_type,
        "X-Client-Version": "1.0.0",
        "X-Signature": sig,
    }


@pytest.fixture(autouse=True)
def env_setup(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "development")
    monkeypatch.setenv("AUTH_TOKEN", "super-secret-token-1234567890")


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
    # bcrypt hash for password: TetraCore@Admin123!
    monkeypatch.setenv(
        "ADMIN_PASSWORD",
        "$2b$12$Q7prO4MIkkDY3CW5WY66aODL68ePW1VVFwYzBSb9Hk8hxc8n.baP.",
    )

    launcher = StreamHubLauncher()
    app = launcher.create_app()
    return TestClient(app)


@pytest.mark.anyio
async def test_guest_access_in_dev():
    from core import websocket_security as ws_mod

    ws_mod.ws_security_manager = ws_mod.WebSocketSecurityManager()
    ws = FakeWebSocket(headers={})
    res = await ws_mod.ws_security_manager.authenticate_websocket(ws, token=None)
    assert res is not None and res["username"] == "guest"


@pytest.mark.anyio
async def test_hmac_authentication_succeeds_with_static_token():
    from core import websocket_security as ws_mod

    ws_mod.ws_security_manager = ws_mod.WebSocketSecurityManager()
    secret = os.environ.get("AUTH_TOKEN")
    headers = _make_hmac_headers(secret, client_id="svc-1", client_type="worker")
    ws = FakeWebSocket(headers=headers)
    res = await ws_mod.ws_security_manager.authenticate_websocket(ws, token=None)
    assert res is not None and res["role"] == "service"


def test_ws_subprotocol_jwt_authentication(app_client_prod: TestClient):
    # Отримати токен
    login = app_client_prod.post(
        "/api/auth/login",
        json={"username": "admin", "password": "TetraCore@Admin123!"},
    )
    assert login.status_code == 200
    access_token = login.json()["tokens"]["access_token"]

    # Підключитися з subprotocols = ["bearer", token]
    with app_client_prod.websocket_connect(
        "/ws", subprotocols=["bearer", access_token]
    ) as ws:
        # очікуємо перше повідомлення
        data = ws.receive_json()
        assert isinstance(data, dict)
        assert data.get("type") in (
            "registration_ack",
            "stats_update",
            "system_notification",
            "error",
        )


def test_ws_query_token_is_denied_in_production(app_client_prod: TestClient):
    import pytest
    from starlette.websockets import WebSocketDisconnect

    with pytest.raises(WebSocketDisconnect):
        with app_client_prod.websocket_connect("/ws?token=abc"):
            pass
