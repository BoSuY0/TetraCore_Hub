import types
import time
import os
import pytest


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
