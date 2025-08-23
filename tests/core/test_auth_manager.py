import importlib
import pytest


@pytest.fixture(autouse=True)
def setup_env(monkeypatch):
    # Базове оточення для відтворюваних тестів
    monkeypatch.setenv("ENVIRONMENT", "development")
    monkeypatch.setenv("DISABLE_BACKGROUND_TASKS", "1")
    monkeypatch.setenv("JWT_SECRET_KEY", "jwt-secret-key-for-tests-1234567890!!!!")
    monkeypatch.setenv("JWT_REFRESH_SECRET", "jwt-refresh-secret-for-tests-0987654321!!!!")
    monkeypatch.setenv("ENCRYPTION_KEY", "StrongP@sswordKey_123!_For_Tests")
    monkeypatch.setenv("ADMIN_USERNAME", "admin")
    monkeypatch.setenv("ADMIN_PASSWORD", "Str0ngAdm!nPass")

    # Перезавантажити модуль секретів і скинути глобальний стан
    import core.secrets_manager as sm
    importlib.reload(sm)
    try:
        sm._secrets_manager = None  # type: ignore[attr-defined]
    except Exception:
        pass


def _new_auth_manager():
    import core.auth_manager as am
    importlib.reload(am)
    return am.AuthManager(redis_client=None)


def test_password_hash_and_verify():
    am = _new_auth_manager()
    password = "my-Super_Passw0rd!"
    hashed = am.hash_password(password)
    assert isinstance(hashed, str) and hashed.startswith("$2")
    assert am.verify_password(password, hashed) is True
    assert am.verify_password("wrong-pass", hashed) is False


@pytest.mark.anyio
async def test_create_and_decode_access_token():
    am = _new_auth_manager()
    token = am.create_access_token({
        "user_id": "u1",
        "username": "john",
        "role": "admin",
        "permissions": ["*"],
    })
    payload = await am.decode_token(token, token_type="access")
    assert payload["user_id"] == "u1"
    assert payload["token_type"] == "access"
    assert payload["boot_id"] == am.server_boot_id


@pytest.mark.anyio
async def test_refresh_flow_without_redis():
    am = _new_auth_manager()
    user = {"id": "u2", "username": "alice", "role": "admin", "permissions": ["*"]}
    pair = await am.create_token_pair(user)
    assert pair.access_token and pair.refresh_token

    new_pair = await am.refresh_access_token(pair.refresh_token)
    assert new_pair.access_token and new_pair.refresh_token


@pytest.mark.anyio
async def test_revoke_token_blocks_decoding():
    am = _new_auth_manager()
    token = am.create_access_token({"user_id": "u3", "username": "kate", "role": "admin", "permissions": ["*"]})
    am.revoke_token(token)
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as ei:
        await am.decode_token(token, token_type="access")
    assert ei.value.status_code == 401


def test_login_attempts_rate_limit():
    am = _new_auth_manager()
    user = "tester"
    ip = "192.168.1.10"

    assert am.check_login_attempts(user, ip) is True

    from core.auth_manager import MAX_LOGIN_ATTEMPTS
    for _ in range(MAX_LOGIN_ATTEMPTS):
        am.record_login_attempt(user, ip, success=False)

    assert am.check_login_attempts(user, ip) is False


