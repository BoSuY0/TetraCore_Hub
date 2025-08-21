#!/usr/bin/env python3
"""CLI-скрипт для діагностики безпекової конфігурації TetraCore Hub.

Запуск:
  python tools/security_config_check.py

Повертає код 0, якщо критичних проблем немає; 1 — якщо є critical.
"""
import json
import sys
import os

# Додаємо корінь проекту до PYTHONPATH
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from config import get_settings
from core.config_diagnostics import run_security_config_diagnostics


def main() -> int:
    settings = get_settings()
    report = run_security_config_diagnostics(settings)
    print(json.dumps(report, indent=2, ensure_ascii=False))
    critical = any(i.get("severity") == "critical" for i in report.get("issues", []))
    return 1 if critical else 0


if __name__ == "__main__":
    sys.exit(main())


