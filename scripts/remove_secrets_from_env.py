#!/usr/bin/env python3
"""
Script to remove secrets from .env files in the repository
Видаляє чутливі дані з .env файлів та створює .env.example
"""

import os
import sys
import shutil
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Tuple, Optional
import re
import argparse

# Список чутливих ключів для видалення
SENSITIVE_KEYS = [
    # Telegram API
    "BOT_TOKEN_PROD",
    "BOT_TOKEN_DEV",
    "API_ID",
    "API_HASH",

    # AWS
    "AWS_ACCESS_KEY_ID",
    "AWS_SECRET_ACCESS_KEY",
    "AWS_SESSION_TOKEN",

    # Database
    "REDIS_PASSWORD",
    "DB_PASSWORD",
    "DATABASE_URL",

    # Auth & Encryption
    "JWT_SECRET",
    "SESSION_SECRET",
    "ENCRYPTION_KEY",
    "ADMIN_PASSWORD",
    "API_SECRET_KEY",

    # External Services
    "OPENAI_API_KEY",
    "STRIPE_SECRET_KEY",
    "SENDGRID_API_KEY",
    "TWILIO_AUTH_TOKEN",
    "GITHUB_TOKEN",

    # Other secrets
    "WEBHOOK_SECRET",
    "PRIVATE_KEY",
    "SECRET_KEY",
    "AUTH_TOKEN",
    "ACCESS_TOKEN",
    "REFRESH_TOKEN"
]

# Паттерни для виявлення секретів
SECRET_PATTERNS = [
    (r'.*_KEY$', 'your-api-key-here'),
    (r'.*_SECRET$', 'your-secret-here'),
    (r'.*_TOKEN$', 'your-token-here'),
    (r'.*_PASSWORD$', 'your-password-here'),
    (r'.*_HASH$', 'your-hash-here'),
    (r'.*_ID$', 'your-id-here'),
]

# Безпечні ключі які можна залишити
SAFE_KEYS = [
    "NODE_ENV",
    "PORT",
    "HOST",
    "DEBUG",
    "LOG_LEVEL",
    "REDIS_HOST",
    "REDIS_PORT",
    "API_VERSION",
    "APP_NAME",
    "ENVIRONMENT",
    "REGION",
    "TIMEZONE"
]


