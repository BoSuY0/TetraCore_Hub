import importlib
import pytest


@pytest.fixture(autouse=True)
def env_setup(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "development")
    monkeypatch.setenv("DISABLE_BACKGROUND_TASKS", "1")
    monkeypatch.setenv("ENCRYPTION_KEY", "StrongP@sswordKey_123!_For_Tests")
    monkeypatch.setenv("JWT_SECRET_KEY", "jwt-secret-key-for-tests-1234567890!!!!")
    monkeypatch.setenv(
        "JWT_REFRESH_SECRET", "jwt-refresh-secret-for-tests-0987654321!!!!"
    )
    monkeypatch.setenv("ADMIN_USERNAME", "admin")
    monkeypatch.setenv("ADMIN_PASSWORD", "Str0ngAdm!nPass")

    import core.secrets_manager as sm

    importlib.reload(sm)
    try:
        sm._secrets_manager = None  # type: ignore[attr-defined]
    except Exception:
        pass


def _manager(provider=None):
    import core.secrets_manager as sm

    importlib.reload(sm)
    return sm.SecretsManager(provider=provider)


def test_encrypt_decrypt_round_trip(tmp_path):
    sm = _manager()
    data = "sensitive-data-äö"
    enc = sm.encrypt_data(data)
    assert isinstance(enc, bytes)
    dec = sm.decrypt_data(enc).decode("utf-8")
    assert dec == data


def test_get_set_rotate_secret_memory_provider():
    from core.secrets_manager import SecretProvider

    sm = _manager(provider=SecretProvider.MEMORY)
    sm.set_secret("CUSTOM_KEY", "value-1", persist=False)
    assert sm.get_secret("CUSTOM_KEY") == "value-1"

    new_val = sm.rotate_secret("JWT_SECRET_KEY")
    assert isinstance(new_val, str) and new_val


def test_status_and_required_loaded():
    sm = _manager()
    status = sm.get_status()
    assert status["encryption_initialized"] is True
    assert status["total_secrets"] >= 3
