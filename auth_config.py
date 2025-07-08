"""
Configuration for TetraCore Hub Authentication
Налаштування авторизації для TetraCore Hub
"""

import os
from typing import List

# Завантаження змінних з .env файлу
# ВАЖЛИВО: Використовуйте python-dotenv для безпечного завантаження
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    import warnings
    warnings.warn(
        "python-dotenv не встановлено. Змінні середовища мають бути встановлені вручну.",
        RuntimeWarning
    )

# Session Configuration
SESSION_DURATION_HOURS = 24  # Тривалість сесії в годинах
CLEANUP_INTERVAL_MINUTES = 60  # Інтервал очищення застарілих сесій

# Security Settings
REQUIRE_USERNAME = False  # Чи вимагати username
REQUIRE_PHOTO = False     # Чи вимагати фото профілю

# Налаштування для авторизації з логіном та паролем
# Значення беруться з .env (див. .env.example)
# Якщо не встановлені в .env, використовуються значення за замовчуванням для тестування
# ВАЖЛИВО: Ці значення МАЮТЬ бути встановлені через змінні середовища!
# Ніколи не використовуйте значення за замовчуванням в продакшені
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD")

# Перевірка наявності обов'язкових credentials
if not ADMIN_USERNAME or not ADMIN_PASSWORD:
    import warnings
    warnings.warn(
        "ADMIN_USERNAME та ADMIN_PASSWORD не встановлені! "
        "Встановіть їх через змінні середовища або .env файл. "
        "Див. .env.example для прикладу.",
        RuntimeWarning
    )
    # Тимчасові значення ТІЛЬКИ для розробки
    if os.getenv("ENVIRONMENT", "production").lower() == "development":
        ADMIN_USERNAME = "dev_admin"
        ADMIN_PASSWORD = "dev_password_change_me"
    else:
        raise ValueError(
            "ADMIN_USERNAME та ADMIN_PASSWORD мають бути встановлені в продакшені!"
        )


# Role-based permissions
ROLE_PERMISSIONS = {
    "admin": [
        "dashboard.view", "clients.view", "clients.manage",
        "tasks.view", "tasks.manage", "settings.view",
        "settings.manage", "logs.view", "auth.manage"
    ]
}

# Функції для отримання ролей та дозволів
def get_user_role(user_id: int) -> str:
    """Визначення ролі користувача - завжди адміністратор"""
    return "admin"

def get_user_permissions(user_id: int) -> List[str]:
    """Отримання дозволів користувача - завжди для адміністратора"""
    return ROLE_PERMISSIONS.get("admin", [])

# Validation functions
def validate_config() -> List[str]:
    """Валідація конфігурації авторизації"""
    errors = []

    # Перевірка наявності обов'язкових змінних
    if not ADMIN_USERNAME:
        errors.append("ADMIN_USERNAME not configured")
    if not ADMIN_PASSWORD:
        errors.append("ADMIN_PASSWORD not configured")

    # Перевірка довжини credentials
    if ADMIN_USERNAME and len(ADMIN_USERNAME) < 3:
        errors.append("ADMIN_USERNAME must be at least 3 characters long")
    if ADMIN_PASSWORD and len(ADMIN_PASSWORD) < 8:
        errors.append("ADMIN_PASSWORD must be at least 8 characters long")

    return errors

# Модуль не призначений для standalone виконання
# Використовуйте hub_launcher.py для запуску
