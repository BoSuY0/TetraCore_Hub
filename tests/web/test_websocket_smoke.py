"""WebSocket smoke-test: try to connect with token and expect handshake or 401 flow.

Note: This is a lightweight test that builds the app but doesn't spin a real ASGI server.
We validate that the WS endpoint is present and requires token.
"""
import os
import pytest
from fastapi.testclient import TestClient

from hub_launcher import StreamHubLauncher


@pytest.fixture()
def app_client(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "development")
    monkeypatch.setenv("REQUIRE_AUTHENTICATION", "true")
    monkeypatch.setenv("REDIS_ENABLED", "false")
    monkeypatch.setenv("ENCRYPTION_KEY", "oNzmRFrNzXqkj00TCa8jY7MJX39HWSoiVnf2WlnXVTg=")
    monkeypatch.setenv("JWT_SECRET_KEY", "test-jwt-secret-key-32chars-long-1234567890")
    monkeypatch.setenv("JWT_REFRESH_SECRET", "test-refresh-secret-key-32chars-long-1234567890")
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


