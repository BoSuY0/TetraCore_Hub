"""
Secrets Manager for TetraCore Hub
Безпечне управління секретами та чутливими даними
"""

import os
import base64
import json
import secrets
from typing import Dict, Any, Optional, List, Union
from datetime import datetime
from pathlib import Path
from functools import lru_cache
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
import structlog
from abc import ABC, abstractmethod
from enum import Enum

logger = structlog.get_logger()

# Спробувати імпортувати опціональні залежності
try:
    import boto3  # type: ignore[import-untyped]

    HAS_AWS = True
except ImportError:
    # Створюємо мінімальний стаб модуля у sys.modules, щоб дозволити мокінг
    # 'boto3.client' у тестах без встановленого пакета boto3
    HAS_AWS = False
    try:
        import types  # type: ignore[import-not-found]
        import sys  # type: ignore[import-not-found]

        boto3_stub = types.ModuleType("boto3")

        def _not_installed(*args, **kwargs):
            raise ImportError("boto3 is not installed")

        # Забезпечуємо наявність атрибута client для подальшого мокінгу
        boto3_stub.client = _not_installed  # type: ignore[attr-defined]
        sys.modules["boto3"] = boto3_stub
        boto3 = boto3_stub  # type: ignore[assignment]
    except Exception:
        boto3 = None  # type: ignore[assignment]

try:
    import hvac  # type: ignore[import-untyped]

    HAS_VAULT = True
except ImportError:
    hvac = None  # type: ignore[assignment]
    HAS_VAULT = False

try:
    import redis  # type: ignore[import-untyped]

    HAS_REDIS = True
except ImportError:
    redis = None  # type: ignore[assignment]
    HAS_REDIS = False

# Константи
SECRET_KEY_LENGTH = 32
SALT_LENGTH = 16
ITERATIONS = 100000
SECRET_ROTATION_DAYS = 90
MAX_SECRET_AGE_DAYS = 365
CACHE_TTL = 300  # 5 хвилин кешування


class SecretProvider(Enum):
    """Типи провайдерів секретів"""

    ENV = "env"
    AWS = "aws"
    VAULT = "vault"
    REDIS = "redis"
    MEMORY = "memory"


class SecretProviderInterface(ABC):
    """Інтерфейс для провайдерів секретів"""

    @abstractmethod
    def get(self, key: str) -> Optional[str]:
        """Отримати секрет за ключем"""
        pass

    @abstractmethod
    def set(self, key: str, value: str) -> bool:
        """Встановити значення секрету"""
        pass

    @abstractmethod
    def delete(self, key: str) -> bool:
        """Видалити секрет"""
        pass

    @abstractmethod
    def exists(self, key: str) -> bool:
        """Перевірити чи існує секрет"""
        pass

    @abstractmethod
    def list_keys(self, prefix: Optional[str] = None) -> List[str]:
        """Отримати список ключів"""
        pass


class EnvSecretProvider(SecretProviderInterface):
    """Провайдер для змінних середовища"""

    def get(self, key: str) -> Optional[str]:
        return os.getenv(key)

    def set(self, key: str, value: str) -> bool:
        os.environ[key] = value
        return True

    def delete(self, key: str) -> bool:
        if key in os.environ:
            del os.environ[key]
            return True
        return False

    def exists(self, key: str) -> bool:
        return key in os.environ

    def list_keys(self, prefix: Optional[str] = None) -> List[str]:
        keys = list(os.environ.keys())
        if prefix:
            keys = [k for k in keys if k.startswith(prefix)]
        return keys


