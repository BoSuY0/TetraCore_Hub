import structlog
from typing import Any

# Кастомний логер замість print
logger = structlog.get_logger(__name__)


def print(*args: Any, **kwargs: Any):  # type: ignore[override]
    try:
        msg = " ".join(str(a) for a in args)
    except Exception:
        msg = "".join(map(str, args))
    logger.info(msg)


#!/usr/bin/env python3
"""
Security Check Script for TetraCore StreamHub
Перевіряє основні аспекти безпеки після оновлень
"""

import os
import sys
import json
import subprocess
from pathlib import Path


def check_vulnerable_packages():
    """Перевірка вразливих пакетів через pip-audit"""
    print("🔍 Перевірка вразливих пакетів...")
    try:
        result = subprocess.run(
            ["pip-audit", "--format", "json"], capture_output=True, text=True
        )

        if result.returncode != 0 and "pip-audit" not in result.stderr:
            print("❌ Помилка при запуску pip-audit")
            return False

        audit_data = json.loads(result.stdout)
        vulns = audit_data.get("dependencies", [])

        vulnerable_packages = [dep for dep in vulns if dep.get("vulns", [])]

        if vulnerable_packages:
            print("❌ Знайдено вразливі пакети:")
            for pkg in vulnerable_packages:
                print(f"  - {pkg['name']} {pkg['version']}")
                for vuln in pkg["vulns"]:
                    print(f"    CVE: {vuln.get('id', 'N/A')}")
            return False
        else:
            print("✅ Вразливі пакети не знайдено")
            return True

    except Exception as e:
        print(f"⚠️  pip-audit не встановлено або помилка: {e}")
        print("   Встановіть: pip install pip-audit")
        return None


def check_env_files():
    """Перевірка наявності .env файлів"""
    print("\n🔍 Перевірка конфігурації середовища...")

    env_example = Path(".env.example")
    env_file = Path(".env")

    if not env_example.exists():
        print("❌ Файл .env.example не знайдено")
        return False

    print("✅ Файл .env.example знайдено")

    if not env_file.exists():
        print("⚠️  Файл .env не знайдено")
        print("   Створіть його з .env.example: cp .env.example .env")
        return None
    else:
        print("✅ Файл .env знайдено")

        # Перевірка на наявність критичних змінних
        required_vars = [
            "ADMIN_USERNAME",
            "ADMIN_PASSWORD",
            "JWT_SECRET_KEY",
            "ENCRYPTION_KEY",
        ]

        with open(env_file, "r") as f:
            env_content = f.read()

        missing_vars = []
        for var in required_vars:
            if (
                f"{var}=" not in env_content
                or f"{var}=\n" in env_content
                or f"{var}= " in env_content
            ):
                missing_vars.append(var)

        if missing_vars:
            print("⚠️  Не встановлені важливі змінні:")
            for var in missing_vars:
                print(f"   - {var}")
            return None
        else:
            print("✅ Всі критичні змінні встановлені")

    return True


def check_hardcoded_credentials():
    """Перевірка на hardcoded credentials в коді"""
    print("\n🔍 Перевірка на hardcoded credentials...")

    dangerous_patterns = [
        ('or "admin"', "Hardcoded admin username"),
        ('or "password"', "Hardcoded password"),
        ('or "TetraCore@Admin123!"', "Hardcoded default password"),
        ("ADMIN_USERNAME = ", "Direct ADMIN_USERNAME assignment"),
        ("ADMIN_PASSWORD = ", "Direct ADMIN_PASSWORD assignment"),
    ]

    files_to_check = ["core/secrets_manager.py", "config.py", "core/auth_manager.py"]

    issues_found = False

    for file_path in files_to_check:
        if not Path(file_path).exists():
            continue

        with open(file_path, "r") as f:
            content = f.read()

        for pattern, description in dangerous_patterns:
            if pattern in content:
                print(f"❌ {description} знайдено в {file_path}")
                issues_found = True

    if not issues_found:
        print("✅ Hardcoded credentials не знайдено")
        return True

    return False


def check_file_permissions():
    """Перевірка прав доступу до файлів"""
    print("\n🔍 Перевірка прав доступу до файлів...")

    files_to_check = ["hub_launcher.py", "scripts/rotate_secrets.py"]

    issues_found = False

    for file_path in files_to_check:
        if not Path(file_path).exists():
            continue

        # Перевірка на права виконання
        if os.access(file_path, os.X_OK):
            print(f"❌ Файл {file_path} має права на виконання")
            issues_found = True
        else:
            print(f"✅ Файл {file_path} не має прав на виконання")

    return not issues_found


def check_gitignore():
    """Перевірка .gitignore"""
    print("\n🔍 Перевірка .gitignore...")

    gitignore = Path(".gitignore")
    if not gitignore.exists():
        print("❌ Файл .gitignore не знайдено")
        return False

    with open(gitignore, "r") as f:
        content = f.read()

    required_entries = [".env", "*.pyc", "__pycache__", "venv", "node_modules"]
    missing = []

    for entry in required_entries:
        if entry not in content:
            missing.append(entry)

    if missing:
        print("⚠️  Відсутні важливі записи в .gitignore:")
        for entry in missing:
            print(f"   - {entry}")
        return None
    else:
        print("✅ .gitignore налаштовано правильно")
        return True


def main():
    """Головна функція перевірки"""
    print("=" * 60)
    print("🛡️  ПЕРЕВІРКА БЕЗПЕКИ TetraCore StreamHub")
    print("=" * 60)

    results = {
        "packages": check_vulnerable_packages(),
        "env": check_env_files(),
        "credentials": check_hardcoded_credentials(),
        "permissions": check_file_permissions(),
        "gitignore": check_gitignore(),
    }

    print("\n" + "=" * 60)
    print("📊 ПІДСУМОК:")
    print("=" * 60)

    critical_issues = sum(1 for v in results.values() if v is False)
    warnings = sum(1 for v in results.values() if v is None)
    passed = sum(1 for v in results.values() if v is True)

    if critical_issues > 0:
        print(f"❌ Критичних проблем: {critical_issues}")
        print("   Необхідно виправити перед production!")

    if warnings > 0:
        print(f"⚠️  Попереджень: {warnings}")
        print("   Рекомендовано виправити")

    if passed == len(results):
        print("✅ Всі перевірки пройдено успішно!")
        print("   Проект готовий до розгортання")

    print("\n" + "=" * 60)

    # Return exit code based on critical issues
    sys.exit(1 if critical_issues > 0 else 0)


if __name__ == "__main__":
    main()