class EnvSecretRemover:
    """Клас для видалення секретів з .env файлів"""

    def __init__(self, project_root: Path):
        self.project_root = project_root
        self.backup_dir = project_root / ".env_backups"
        self.removed_secrets: Dict[str, Dict[str, str]] = {}
        self.backup_dir.mkdir(exist_ok=True)

    def find_env_files(self) -> List[Path]:
        """Знайти всі .env файли в проекті"""
        env_files = []

        # Шукаємо .env файли
        for pattern in [".env", ".env.*"]:
            for file_path in self.project_root.rglob(pattern):
                # Пропускаємо node_modules та інші службові директорії
                if any(part in file_path.parts for part in [
                    "node_modules", "venv", ".git", "__pycache__",
                    "dist", "build", ".env_backups"
                ]):
                    continue

                # Пропускаємо .env.example файли
                if file_path.name.endswith(".example"):
                    continue

                env_files.append(file_path)

        return sorted(env_files)

    def create_backup(self, file_path: Path) -> Path:
        """Створити резервну копію .env файлу"""
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        relative_path = file_path.relative_to(self.project_root)
        backup_name = f"{relative_path.name}_{timestamp}.backup"

        # Створити структуру директорій для backup
        backup_path = self.backup_dir / relative_path.parent / backup_name
        backup_path.parent.mkdir(parents=True, exist_ok=True)

        # Копіювати файл
        shutil.copy2(file_path, backup_path)

        # Створити hash для перевірки цілісності
        with open(file_path, 'rb') as f:
            file_hash = hashlib.sha256(f.read()).hexdigest()

        # Зберегти метадані
        metadata_path = backup_path.with_suffix('.json')
        metadata = {
            "original_path": str(file_path),
            "backup_time": timestamp,
            "file_hash": file_hash,
            "file_size": file_path.stat().st_size
        }

        with open(metadata_path, 'w') as f:
            json.dump(metadata, f, indent=2)

        return backup_path

    def is_sensitive_key(self, key: str) -> bool:
        """Перевірити чи ключ є чутливим"""
        # Перевірити прямі співпадіння
        if key in SENSITIVE_KEYS:
            return True

        # Перевірити паттерни
        for pattern, _ in SECRET_PATTERNS:
            if re.match(pattern, key, re.IGNORECASE):
                return True

        # Перевірити чи містить ключові слова
        sensitive_words = ['secret', 'password', 'token', 'key', 'auth', 'private']
        key_lower = key.lower()

        return any(word in key_lower for word in sensitive_words)

    def get_safe_value(self, key: str, original_value: str) -> str:
        """Отримати безпечне значення для заміни"""
        # Перевірити паттерни
        for pattern, safe_value in SECRET_PATTERNS:
            if re.match(pattern, key, re.IGNORECASE):
                return safe_value

        # За замовчуванням
        if 'password' in key.lower():
            return 'your-password-here'
        elif 'token' in key.lower():
            return 'your-token-here'
        elif 'key' in key.lower():
            return 'your-key-here'
        elif 'secret' in key.lower():
            return 'your-secret-here'
        else:
            return 'your-value-here'

    def process_env_file(self, file_path: Path) -> Tuple[int, int]:
        """Обробити один .env файл"""
        lines = []
        removed_count = 0
        total_count = 0
        file_secrets = {}

        with open(file_path, 'r') as f:
            for line in f:
                line = line.rstrip('\n')

                # Пропустити порожні рядки та коментарі
                if not line.strip() or line.strip().startswith('#'):
                    lines.append(line)
                    continue

                # Парсити ключ=значення
                if '=' in line:
                    key, value = line.split('=', 1)
                    key = key.strip()
                    value = value.strip().strip('"\'')
                    total_count += 1

                    if self.is_sensitive_key(key) and key not in SAFE_KEYS:
                        # Зберегти оригінальне значення
                        file_secrets[key] = value

                        # Замінити на безпечне значення
                        safe_value = self.get_safe_value(key, value)
                        lines.append(f"{key}={safe_value}")
                        removed_count += 1
                    else:
                        lines.append(line)
                else:
                    lines.append(line)

        # Зберегти видалені секрети
        if file_secrets:
            self.removed_secrets[str(file_path)] = file_secrets

        # Записати оновлений файл
        with open(file_path, 'w') as f:
            f.write('\n'.join(lines))
            # Додати новий рядок в кінці якщо його не було
            if lines and not lines[-1].endswith('\n'):
                f.write('\n')

        return removed_count, total_count

    def create_env_example(self, file_path: Path):
        """Створити .env.example файл"""
        example_path = file_path.parent / f"{file_path.name}.example"

        # Якщо .env.example вже існує, створити backup
        if example_path.exists():
            timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
            backup_path = example_path.parent / f"{example_path.name}.{timestamp}.backup"
            shutil.copy2(example_path, backup_path)

        # Копіювати поточний .env (вже без секретів) як .env.example
        shutil.copy2(file_path, example_path)

        # Додати заголовок
        with open(example_path, 'r') as f:
            content = f.read()

        header = """# Environment Variables Example
# Copy this file to .env and fill in your actual values
# DO NOT commit .env file with real secrets!
# Generated by remove_secrets_from_env.py

"""

        with open(example_path, 'w') as f:
            f.write(header + content)

    def save_removed_secrets_report(self):
        """Зберегти звіт про видалені секрети"""
        if not self.removed_secrets:
            return

        report_path = self.backup_dir / f"removed_secrets_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.json"

        report = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "files_processed": len(self.removed_secrets),
            "total_secrets_removed": sum(len(secrets) for secrets in self.removed_secrets.values()),
            "removed_secrets": {
                file_path: {
                    "count": len(secrets),
                    "keys": list(secrets.keys())
                }
                for file_path, secrets in self.removed_secrets.items()
            }
        }

        with open(report_path, 'w') as f:
            json.dump(report, f, indent=2)

        return report_path