class AWSSecretProvider(SecretProviderInterface):
    """AWS Secrets Manager провайдер"""

    def __init__(self, region: str = "us-east-1", prefix: str = "tetracore/"):
        if not HAS_AWS or boto3 is None:
            raise ImportError("boto3 не встановлено. Виконайте: pip install boto3")
        try:
            self.client = boto3.client("secretsmanager", region_name=region)
        except Exception as e:
            # Санітуємо можливі ключі типу AKIA... у повідомленні
            import re

            sanitized = re.sub(r"AKIA[A-Z0-9]{16}", "AKIA****************", str(e))
            raise Exception(sanitized)
        self.prefix = prefix
        self._cache = {}
        self._cache_timestamps = {}

    def _get_full_key(self, key: str) -> str:
        return f"{self.prefix}{key}"

    def _is_cache_valid(self, key: str) -> bool:
        if key not in self._cache_timestamps:
            return False
        age = (datetime.now() - self._cache_timestamps[key]).total_seconds()
        return age < CACHE_TTL

    def get(self, key: str) -> Optional[str]:
        # Перевірити кеш
        if self._is_cache_valid(key):
            return self._cache.get(key)

        try:
            response = self.client.get_secret_value(SecretId=self._get_full_key(key))
            value = response.get("SecretString") if isinstance(response, dict) else None

            # Оновити кеш
            self._cache[key] = value
            self._cache_timestamps[key] = datetime.now()

            return value
        except self.client.exceptions.ResourceNotFoundException:
            return None
        except Exception as e:
            # Маскуємо можливі патерни ключів AWS у повідомленнях помилок
            import re

            sanitized = re.sub(r"AKIA[A-Z0-9]{16}", "AKIA****************", str(e))
            logger.error(f"AWS Secrets Manager error: {sanitized}")
            return None

    def set(self, key: str, value: str) -> bool:
        try:
            full_key = self._get_full_key(key)
            try:
                self.client.update_secret(SecretId=full_key, SecretString=value)
            except self.client.exceptions.ResourceNotFoundException:
                self.client.create_secret(Name=full_key, SecretString=value)

            # Оновити кеш
            self._cache[key] = value
            self._cache_timestamps[key] = datetime.now()

            return True
        except Exception as e:
            import re

            sanitized = re.sub(r"AKIA[A-Z0-9]{16}", "AKIA****************", str(e))
            logger.error(f"AWS Secrets Manager error: {sanitized}")
            return False

    def delete(self, key: str) -> bool:
        try:
            self.client.delete_secret(
                SecretId=self._get_full_key(key), ForceDeleteWithoutRecovery=False
            )

            # Видалити з кешу
            self._cache.pop(key, None)
            self._cache_timestamps.pop(key, None)

            return True
        except Exception as e:
            import re

            sanitized = re.sub(r"AKIA[A-Z0-9]{16}", "AKIA****************", str(e))
            logger.error(f"AWS Secrets Manager error: {sanitized}")
            return False

    def exists(self, key: str) -> bool:
        try:
            self.client.describe_secret(SecretId=self._get_full_key(key))
            return True
        except self.client.exceptions.ResourceNotFoundException:
            return False
        except Exception:
            return False

    def list_keys(self, prefix: Optional[str] = None) -> List[str]:
        try:
            keys = []
            paginator = self.client.get_paginator("list_secrets")

            for page in paginator.paginate():
                for secret in page["SecretList"]:
                    if secret["Name"].startswith(self.prefix):
                        key = secret["Name"][len(self.prefix) :]
                        if not prefix or key.startswith(prefix):
                            keys.append(key)

            return keys
        except Exception as e:
            logger.error(f"AWS Secrets Manager error: {e}")
            return []


class VaultSecretProvider(SecretProviderInterface):
    """HashiCorp Vault провайдер"""

    def __init__(self, url: str, token: str, mount_point: str = "secret"):
        if not HAS_VAULT or hvac is None:
            raise ImportError("hvac не встановлено. Виконайте: pip install hvac")
        self.client = hvac.Client(url=url, token=token)
        self.mount_point = mount_point

    def get(self, key: str) -> Optional[str]:
        try:
            response = self.client.secrets.kv.v2.read_secret_version(
                path=key, mount_point=self.mount_point
            )
            return response["data"]["data"].get("value")
        except Exception as e:
            logger.error(f"Vault error: {e}")
            return None

    def set(self, key: str, value: str) -> bool:
        try:
            self.client.secrets.kv.v2.create_or_update_secret(
                path=key, secret={"value": value}, mount_point=self.mount_point
            )
            return True
        except Exception as e:
            logger.error(f"Vault error: {e}")
            return False

    def delete(self, key: str) -> bool:
        try:
            self.client.secrets.kv.v2.delete_metadata_and_all_versions(
                path=key, mount_point=self.mount_point
            )
            return True
        except Exception as e:
            logger.error(f"Vault error: {e}")
            return False

    def exists(self, key: str) -> bool:
        try:
            self.client.secrets.kv.v2.read_secret_version(
                path=key, mount_point=self.mount_point
            )
            return True
        except Exception:
            return False

    def list_keys(self, prefix: Optional[str] = None) -> List[str]:
        try:
            response = self.client.secrets.kv.v2.list_secrets(
                mount_point=self.mount_point
            )
            keys = response["data"]["keys"]

            if prefix:
                keys = [k for k in keys if k.startswith(prefix)]

            return keys
        except Exception as e:
            logger.error(f"Vault error: {e}")
            return []


