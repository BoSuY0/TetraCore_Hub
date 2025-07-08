#!/usr/bin/env python3
"""
Development Environment Setup Script for TetraCore Hub
Налаштування локального середовища розробки з безпечними секретами
"""

import os
import sys
import secrets
import string
import json
import shutil
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple
import subprocess
import base64

# Константи
PROJECT_ROOT = Path(__file__).parent.parent
ENV_FILE = PROJECT_ROOT / ".env"
ENV_TEMPLATE = PROJECT_ROOT / ".env.template"
REQUIRED_DIRS = [
    "logs",
    "static",
    "secrets_backup",
    "frontend/build",
    "frontend/node_modules"
]

# Кольори для виводу
class Colors:
    HEADER = '\033[95m'
    OKBLUE = '\033[94m'
    OKCYAN = '\033[96m'
    OKGREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'


def print_header(message: str):
    """Вивести заголовок"""
    print(f"\n{Colors.HEADER}{Colors.BOLD}{'='*60}{Colors.ENDC}")
    print(f"{Colors.HEADER}{Colors.BOLD}{message.center(60)}{Colors.ENDC}")
    print(f"{Colors.HEADER}{Colors.BOLD}{'='*60}{Colors.ENDC}\n")


def print_success(message: str):
    """Вивести успішне повідомлення"""
    print(f"{Colors.OKGREEN}✅ {message}{Colors.ENDC}")


def print_warning(message: str):
    """Вивести попередження"""
    print(f"{Colors.WARNING}⚠️  {message}{Colors.ENDC}")


def print_error(message: str):
    """Вивести помилку"""
    print(f"{Colors.FAIL}❌ {message}{Colors.ENDC}")


def print_info(message: str):
    """Вивести інформацію"""
    print(f"{Colors.OKBLUE}ℹ️  {message}{Colors.ENDC}")


def generate_secret(secret_type: str, length: int = 32) -> str:
    """Генерувати безпечний секрет"""
    if secret_type == "password":
        # Пароль з літерами, цифрами та спецсимволами
        alphabet = string.ascii_letters + string.digits + "!@#$%^&*"
        return ''.join(secrets.choice(alphabet) for _ in range(length))

    elif secret_type == "jwt":
        # JWT секрет - довший та складніший
        alphabet = string.ascii_letters + string.digits + "!@#$%^&*()_+-="
        return ''.join(secrets.choice(alphabet) for _ in range(64))

    elif secret_type == "encryption_key":
        # Ключ шифрування - base64 encoded
        return base64.urlsafe_b64encode(secrets.token_bytes(32)).decode('utf-8')

    elif secret_type == "api_key":
        # API ключ - тільки літери та цифри
        alphabet = string.ascii_letters + string.digits
        return ''.join(secrets.choice(alphabet) for _ in range(length))

    elif secret_type == "token":
        # Токен - URL-safe
        return secrets.token_urlsafe(length)

    else:
        # За замовчуванням - безпечний токен
        return secrets.token_urlsafe(length)


def check_python_version():
    """Перевірити версію Python"""
    required_version = (3, 8)
    current_version = sys.version_info[:2]

    if current_version < required_version:
        print_error(f"Python {required_version[0]}.{required_version[1]}+ required, but {current_version[0]}.{current_version[1]} found")
        return False

    print_success(f"Python {current_version[0]}.{current_version[1]} ✓")
    return True


def check_node_version():
    """Перевірити версію Node.js"""
    try:
        result = subprocess.run(['node', '--version'], capture_output=True, text=True)
        if result.returncode == 0:
            version = result.stdout.strip()
            print_success(f"Node.js {version} ✓")
            return True
        else:
            print_error("Node.js not found")
            return False
    except FileNotFoundError:
        print_error("Node.js not found in PATH")
        return False


