import os
import time
import json
import asyncio
import types

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


@pytest.fixture(autouse=True)
def reset_env(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.delenv("HUB_AUTH_TOKEN", raising=False)
    monkeypatch.delenv("AUTH_TOKEN_ACTIVE", raising=False)
    monkeypatch.delenv("AUTH_TOKEN_NEXT", raising=False)
    monkeypatch.setenv("AUTH_TOKEN", "super-secret-token-1234567890")
    yield


@pytest.fixture()
def ws_sec(monkeypatch):
    # Ініціалізуємо заново менеджер безпеки з чистим станом
    from core import websocket_security as ws_mod
    # Пересоздаємо інстанс
    ws_mod.ws_security_manager = ws_mod.WebSocketSecurityManager()
    mgr = ws_mod.ws_security_manager
    # Налаштовуємо суворіші ліміти для швидких тестів
    mgr._conn_max_per_window = 2
    mgr._conn_window_seconds = 60
    mgr._used_nonces.clear()
    return mgr


def _make_hmac_headers(secret: str, client_id: str = "client-1", client_type: str = "worker") -> dict:
    ts = str(int(time.time()))
    nonce = "fixed-nonce-for-test"  # фіксовано для керованих тестів (replay)
    canonical = f"{client_id}|{ts}|{nonce}|{client_type}|1.0.0"
    import hmac, hashlib
    sig = hmac.new(secret.encode("utf-8"), canonical.encode("utf-8"), hashlib.sha256).hexdigest()
    return {
        "Authorization": f"Bearer {secret}",
        "X-Client-Id": client_id,
        "X-Timestamp": ts,
        "X-Nonce": nonce,
        "X-Client-Type": client_type,
        "X-Client-Version": "1.0.0",
        "X-Signature": sig,
    }


@pytest.mark.anyio
async def test_query_token_rejected_in_production(ws_sec, monkeypatch):
    # Запит з токеном у query має бути відхилений у проді
    ws = FakeWebSocket(headers={})
    res = await ws_sec.authenticate_websocket(ws, token="token-in-query")
    assert res is None


@pytest.mark.anyio
async def test_bearer_with_valid_hmac_succeeds(ws_sec, monkeypatch):
    secret = os.environ.get("AUTH_TOKEN")
    headers = _make_hmac_headers(secret, client_id="svc-1", client_type="worker")
    ws = FakeWebSocket(headers=headers)
    res = await ws_sec.authenticate_websocket(ws, token=None)
    assert res is not None
    assert res["user_id"] == "svc-1"
    assert res["role"] == "service"


@pytest.mark.anyio
async def test_invalid_signature_fails(ws_sec, monkeypatch):
    secret = os.environ.get("AUTH_TOKEN")
    headers = _make_hmac_headers(secret, client_id="svc-2", client_type="worker")
    # Ламаємо підпис
    headers["X-Signature"] = "deadbeef"
    ws = FakeWebSocket(headers=headers)
    res = await ws_sec.authenticate_websocket(ws, token=None)
    assert res is None


@pytest.mark.anyio
async def test_expired_timestamp_fails(ws_sec, monkeypatch):
    secret = os.environ.get("AUTH_TOKEN")
    # Робимо вручну заголовки з простроченим timestamp
    old_ts = str(int(time.time()) - 3600)
    client_id = "svc-3"
    nonce = "nonce-expired"
    canonical = f"{client_id}|{old_ts}|{nonce}|worker|1.0.0"
    import hmac, hashlib
    sig = hmac.new(secret.encode("utf-8"), canonical.encode("utf-8"), hashlib.sha256).hexdigest()
    headers = {
        "Authorization": f"Bearer {secret}",
        "X-Client-Id": client_id,
        "X-Timestamp": old_ts,
        "X-Nonce": nonce,
        "X-Client-Type": "worker",
        "X-Client-Version": "1.0.0",
        "X-Signature": sig,
    }
    ws = FakeWebSocket(headers=headers)
    res = await ws_sec.authenticate_websocket(ws, token=None)
    assert res is None


@pytest.mark.anyio
async def test_replay_nonce_fails(ws_sec, monkeypatch):
    secret = os.environ.get("AUTH_TOKEN")
    headers = _make_hmac_headers(secret, client_id="svc-4", client_type="worker")
    ws1 = FakeWebSocket(headers=headers)
    res1 = await ws_sec.authenticate_websocket(ws1, token=None)
    assert res1 is not None

    # Повторюємо з тим самим nonce
    ws2 = FakeWebSocket(headers=headers)
    res2 = await ws_sec.authenticate_websocket(ws2, token=None)
    assert res2 is None


@pytest.mark.anyio
async def test_rate_limit_ip(ws_sec, monkeypatch):
    ws_sec._conn_max_per_window = 1
    secret = os.environ.get("AUTH_TOKEN")
    headers = _make_hmac_headers(secret, client_id="svc-5", client_type="worker")
    ws1 = FakeWebSocket(headers=headers, host="10.0.0.1")
    ws2 = FakeWebSocket(headers=headers, host="10.0.0.1")
    res1 = await ws_sec.authenticate_websocket(ws1, token=None)
    res2 = await ws_sec.authenticate_websocket(ws2, token=None)
    assert res1 is not None
    assert res2 is None  # перевищили ліміт підключень з IP


@pytest.mark.anyio
async def test_rate_limit_token(ws_sec, monkeypatch):
    ws_sec._conn_max_per_window = 1
    secret = os.environ.get("AUTH_TOKEN")
    headers = _make_hmac_headers(secret, client_id="svc-6", client_type="worker")
    ws1 = FakeWebSocket(headers=headers, host="10.0.0.2")
    ws2 = FakeWebSocket(headers=headers, host="10.0.0.3")  # інший IP, той самий токен
    res1 = await ws_sec.authenticate_websocket(ws1, token=None)
    res2 = await ws_sec.authenticate_websocket(ws2, token=None)
    assert res1 is not None
    assert res2 is None  # перевищили ліміт по токену


@pytest.mark.anyio
async def test_dev_guest_access(monkeypatch):
    # У development без токена пускаємо гостей
    monkeypatch.setenv("ENVIRONMENT", "development")
    from core import websocket_security as ws_mod
    ws_mod.ws_security_manager = ws_mod.WebSocketSecurityManager()
    ws = FakeWebSocket(headers={})
    res = await ws_mod.ws_security_manager.authenticate_websocket(ws, token=None)
    assert res is not None
    assert res["username"] == "guest"


@pytest.mark.anyio
async def test_validate_message_size_limit(monkeypatch):
    from core.websocket_security import WebSocketSecurityManager, ConnectionInfo
    mgr = WebSocketSecurityManager()
    ws = FakeWebSocket()
    conn = ConnectionInfo(ws, user_id="u1", client_id="c1")
    mgr.connections["c1"] = conn
    # Формуємо JSON > 256KB
    big_data = {"type": "ping", "data": {"x": "a" * (300 * 1024)}}
    raw = json.dumps(big_data)
    msg = await mgr.validate_message("c1", raw)
    assert msg is None

"""
Unit tests for the core.websocket_security module.
"""
import pytest

# TODO: Add necessary imports from 'core.websocket_security'

def test_placeholder():
    """
    A placeholder test.
    TODO: Replace this with actual tests for the module.
    """
    assert True