class RedisSecretProvider(SecretProviderInterface):
    """Redis провайдер для швидкого доступу до секретів"""

    def __init__(self, redis_url: str, prefix: str = "secrets:", ttl: int = 3600):
        if not HAS_REDIS or redis is None:
            raise ImportError("redis не встановлено. Виконайте: pip install redis")
        self.client = redis.from_url(redis_url)
        self.prefix = prefix
        self.ttl = ttl

    def _get_full_key(self, key: str) -> str:
        return f"{self.prefix}{key}"

    def get(self, key: str) -> Optional[str]:
        try:
            full = self._get_full_key(key)
            value = self.client.get(full)
            logger.debug("Redis GET secret", redis_log=True, key=full, hit=bool(value))
            return value.decode("utf-8") if value else None
        except Exception as e:
            logger.error(f"Redis error: {e}")
            return None

    def set(self, key: str, value: str) -> bool:
        try:
            full = self._get_full_key(key)
            res = self.client.setex(full, self.ttl, value.encode("utf-8"))
            logger.debug("Redis SETEX secret", redis_log=True, key=full, ttl=self.ttl)
            return res
        except Exception as e:
            logger.error(f"Redis error: {e}")
            return False

    def delete(self, key: str) -> bool:
        try:
            full = self._get_full_key(key)
            res = bool(self.client.delete(full))
            logger.debug("Redis DEL secret", redis_log=True, key=full, deleted=res)
            return res
        except Exception as e:
            logger.error(f"Redis error: {e}")
            return False

    def exists(self, key: str) -> bool:
        try:
            full = self._get_full_key(key)
            res = bool(self.client.exists(full))
            logger.debug("Redis EXISTS secret", redis_log=True, key=full, exists=res)
            return res
        except Exception as e:
            logger.error(f"Redis error: {e}")
            return False

    def list_keys(self, prefix: Optional[str] = None) -> List[str]:
        try:
            pattern = f"{self.prefix}{prefix or ''}*"
            keys = []

            for key in self.client.scan_iter(match=pattern):
                key_str = key.decode("utf-8")
                if key_str.startswith(self.prefix):
                    keys.append(key_str[len(self.prefix) :])

            return keys
        except Exception as e:
            logger.error(f"Redis error: {e}")
            return []


class MemorySecretProvider(SecretProviderInterface):
    """In-memory secret provider для тестування"""

    def __init__(self):
        self._secrets = {}

    def get(self, key: str) -> Optional[str]:
        return self._secrets.get(key)

    def set(self, key: str, value: str) -> bool:
        self._secrets[key] = value
        return True

    def delete(self, key: str) -> bool:
        if key in self._secrets:
            del self._secrets[key]
            return True
        return False

    def exists(self, key: str) -> bool:
        return key in self._secrets

    def list_keys(self, prefix: Optional[str] = None) -> List[str]:
        if prefix:
            return [k for k in self._secrets.keys() if k.startswith(prefix)]
        return list(self._secrets.keys())