def check_redis():
    """Перевірити доступність Redis"""
    try:
        result = subprocess.run(['redis-cli', 'ping'], capture_output=True, text=True)
        if result.returncode == 0 and result.stdout.strip() == 'PONG':
            print_success("Redis server is running ✓")
            return True
        else:
            print_warning("Redis server is not running (optional for development)")
            return False
    except FileNotFoundError:
        print_warning("Redis not found (optional for development)")
        return False


def create_directories():
    """Створити необхідні директорії"""
    print_info("Creating required directories...")

    for dir_path in REQUIRED_DIRS:
        full_path = PROJECT_ROOT / dir_path
        full_path.mkdir(parents=True, exist_ok=True)
        print_success(f"Directory created: {dir_path}")

    # Створити .gitkeep файли для порожніх директорій
    gitkeep_dirs = ["logs", "static", "secrets_backup"]
    for dir_name in gitkeep_dirs:
        gitkeep_path = PROJECT_ROOT / dir_name / ".gitkeep"
        gitkeep_path.touch(exist_ok=True)


def generate_env_file():
    """Створити .env файл з безпечними секретами"""
    print_info("Generating .env file with secure secrets...")

    # Перевірити чи вже існує .env
    if ENV_FILE.exists():
        backup_name = f".env.backup.{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        backup_path = PROJECT_ROOT / backup_name
        shutil.copy2(ENV_FILE, backup_path)
        print_warning(f"Existing .env backed up to {backup_name}")

    # Генерувати секрети
    secrets_config = {
        # Redis
        "REDIS_PASSWORD": generate_secret("password", 24),

        # JWT та автентифікація
        "JWT_SECRET": generate_secret("jwt"),
        "ADMIN_PASSWORD": generate_secret("password", 16),
        "SESSION_SECRET": generate_secret("jwt"),

        # Шифрування
        "ENCRYPTION_KEY": generate_secret("encryption_key"),
        "API_SECRET_KEY": generate_secret("api_key", 32),

        # Telegram (заглушки для dev)
        "BOT_TOKEN_PROD": "1234567890:ABCdefGHIjklMNOpqrsTUVwxyz",
        "BOT_TOKEN_DEV": "0987654321:zyxWVUtsrqpONMlkjIHGfedCBA",
        "API_ID": "12345678",
        "API_HASH": generate_secret("api_key", 32),

        # AWS (заглушки для dev)
        "AWS_ACCESS_KEY_ID": f"AKIA{generate_secret('api_key', 16).upper()}",
        "AWS_SECRET_ACCESS_KEY": generate_secret("api_key", 40),

        # Інші секрети
        "WEBHOOK_SECRET": generate_secret("token", 32),
        "BACKUP_ENCRYPTION_KEY": generate_secret("encryption_key"),
    }

    # Читаємо шаблон
    if ENV_TEMPLATE.exists():
        with open(ENV_TEMPLATE, 'r') as f:
            template_content = f.read()
    else:
        # Базовий шаблон якщо файл не існує
        template_content = """# TetraCore Hub Environment Variables
# Generated by setup_dev_env.py

# Environment
NODE_ENV=development
ENVIRONMENT=development

# Server Configuration
HOST=0.0.0.0
PORT=8000

# Redis Configuration
REDIS_HOST=localhost
REDIS_PORT=6379
"""

    # Створюємо .env файл
    env_content = []
    for line in template_content.split('\n'):
        if '=' in line and not line.strip().startswith('#'):
            key = line.split('=')[0].strip()
            if key in secrets_config:
                env_content.append(f"{key}={secrets_config[key]}")
            else:
                env_content.append(line)
        else:
            env_content.append(line)

    # Додаємо секрети які могли бути відсутні в шаблоні
    existing_keys = set()
    for line in env_content:
        if '=' in line and not line.strip().startswith('#'):
            key = line.split('=')[0].strip()
            existing_keys.add(key)

    missing_keys = set(secrets_config.keys()) - existing_keys
    if missing_keys:
        env_content.append("\n# Additional secrets")
        for key in sorted(missing_keys):
            env_content.append(f"{key}={secrets_config[key]}")

    # Записуємо файл
    with open(ENV_FILE, 'w') as f:
        f.write('\n'.join(env_content))

    print_success(".env file created with secure secrets")

    # Зберігаємо згенеровані секрети в окремий файл для довідки
    secrets_file = PROJECT_ROOT / "secrets_backup" / f"dev_secrets_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(secrets_file, 'w') as f:
        json.dump({
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "environment": "development",
            "secrets": secrets_config,
            "warning": "These are development secrets. Do not use in production!"
        }, f, indent=2)

    print_info(f"Secrets saved to {secrets_file.relative_to(PROJECT_ROOT)}")

    return secrets_config


