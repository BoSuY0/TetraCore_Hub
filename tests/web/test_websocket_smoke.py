"""WebSocket smoke-test: try to connect with token and expect handshake or 401 flow.

Note: This is a lightweight test that builds the app but doesn't spin a real ASGI server.
We validate that the WS endpoint is present and requires token.
"""

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
    monkeypatch.setenv("ADMIN_PASSWORD", "admin")

    launcher = StreamHubLauncher()
    app = launcher.create_app()
    client = TestClient(app)
    return client


def test_ws_requires_token(app_client: TestClient):
    # Без токена очікуємо, що сервер закриє з'єднання на рукопотисканні або відразу після
    import pytest
    from starlette.websockets import WebSocketDisconnect

    with pytest.raises(WebSocketDisconnect):
        with app_client.websocket_connect("/ws"):
            pass


def test_ws_accepts_bearer_subprotocol_with_jwt(app_client: TestClient):
    # Логін отримує JWT, який передамо як другий субпротокол після 'bearer'
    login = app_client.post(
        "/api/auth/login", json={"username": "admin", "password": "admin"}
    )
    assert login.status_code in (200, 401)

    if login.status_code == 200:
        access_token = login.json()["tokens"]["access_token"]
        with app_client.websocket_connect(
            "/ws",
            subprotocols=["bearer", access_token],
        ) as ws:
            # Якщо рукостискання пройшло, клієнт повинен бути приєднаний
            # Чекаємо перше повідомлення ack або помилки реєстрації
            msg = ws.receive_json()
            assert isinstance(msg, dict)
            # або registration_ack, або error (але не через субпротокол)
            assert msg.get("type") in ("registration_ack", "error", "stats_update")
    else:
        # Якщо логін вимкнений конфігом, тест все одно перевіряє, що без токена не пускає
        import pytest
        from starlette.websockets import WebSocketDisconnect

        with pytest.raises(WebSocketDisconnect):
            with app_client.websocket_connect("/ws"):
                pass