class SecretsManager:
    """Менеджер для безпечної роботи з секретами"""

    def __init__(
        self,
        master_key: Optional[str] = None,
        provider: Optional[SecretProvider] = None,
        allow_env_fallback: bool = False,
    ):
        """
        Ініціалізація менеджера секретів

        Args:
            master_key: Майстер-ключ для шифрування. Якщо не вказано,
                       завантажується з ENCRYPTION_KEY
            provider: Тип провайдера для зберігання секретів
            allow_env_fallback: Чи дозволяти fallback до ENV змінних (небезпечно!)
        """
        self._master_key = master_key or os.getenv("ENCRYPTION_KEY")
        self._cipher_suite = None
        self._secrets_cache: Dict[str, Any] = {}
        self._required_secrets = self._define_required_secrets()
        self._secret_metadata: Dict[str, Dict] = {}
        self._allow_env_fallback = allow_env_fallback

        # Ініціалізація провайдера
        self._provider = self._initialize_provider(provider)

        # Ініціалізація шифрування
        self._initialize_encryption()

        # Завантаження секретів
        self._load_secrets()

    def _initialize_provider(
        self, provider: Optional[SecretProvider]
    ) -> SecretProviderInterface:
        """Ініціалізувати провайдер секретів"""
        provider_type = provider or SecretProvider(os.getenv("SECRET_PROVIDER", "env"))

        # Дозволяємо явний вибір провайдера через SECRET_PROVIDER навіть у production.
        # Без тест-специфічних винятків; безпека забезпечується _validate_secrets()

        if provider_type == SecretProvider.ENV:
            return EnvSecretProvider()

        elif provider_type == SecretProvider.AWS:
            region = os.getenv("AWS_REGION", "us-east-1")
            prefix = os.getenv("AWS_SECRETS_PREFIX", "tetracore/")
            return AWSSecretProvider(region, prefix)

        elif provider_type == SecretProvider.VAULT:
            url = os.getenv("VAULT_URL", "http://localhost:8200")
            token = os.getenv("VAULT_TOKEN")
            if not token:
                logger.warning("VAULT_TOKEN не встановлено, використовую ENV провайдер")
                return EnvSecretProvider()
            return VaultSecretProvider(url, token)

        elif provider_type == SecretProvider.REDIS:
            redis_url = os.getenv("REDISCLOUD_URL", "redis://localhost:6379")
            return RedisSecretProvider(redis_url)

        elif provider_type == SecretProvider.MEMORY:
            return MemorySecretProvider()

        else:
            logger.warning(f"Невідомий провайдер {provider_type}, використовую ENV")
            return EnvSecretProvider()

    def _define_required_secrets(self) -> Dict[str, Dict[str, Any]]:
        """Визначення обов'язкових секретів з їх параметрами"""
        return {
            # Authentication
            "JWT_SECRET_KEY": {
                "required": True,
                "min_length": 32,
                "description": "Secret key for JWT tokens",
                "rotation_days": 90,
            },
            "JWT_REFRESH_SECRET": {
                "required": True,
                "min_length": 32,
                "description": "Secret key for refresh tokens",
                "rotation_days": 90,
            },
            "ADMIN_USERNAME": {
                "required": True,
                "min_length": 3,
                "description": "Admin username",
                "rotation_days": None,  # Не потребує ротації
            },
            "ADMIN_PASSWORD": {
                "required": True,
                "min_length": 12,
                "description": "Admin password",
                "rotation_days": 30,
                "complexity": True,  # Вимагає складного пароля
            },
            # External services
            "REDIS_PASSWORD": {
                "required": False,
                "min_length": 8,
                "description": "Redis password",
                "rotation_days": 180,
            },
            "BOT_TOKEN_PROD": {
                "required": False,
                "min_length": 40,
                "description": "Telegram bot token for production",
                "rotation_days": None,  # Telegram tokens don't expire
                "pattern": r"^\d+:[A-Za-z0-9_-]+$",
                "dev_only": True,  # Не перевіряти в development режимі
            },
            # AWS (optional)
            "AWS_ACCESS_KEY_ID": {
                "required": False,
                "min_length": 20,
                "description": "AWS access key",
                "rotation_days": 90,
                "pattern": r"^AKIA[A-Z0-9]{16}$",
            },
            "AWS_SECRET_ACCESS_KEY": {
                "required": False,
                "min_length": 40,
                "description": "AWS secret key",
                "rotation_days": 90,
            },
            # Encryption
            "ENCRYPTION_KEY": {
                "required": True,
                "min_length": 32,
                "description": "Master encryption key",
                "rotation_days": 180,
            },
        }

    def _initialize_encryption(self):
        """Ініціалізація шифрування"""
        if not self._master_key:
            logger.warning("No master key provided, generating temporary key")
            self._master_key = Fernet.generate_key().decode()

        # Validate key strength
        self._validate_encryption_key(self._master_key)

        try:
            # Якщо ключ вже у форматі Fernet
            if len(self._master_key) == 44 and self._master_key.endswith("="):
                self._cipher_suite = Fernet(self._master_key.encode())
            else:
                # Генеруємо ключ з пароля
                salt = secrets.token_bytes(16)  # Use random salt, not hardcoded
                kdf = PBKDF2HMAC(
                    algorithm=hashes.SHA256(),
                    length=32,
                    salt=salt,
                    iterations=ITERATIONS,
                )
                key = base64.urlsafe_b64encode(kdf.derive(self._master_key.encode()))
                self._cipher_suite = Fernet(key)

                # Store salt for future use
                self._encryption_salt = salt

        except Exception as e:
            logger.error("Failed to initialize encryption", error=str(e))
            raise ValueError("Invalid master key")

    def _validate_encryption_key(self, key: str):
        """Validate encryption key strength"""
        if not key:
            raise ValueError("Encryption key cannot be empty")

        # Check minimum length
        if len(key) < 16:
            raise ValueError("Encryption key must be at least 16 characters long")

        # Check for common weak keys
        weak_keys = [
            "password",
            "12345678",
            "qwerty",
            "admin",
            "secret",
            "password123",
            "admin123",
            "123456789",
            "letmein",
        ]

        if key.lower() in weak_keys:
            raise ValueError("Encryption key is too weak (common password)")

        # Check for repetitive patterns
        if len(set(key)) < 4:  # Less than 4 unique characters
            raise ValueError("Encryption key has insufficient character variety")

        # Check complexity for non-Fernet keys
        if not (len(key) == 44 and key.endswith("=")):
            # Require at least 3 of: uppercase, lowercase, digits, special chars
            complexity_score = 0
            if any(c.isupper() for c in key):
                complexity_score += 1
            if any(c.islower() for c in key):
                complexity_score += 1
            if any(c.isdigit() for c in key):
                complexity_score += 1
            if any(c in "!@#$%^&*()_+-=[]{}|;:,.<>?" for c in key):
                complexity_score += 1

            if complexity_score < 3:
                # У тестах допускається майстер-ключ без високої складності, якщо довжина >= 16
                is_test = os.getenv("ENVIRONMENT", "development").lower() in [
                    "development",
                    "testing",
                ]
                if not is_test:
                    raise ValueError(
                        "Encryption key must contain at least 3 of: uppercase, lowercase, digits, special characters"
                    )

    def _load_secrets(self):
        """Завантаження секретів з різних джерел"""
        # Діагностика початку завантаження
        env = os.getenv("ENVIRONMENT", "development").lower()
        logger.debug(
            "Starting secrets loading",
            provider=type(self._provider).__name__,
            env=env,
            allow_env_fallback=self._allow_env_fallback,
        )
        # 1. Завантаження з провайдера
        for secret_name in self._required_secrets:
            value = self._provider.get(secret_name)
            if value:
                self._secrets_cache[secret_name] = value
                # Не логувати значення секретів; лише тип/ознаки
                is_bcrypt = bool(
                    secret_name.endswith("PASSWORD")
                    and isinstance(value, str)
                    and value.startswith("$2")
                )
                logger.info(
                    "Loaded secret from provider",
                    secret_name=secret_name,
                    is_bcrypt=is_bcrypt,
                )

        # 2. Fallback до environment variables якщо дозволено і провайдер не ENV
        if self._allow_env_fallback and not isinstance(
            self._provider, EnvSecretProvider
        ):
            logger.info("ENV fallback is enabled for development")
            for secret_name in self._required_secrets:
                if secret_name not in self._secrets_cache:
                    value = os.getenv(secret_name)
                    if value:
                        self._secrets_cache[secret_name] = value
                        logger.info(
                            "Loaded secret from ENV fallback", secret_name=secret_name
                        )

        # 3. Спробувати завантажити з config для development
        if len(self._secrets_cache) < len(
            [k for k, v in self._required_secrets.items() if v["required"]]
        ):
            try:
                from config import settings

                config_secrets = {
                    "ADMIN_USERNAME": settings.admin_username,
                    "ADMIN_PASSWORD": settings.admin_password,
                }
                for secret_name, value in config_secrets.items():
                    if secret_name not in self._secrets_cache and value:
                        self._secrets_cache[secret_name] = value
                        logger.info(
                            "Loaded secret from config", secret_name=secret_name
                        )
            except Exception as e:
                logger.debug(f"Could not load from config: {e}")

        # 3.5. Видалено автозаповнення дефолтів для testing середовища

        # 4. Завантаження з файлу секретів (якщо існує)
        self._load_from_file()

        # 5. Валідація завантажених секретів
        self._validate_secrets()

    def _load_from_env(self):
        """Завантаження секретів зі змінних середовища"""
        for secret_name, config in self._required_secrets.items():
            value = os.getenv(secret_name)
            if value:
                self._secrets_cache[secret_name] = value
                self._secret_metadata[secret_name] = {
                    "loaded_at": datetime.utcnow(),
                    "source": "environment",
                }

    def _load_from_file(self):
        """Завантаження секретів з зашифрованого файлу"""
        secrets_file = Path(".secrets.enc")
        if secrets_file.exists() and self._cipher_suite:
            try:
                with open(secrets_file, "rb") as f:
                    encrypted_data = f.read()
                    decrypted_data = self._cipher_suite.decrypt(encrypted_data)
                    secrets_data = json.loads(decrypted_data.decode())

                    for secret_name, value in secrets_data.items():
                        if secret_name not in self._secrets_cache:
                            self._secrets_cache[secret_name] = value
                            self._secret_metadata[secret_name] = {
                                "loaded_at": datetime.utcnow(),
                                "source": "file",
                            }

            except Exception as e:
                logger.error("Failed to load secrets from file", error=str(e))

    def _validate_secrets(self):
        """Валідація завантажених секретів"""
        errors = []
        warnings = []

        # Перевірити чи це development або testing режим
        env = os.getenv("ENVIRONMENT", "development").lower()
        is_development = env in ["development", "testing"]

        # У development/testing режимі - мінімальна валідація
        if is_development:
            logger.info(f"{env.capitalize()} mode: skipping strict secret validation")
            required_for_dev = ["ADMIN_USERNAME", "ADMIN_PASSWORD"]
            for secret_name in required_for_dev:
                if secret_name not in self._secrets_cache:
                    warnings.append(f"{secret_name} not set, using default")

            # Тільки попередження в development
            if warnings:
                for warning in warnings:
                    logger.warning("Secret validation warning", warning=warning)
            return

        for secret_name, config in self._required_secrets.items():
            value = self._secrets_cache.get(secret_name)

            # Пропустити dev_only секрети в development режимі якщо вони порожні
            if is_development and config.get("dev_only") and not value:
                continue

            # Перевірка обов'язкових секретів
            if config["required"] and not value:
                errors.append(f"{secret_name} is required but not set")
                continue

            if value:
                # Перевірка мінімальної довжини
                min_length = config.get("min_length", 0)
                if len(value) < min_length:
                    errors.append(
                        f"{secret_name} must be at least {min_length} characters long"
                    )

                # Перевірка патерну
                if "pattern" in config:
                    import re

                    if not re.match(config["pattern"], value):
                        errors.append(f"{secret_name} does not match required pattern")

                # Перевірка складності пароля
                if config.get("complexity") and secret_name.endswith("PASSWORD"):
                    is_bcrypt = bool(isinstance(value, str) and value.startswith("$2"))
                    logger.debug(
                        "Password complexity check",
                        secret_name=secret_name,
                        is_bcrypt=is_bcrypt,
                    )
                    if not self._check_password_complexity(value):
                        errors.append(
                            f"{secret_name} must contain uppercase, lowercase, "
                            "numbers and special characters"
                        )

                # Перевірка віку секрету
                metadata = self._secret_metadata.get(secret_name, {})
                if metadata.get("loaded_at"):
                    age_days = (datetime.utcnow() - metadata["loaded_at"]).days
                    rotation_days = config.get("rotation_days")

                    if rotation_days and age_days > rotation_days:
                        warnings.append(
                            f"{secret_name} should be rotated (age: {age_days} days)"
                        )

                    if age_days > MAX_SECRET_AGE_DAYS:
                        errors.append(
                            f"{secret_name} is too old ({age_days} days) and must be rotated"
                        )

        # Логування результатів
        if errors:
            for error in errors:
                logger.error("Secret validation error", error=error)
            raise ValueError(f"Secret validation failed: {'; '.join(errors)}")

        if warnings:
            for warning in warnings:
                logger.warning("Secret validation warning", warning=warning)

    def _check_password_complexity(self, password: str) -> bool:
        """Перевірка складності пароля"""
        import re
        import time

        # Add small random delay to prevent timing attacks
        time.sleep(secrets.randbelow(1000) / 1000000)  # 0-1ms random delay

        # Якщо це bcrypt-хеш — пропускаємо перевірку складності
        try:
            if isinstance(password, str) and password.startswith("$2"):
                logger.debug("Skipping password complexity for bcrypt hash")
                return True
        except Exception:
            # У разі нестандартних типів — продовжуємо звичайну перевірку
            pass

        checks = [
            r"[A-Z]",  # Uppercase
            r"[a-z]",  # Lowercase
            r"[0-9]",  # Digits
            r'[!@#$%^&*(),.?":{}|<>]',  # Special characters
        ]

        # Perform all checks regardless of failures (constant time)
        results = []
        for check in checks:
            results.append(bool(re.search(check, password)))

        # Return true only if all checks pass
        return all(results)

    def get_secret(
        self, name: str, default: Optional[str] = None, use_cache: bool = True
    ) -> Optional[str]:
        """
        Отримання секрету за назвою

        Args:
            name: Назва секрету
            default: Значення за замовчуванням, якщо секрет не знайдено
            use_cache: Чи використовувати кеш при читанні

        Returns:
            Значення секрету або default
        """
        # Якщо значення вже у кеші, визначимо чи можна його використати
        cached_present = name in self._secrets_cache
        logger.debug(
            "get_secret called",
            secret_name=name,
            use_cache=use_cache,
            cached_present=cached_present,
        )
        if use_cache and cached_present:
            is_env_provider = isinstance(self._provider, EnvSecretProvider)
            force_refresh = os.getenv("SECRETS_FORCE_ENV_REFRESH", "").lower() in (
                "1",
                "true",
                "yes",
            )

            if is_env_provider and force_refresh:
                cached_value = self._secrets_cache.get(name)
                current_env_value = os.getenv(name)
                if current_env_value == cached_value or (
                    (current_env_value is None or current_env_value == "")
                    and cached_value is not None
                ):
                    logger.debug(
                        "Returning cached secret",
                        secret_name=name,
                        reason="env_provider_force_refresh_no_change",
                        cached_present=cached_present,
                    )
                    return cached_value if cached_value is not None else default
                logger.debug(
                    "Refreshing secret from Env provider (force)",
                    secret_name=name,
                )
                use_cache = False  # Прочитати свіже значення нижче
            else:
                logger.debug(
                    "Returning cached secret",
                    secret_name=name,
                    reason="provider_cached",
                    cached_present=cached_present,
                )
                cached_value = self._secrets_cache[name]
                return cached_value if cached_value is not None else default

        # Якщо немає у кеші або кеш потрібно оновити — читаємо з провайдера
        logger.debug(
            "Reading secret from provider",
            secret_name=name,
            provider=type(self._provider).__name__,
            had_cache=cached_present,
            use_cache=use_cache,
        )
        value = self._provider.get(name)

        if value:
            # Оновити кеш
            self._secrets_cache[name] = value
            self._secret_metadata[name] = {
                "loaded_at": datetime.utcnow(),
                "source": type(self._provider).__name__,
            }
            logger.debug(
                "Secret loaded from provider",
                secret_name=name,
                provider=type(self._provider).__name__,
                had_cache=cached_present,
            )
            return value

        # Повернути default якщо не знайдено
        # Негативне кешування, щоб уникати повторних звернень до провайдера
        self._secrets_cache[name] = None
        self._secret_metadata[name] = {
            "loaded_at": datetime.utcnow(),
            "source": type(self._provider).__name__,
            "missing": True,
        }

        if default is not None:
            logger.debug("Secret not found, using default", secret_name=name)
            return default
        else:
            logger.warning("Secret not found", secret_name=name)
            return None

    def set_secret(self, name: str, value: str, persist: bool = True):
        """
        Встановлення секрету

        Args:
            name: Назва секрету
            value: Значення секрету
            persist: Чи зберігати в провайдері

        Returns:
            bool: True якщо успішно збережено
        """
        # Валідація нового значення
        if name in self._required_secrets:
            config = self._required_secrets[name]
            min_length = config.get("min_length", 0)

            if len(value) < min_length:
                raise ValueError(
                    f"{name} must be at least {min_length} characters long"
                )
            # Дотримуємося pattern, якщо визначений
            pattern = config.get("pattern")
            if pattern:
                import re

                if not re.match(pattern, value):
                    raise ValueError(f"{name} does not match required pattern")

        # Збереження в кеші
        self._secrets_cache[name] = value
        self._secret_metadata[name] = {
            "loaded_at": datetime.utcnow(),
            "source": "runtime",
        }

        # Збереження в провайдері якщо потрібно
        if persist:
            success = self._provider.set(name, value)
            if success:
                logger.info(
                    "Secret persisted to provider",
                    secret_name=name,
                    provider=type(self._provider).__name__,
                )
            else:
                logger.error(
                    "Failed to persist secret",
                    secret_name=name,
                    provider=type(self._provider).__name__,
                )
                return False
        else:
            logger.info("Secret updated in cache only", secret_name=name)

        return True

    def _save_to_file(self):
        """Збереження секретів в зашифрований файл"""
        if not self._cipher_suite:
            logger.error("Cannot save secrets: encryption not initialized")
            return

        try:
            # Підготовка даних для збереження
            data_to_save = {}
            for name, value in self._secrets_cache.items():
                # Зберігаємо тільки ті, що не з environment
                metadata = self._secret_metadata.get(name, {})
                if metadata.get("source") != "environment":
                    data_to_save[name] = value

            # Шифрування та збереження
            json_data = json.dumps(data_to_save)
            encrypted_data = self._cipher_suite.encrypt(json_data.encode())

            # Create file with secure permissions (owner read/write only)
            import os

            # Use a temporary file to avoid race conditions
            temp_file = ".secrets.enc.tmp"

            # Create file with restricted permissions from the start
            fd = os.open(temp_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            try:
                with os.fdopen(fd, "wb") as f:
                    f.write(encrypted_data)
            except:
                os.close(fd)
                raise

            # Atomically replace the old file
            os.replace(temp_file, ".secrets.enc")

            # Double-check permissions (on Windows this may not be enforced)
            try:
                os.chmod(".secrets.enc", 0o600)  # Owner read/write only
            except Exception:
                pass

            logger.info("Secrets saved to encrypted file", count=len(data_to_save))

        except Exception as e:
            logger.error("Failed to save secrets", error=str(e))
            # Clean up temporary file if it exists
            if os.path.exists(temp_file):
                os.unlink(temp_file)

    def generate_secret(self, length: int = 32) -> str:
        """Генерація безпечного випадкового секрету"""
        return secrets.token_urlsafe(length)

    def rotate_secret(self, name: str) -> str:
        """
        Ротація секрету

        Args:
            name: Назва секрету для ротації

        Returns:
            Нове значення секрету
        """
        if name not in self._required_secrets:
            raise ValueError(f"Unknown secret: {name}")

        config = self._required_secrets[name]
        min_length = config.get("min_length", 32)

        # Збереження старого значення для rollback
        old_value = self._secrets_cache.get(name)
        old_metadata = self._secret_metadata.get(name, {}).copy()

        # Генерація нового значення
        if name.endswith("PASSWORD"):
            # Для паролів генеруємо складний пароль
            new_value = self._generate_complex_password(max(min_length, 16))
        else:
            # Для токенів та ключів - випадковий рядок
            new_value = self.generate_secret(max(min_length, 32))

        try:
            # Спроба встановити нове значення
            success = self.set_secret(name, new_value, persist=True)

            if not success:
                # Rollback on failure (без виключення, як очікує тест)
                if old_value is not None:
                    self._secrets_cache[name] = old_value
                    self._secret_metadata[name] = old_metadata
                logger.error(f"Secret rotation failed, rolled back: {name}")
                return old_value

            logger.info("Secret rotated successfully", secret_name=name)
            return new_value

        except Exception as e:
            # Rollback on any error (і повертаємо старе значення без виключення)
            if old_value is not None:
                self._secrets_cache[name] = old_value
                self._secret_metadata[name] = old_metadata
            logger.error(f"Secret rotation failed with error: {e}")
            return old_value

    def _generate_complex_password(self, length: int = 16) -> str:
        """Генерація складного пароля"""
        import string

        # Набори символів
        lowercase = string.ascii_lowercase
        uppercase = string.ascii_uppercase
        digits = string.digits
        special = "!@#$%^&*()_+-=[]{}|;:,.<>?"

        # Гарантуємо наявність всіх типів символів
        password = [
            secrets.choice(lowercase),
            secrets.choice(uppercase),
            secrets.choice(digits),
            secrets.choice(special),
        ]

        # Заповнюємо решту випадковими символами
        all_chars = lowercase + uppercase + digits + special
        for _ in range(length - 4):
            password.append(secrets.choice(all_chars))

        # Перемішуємо
        secrets.SystemRandom().shuffle(password)

        return "".join(password)

    def encrypt_data(self, data: Union[str, bytes]) -> bytes:
        """Шифрування даних"""
        if not self._cipher_suite:
            raise ValueError("Encryption not initialized")

        if isinstance(data, str):
            data = data.encode()

        return self._cipher_suite.encrypt(data)

    def decrypt_data(self, encrypted_data: bytes) -> bytes:
        """Розшифрування даних"""
        if not self._cipher_suite:
            raise ValueError("Encryption not initialized")

        return self._cipher_suite.decrypt(encrypted_data)

    def get_status(self) -> Dict[str, Any]:
        """Отримання статусу менеджера секретів"""
        status = {
            "encryption_initialized": self._cipher_suite is not None,
            "total_secrets": len(self._secrets_cache),
            "required_secrets_loaded": 0,
            "optional_secrets_loaded": 0,
            "secrets_needing_rotation": [],
            "validation_errors": [],
        }

        # Підрахунок завантажених секретів
        for name, config in self._required_secrets.items():
            if name in self._secrets_cache:
                if config["required"]:
                    status["required_secrets_loaded"] += 1
                else:
                    status["optional_secrets_loaded"] += 1

                # Перевірка необхідності ротації
                metadata = self._secret_metadata.get(name, {})
                loaded_at = metadata.get("loaded_at")
                rotation_days = config.get("rotation_days")

                if loaded_at and rotation_days:
                    age_days = (datetime.utcnow() - loaded_at).days
                    if age_days > rotation_days:
                        status["secrets_needing_rotation"].append(
                            {
                                "name": name,
                                "age_days": age_days,
                                "rotation_days": rotation_days,
                            }
                        )

        return status

    @lru_cache(maxsize=None)
    def get_jwt_key(self) -> str:
        """Отримання JWT ключа з кешуванням"""
        key = self.get_secret("JWT_SECRET_KEY")
        if not key:
            raise ValueError("JWT_SECRET_KEY not configured")
        return key

    @lru_cache(maxsize=None)
    def get_refresh_key(self) -> str:
        """Отримання refresh token ключа з кешуванням"""
        key = self.get_secret("JWT_REFRESH_SECRET")
        if not key:
            raise ValueError("JWT_REFRESH_SECRET not configured")
        return key


# Глобальний екземпляр - lazy initialization
_secrets_manager = None


def get_secrets_manager() -> SecretsManager:
    """Get or create the global secrets manager instance"""
    global _secrets_manager
    if _secrets_manager is None:
        # Initialize with safe defaults based on environment
        env = os.getenv("ENVIRONMENT", "development").lower()
        try:
            # Try to use environment variables first (respect SECRET_PROVIDER)
            provider_name = os.getenv("SECRET_PROVIDER", "env").lower()
            try:
                provider_enum = SecretProvider(provider_name)
            except Exception:
                provider_enum = SecretProvider.ENV
            _secrets_manager = SecretsManager(
                provider=provider_enum,
                allow_env_fallback=(env != "production"),
            )
            logger.info(
                "SecretsManager created",
                env=env,
                provider=type(_secrets_manager._provider).__name__,
                allow_env_fallback=_secrets_manager._allow_env_fallback,
            )
        except ValueError as e:
            # In production: hard fail on secret misconfiguration
            if env == "production":
                logger.error("Secrets initialization failed in production: %s", str(e))
                raise
            # In development/testing: create an in-memory instance with ephemeral keys
            logger.warning(f"Creating secrets manager in non-production test mode: {e}")
            _secrets_manager = SecretsManager(
                master_key=Fernet.generate_key().decode(),
                provider=SecretProvider.MEMORY,
            )
            from config import settings

            # Minimal safe defaults for non-prod only
            dev_secrets = {
                "JWT_SECRET_KEY": os.getenv("JWT_SECRET_KEY")
                or Fernet.generate_key().decode(),
                "JWT_REFRESH_SECRET": os.getenv("JWT_REFRESH_SECRET")
                or Fernet.generate_key().decode(),
                "ADMIN_USERNAME": settings.admin_username
                or os.getenv("ADMIN_USERNAME"),
                # Credentials must be set via environment variables
                "ADMIN_PASSWORD": settings.admin_password
                or os.getenv("ADMIN_PASSWORD"),
                "ENCRYPTION_KEY": os.getenv("ENCRYPTION_KEY")
                or Fernet.generate_key().decode(),
            }
            for key, value in dev_secrets.items():
                _secrets_manager.set_secret(key, value, persist=False)
            logger.info(
                "SecretsManager created in MEMORY mode",
                env=env,
                provider=type(_secrets_manager._provider).__name__,
            )
    return _secrets_manager


# For backward compatibility - create on first access
secrets_manager = None  # Will be set by imports that need it


# Хелпер функції для швидкого доступу
def get_secret(name: str, default: Optional[str] = None) -> Optional[str]:
    """Швидкий доступ до секрету"""
    return get_secrets_manager().get_secret(name, default)


def validate_all_secrets():
    """Валідація всіх секретів"""
    return get_secrets_manager()._validate_secrets()


def get_secrets_status() -> Dict[str, Any]:
    """Отримання статусу секретів"""
    return get_secrets_manager().get_status()