def install_python_dependencies():
    """Встановити Python залежності"""
    print_info("Installing Python dependencies...")

    requirements_file = PROJECT_ROOT / "requirements.txt"
    if not requirements_file.exists():
        print_warning("requirements.txt not found, skipping Python dependencies")
        return False

    try:
        subprocess.run([sys.executable, "-m", "pip", "install", "-r", str(requirements_file)], check=True)
        print_success("Python dependencies installed")
        return True
    except subprocess.CalledProcessError:
        print_error("Failed to install Python dependencies")
        return False


def setup_frontend():
    """Налаштувати frontend"""
    print_info("Setting up frontend...")

    frontend_dir = PROJECT_ROOT / "frontend"
    if not (frontend_dir / "package.json").exists():
        print_warning("Frontend package.json not found, skipping frontend setup")
        return False

    try:
        # Install dependencies
        print_info("Installing frontend dependencies...")
        subprocess.run(["npm", "install", "--legacy-peer-deps"], cwd=frontend_dir, check=True)
        print_success("Frontend dependencies installed")

        # Build frontend
        print_info("Building frontend...")
        subprocess.run(["npm", "run", "build"], cwd=frontend_dir, check=True)
        print_success("Frontend built successfully")

        return True
    except subprocess.CalledProcessError as e:
        print_error(f"Frontend setup failed: {e}")
        return False


def print_secrets_info(secrets: Dict[str, str]):
    """Вивести інформацію про згенеровані секрети"""
    print_header("Generated Secrets Summary")

    print_info("Admin credentials:")
    print(f"  Username: admin")
    print(f"  Password: {secrets.get('ADMIN_PASSWORD', 'N/A')}")

    print_info("\nImportant secrets (first 8 characters):")
    important_keys = ["JWT_SECRET", "ENCRYPTION_KEY", "API_SECRET_KEY"]
    for key in important_keys:
        if key in secrets:
            print(f"  {key}: {secrets[key][:8]}...")

    print_warning("\nThese are DEVELOPMENT secrets only!")
    print_warning("For production, use proper secret management (AWS Secrets Manager, HashiCorp Vault, etc.)")


def main():
    """Основна функція"""
    print_header("TetraCore Hub Development Setup")

    # Перевірка системи
    print_info("Checking system requirements...")

    if not check_python_version():
        return 1

    check_node_version()
    check_redis()

    # Створення директорій
    create_directories()

    # Генерація .env файлу
    secrets = generate_env_file()

    # Встановлення залежностей
    if "--skip-deps" not in sys.argv:
        install_python_dependencies()

        if "--with-frontend" in sys.argv:
            setup_frontend()

    # Виведення інформації
    print_secrets_info(secrets)

    print_header("Setup Complete!")

    print_info("Next steps:")
    print("1. Start Redis: redis-server")
    print("2. Start the hub: python start_hub.py dev")
    print("3. Access the dashboard: http://localhost:8000")
    print("\nFor production deployment, remember to:")
    print("- Use proper secret management")
    print("- Enable HTTPS/WSS")
    print("- Configure proper CORS origins")
    print("- Set up monitoring and logging")

    return 0


if __name__ == "__main__":
    sys.exit(main())
