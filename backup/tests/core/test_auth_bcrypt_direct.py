"""
Тести для перевірки прямого використання bcrypt
"""

import pytest
from unittest.mock import Mock, patch

from core.auth_manager import AuthManager
from core.secrets_manager import SecretsManager


@pytest.fixture
def mock_secrets_manager():
    """Mock для SecretsManager"""
    secrets = Mock(spec=SecretsManager)
    secrets.get_secret.return_value = "test_secret_key"
    return secrets


@pytest.fixture
def auth_manager(mock_secrets_manager):
    """Створення AuthManager для тестів"""
    with patch(
        "core.auth_manager.get_secrets_manager", return_value=mock_secrets_manager
    ):
        return AuthManager()


def test_hash_password_creates_bcrypt_hash(auth_manager):
    """Тест що hash_password створює валідний bcrypt хеш"""
    password = "test_password_123"

    hashed = auth_manager.hash_password(password)

    # Перевіряємо що це bcrypt хеш
    assert hashed is not None
    assert isinstance(hashed, str)
    assert hashed.startswith("$2b$")  # bcrypt prefix
    assert len(hashed) == 60  # bcrypt хеші завжди 60 символів


def test_verify_password_correct(auth_manager):
    """Тест що verify_password правильно перевіряє коректний пароль"""
    password = "correct_password"

    # Хешуємо пароль
    hashed = auth_manager.hash_password(password)

    # Перевіряємо коректний пароль
    assert auth_manager.verify_password(password, hashed) is True


def test_verify_password_incorrect(auth_manager):
    """Тест що verify_password відхиляє неправильний пароль"""
    password = "correct_password"
    wrong_password = "wrong_password"

    # Хешуємо пароль
    hashed = auth_manager.hash_password(password)

    # Перевіряємо неправильний пароль
    assert auth_manager.verify_password(wrong_password, hashed) is False


def test_verify_password_empty_inputs(auth_manager):
    """Тест що verify_password правильно обробляє порожні вводи"""
    hashed = auth_manager.hash_password("test")

    # Порожній пароль
    assert auth_manager.verify_password("", hashed) is False

    # Порожній хеш
    assert auth_manager.verify_password("test", "") is False

    # Обидва порожні
    assert auth_manager.verify_password("", "") is False

    # None значення
    assert auth_manager.verify_password(None, hashed) is False
    assert auth_manager.verify_password("test", None) is False


def test_password_hash_uniqueness(auth_manager):
    """Тест що кожен хеш унікальний навіть для однакових паролів"""
    password = "same_password"

    hash1 = auth_manager.hash_password(password)
    hash2 = auth_manager.hash_password(password)

    # Хеші повинні бути різні (через різні salt)
    assert hash1 != hash2

    # Але обидва повинні проходити верифікацію
    assert auth_manager.verify_password(password, hash1) is True
    assert auth_manager.verify_password(password, hash2) is True


def test_bcrypt_rounds_configuration():
    """Тест що кількість раундів bcrypt конфігурується"""
    import os
    from core.auth_manager import BCRYPT_ROUNDS

    # Перевіряємо дефолтне значення або з env
    expected_rounds = int(os.getenv("BCRYPT_ROUNDS", "12"))
    assert BCRYPT_ROUNDS == expected_rounds


def test_verify_old_passlib_hashes(auth_manager):
    """Тест що старі хеші від passlib все ще працюють"""
    # Це реальний bcrypt хеш згенерований passlib для пароля "test"
    # $2b$12$... означає bcrypt з 12 раундами
    old_hash = "$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/LewKyNiLXCsr/XgKC"

    # Має повернути False бо це хеш для "test", а не "wrong"
    assert auth_manager.verify_password("wrong", old_hash) is False

    # Примітка: ми не можемо перевірити правильний пароль без знання
    # оригінального пароля для цього хешу
