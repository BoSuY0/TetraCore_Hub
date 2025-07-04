"""
Configuration for TetraCore Hub Authentication
Налаштування авторизації для TetraCore Hub
"""

import os
from typing import List

# Завантаження змінних з .env файлу
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    # Якщо python-dotenv не встановлено, спробуємо завантажити .env вручну
    env_path = os.path.join(os.path.dirname(__file__), '.env')
    if os.path.exists(env_path):
        with open(env_path, 'r') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, value = line.split('=', 1)
                    os.environ[key] = value

# Session Configuration
SESSION_DURATION_HOURS = 24  # Тривалість сесії в годинах
CLEANUP_INTERVAL_MINUTES = 60  # Інтервал очищення застарілих сесій

# Security Settings
REQUIRE_USERNAME = False  # Чи вимагати username
REQUIRE_PHOTO = False     # Чи вимагати фото профілю

# Налаштування для авторизації з логіном та паролем
# Значення беруться з .env (див. .env.example)
# Якщо не встановлені в .env, використовуються значення за замовчуванням для тестування
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")  # За замовчуванням: admin
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "password")  # За замовчуванням: password


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
    # Без авторизації через бота немає що перевіряти
    return []

if __name__ == "__main__":
    print_auth_status() 