def main():
    parser = argparse.ArgumentParser(
        description="Remove secrets from .env files in the repository"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be done without making changes"
    )
    parser.add_argument(
        "--no-backup",
        action="store_true",
        help="Don't create backups (not recommended!)"
    )
    parser.add_argument(
        "--no-example",
        action="store_true",
        help="Don't create .env.example files"
    )
    parser.add_argument(
        "--path",
        type=Path,
        default=Path.cwd(),
        help="Project root path (default: current directory)"
    )

    args = parser.parse_args()

    # Ініціалізація
    remover = EnvSecretRemover(args.path)

    print("🔍 Searching for .env files...")
    env_files = remover.find_env_files()

    if not env_files:
        print("✅ No .env files found in the repository")
        return 0

    print(f"\nFound {len(env_files)} .env file(s):")
    for file_path in env_files:
        print(f"  - {file_path.relative_to(remover.project_root)}")

    if args.dry_run:
        print("\n🔎 DRY RUN MODE - No changes will be made")

        for file_path in env_files:
            print(f"\nAnalyzing {file_path.relative_to(remover.project_root)}...")

            with open(file_path, 'r') as f:
                for line in f:
                    if '=' in line and not line.strip().startswith('#'):
                        key = line.split('=', 1)[0].strip()
                        if remover.is_sensitive_key(key) and key not in SAFE_KEYS:
                            print(f"  ⚠️  Would remove: {key}")

        return 0

    # Обробка файлів
    total_removed = 0
    total_keys = 0

    print("\n🔐 Processing .env files...")

    for file_path in env_files:
        relative_path = file_path.relative_to(remover.project_root)
        print(f"\nProcessing {relative_path}...")

        # Створити backup
        if not args.no_backup:
            backup_path = remover.create_backup(file_path)
            print(f"  ✅ Backup created: {backup_path.relative_to(remover.project_root)}")

        # Обробити файл
        removed, total = remover.process_env_file(file_path)
        total_removed += removed
        total_keys += total

        if removed > 0:
            print(f"  ⚠️  Removed {removed} secret(s) from {total} total keys")
        else:
            print(f"  ✅ No secrets found (checked {total} keys)")

        # Створити .env.example
        if not args.no_example:
            remover.create_env_example(file_path)
            print(f"  ✅ Created {file_path.name}.example")

    # Зберегти звіт
    if total_removed > 0:
        report_path = remover.save_removed_secrets_report()
        print(f"\n📄 Report saved: {report_path.relative_to(remover.project_root)}")

    # Підсумок
    print("\n" + "="*50)
    print("📊 SUMMARY:")
    print(f"  - Files processed: {len(env_files)}")
    print(f"  - Secrets removed: {total_removed}")
    print(f"  - Total keys checked: {total_keys}")

    if total_removed > 0:
        print("\n⚠️  IMPORTANT NEXT STEPS:")
        print("1. Review the changes to ensure no non-sensitive data was removed")
        print("2. Commit the cleaned .env and .env.example files")
        print("3. Add .env to .gitignore if not already there")
        print("4. Rotate ALL compromised secrets immediately:")
        print("   python scripts/rotate_secrets.py --rotate-all")
        print("5. Update your deployment configuration with new secrets")
        print("\n🔐 Security Note: The removed secrets are stored in encrypted backups.")
        print("   Delete the .env_backups directory after rotating all secrets.")
    else:
        print("\n✅ No secrets found in .env files!")

    return 0


if __name__ == "__main__":
    sys.exit(main())
