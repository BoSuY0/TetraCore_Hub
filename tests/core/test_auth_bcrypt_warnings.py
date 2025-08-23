"""
Тести для перевірки відсутності попереджень bcrypt
"""

import pytest
import warnings
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
    with patch('core.auth_manager.get_secrets_manager', return_value=mock_secrets_manager):
        return AuthManager()


def test_no_bcrypt_warnings_on_hash(auth_manager, caplog):
    """Тест що hash_password не генерує попереджень про bcrypt"""
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        
        # Хешуємо пароль
        hashed = auth_manager.hash_password("test_password")
        
        # Перевіряємо що хеш створено
        assert hashed is not None
        assert hashed.startswith("$2")
        
        # Перевіряємо що немає попереджень про bcrypt
        bcrypt_warnings = [
            warning for warning in w 
            if "bcrypt" in str(warning.message).lower()
        ]
        assert len(bcrypt_warnings) == 0, f"Знайдено попередження про bcrypt: {bcrypt_warnings}"
        
        # Також перевіряємо логи
        assert "error reading bcrypt version" not in caplog.text
        assert "detected 'bcrypt' backend" not in caplog.text


def test_no_bcrypt_warnings_on_verify(auth_manager, caplog):
    """Тест що verify_password не генерує попереджень про bcrypt"""
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        
        # Спочатку хешуємо пароль
        hashed = auth_manager.hash_password("test_password")
        
        # Потім перевіряємо його
        result = auth_manager.verify_password("test_password", hashed)
        
        # Перевіряємо що пароль правильний
        assert result is True
        
        # Перевіряємо що немає попереджень про bcrypt
        bcrypt_warnings = [
            warning for warning in w 
            if "bcrypt" in str(warning.message).lower()
        ]
        assert len(bcrypt_warnings) == 0, f"Знайдено попередження про bcrypt: {bcrypt_warnings}"
        
        # Також перевіряємо логи
        assert "error reading bcrypt version" not in caplog.text
        assert "detected 'bcrypt' backend" not in caplog.text
        assert "backend lacks" not in caplog.text


def test_password_functionality_works(auth_manager):
    """Тест що функціонал паролів працює коректно"""
    password = "my_secure_password_123!"
    
    # Хешуємо пароль
    hashed = auth_manager.hash_password(password)
    
    # Перевіряємо правильний пароль
    assert auth_manager.verify_password(password, hashed) is True
    
    # Перевіряємо неправильний пароль
    assert auth_manager.verify_password("wrong_password", hashed) is False
    
    # Перевіряємо що різні паролі дають різні хеші
    hashed2 = auth_manager.hash_password("different_password")
    assert hashed != hashed2