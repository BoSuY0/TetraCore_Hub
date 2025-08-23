"""
Система аудит логування для критичних операцій.
"""

import logging
import json
from datetime import datetime
from typing import Any, Dict, Optional
import os
from .utils import PIIMaskingFilter, mask_event_dict, _mask_text_patterns

# Створюємо окремий логер для аудиту
audit_logger = logging.getLogger("audit")
# Рівень логування аудиту успадковується з root/LOG_LEVEL; не примушуємо локально

# Створюємо директорію для аудит логів якщо не існує
audit_dir = "logs/audit"
os.makedirs(audit_dir, exist_ok=True)

# Налаштування файлового хендлера для аудит логів
audit_handler = logging.FileHandler(
    filename=f'{audit_dir}/audit_{datetime.now().strftime("%Y%m%d")}.log',
    encoding="utf-8",
)

# Формат для аудит логів
audit_formatter = logging.Formatter(
    "%(asctime)s | %(levelname)s | %(message)s | %(extra_data)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)


class AuditFilter(logging.Filter):
    """Фільтр для додавання додаткових даних до логів."""

    def filter(self, record):
        # Додаємо і маскуємо extra_data якщо є
        if hasattr(record, "extra_data"):
            try:
                extra = record.extra_data
                if isinstance(extra, dict):
                    extra = mask_event_dict(extra)
                    record.extra_data = json.dumps(extra, ensure_ascii=False)
                elif isinstance(extra, str):
                    record.extra_data = _mask_text_patterns(extra)
                else:
                    record.extra_data = json.dumps({}, ensure_ascii=False)
            except Exception:
                record.extra_data = json.dumps({}, ensure_ascii=False)
        else:
            record.extra_data = "{}"
        return True


audit_handler.setFormatter(audit_formatter)
AuditFilter()  # no-op create (kept for parity)
# Додаємо фільтр на handler (щоб formatter мав extra_data)
try:
    audit_handler.addFilter(AuditFilter())
except Exception:
    pass

# Додаємо PII/secret маскування і для аудиту
try:
    audit_handler.addFilter(PIIMaskingFilter())
except Exception:
    pass

audit_logger.addHandler(audit_handler)

# Відключаємо пропагацію щоб не дублювати в основних логах
audit_logger.propagate = False


class AuditLogger:
    """Клас для структурованого аудит логування."""

    @staticmethod
    def log_action(
        action: str,
        entity_type: str,
        entity_id: Any,
        user_id: Optional[int] = None,
        details: Optional[Dict[str, Any]] = None,
        success: bool = True,
        error: Optional[str] = None,
    ):
        """
        Логує дію для аудиту.

        Args:
            action: Тип дії (create, update, delete, activate, deactivate, etc.)
            entity_type: Тип сутності (module, user, chat, etc.)
            entity_id: ID сутності
            user_id: ID користувача який виконав дію
            details: Додаткові деталі
            success: Чи була дія успішною
            error: Повідомлення про помилку якщо є
        """
        log_data = {
            "action": action,
            "entity_type": entity_type,
            "entity_id": entity_id,
            "user_id": user_id,
            "timestamp": datetime.now().isoformat(),
            "success": success,
        }

        if details:
            log_data["details"] = details

        if error:
            log_data["error"] = error

        message = f"AUDIT | {action.upper()} | {entity_type} | {entity_id}"

        if user_id:
            message += f" | by user {user_id}"

        if success:
            audit_logger.info(message, extra={"extra_data": log_data})
        else:
            audit_logger.warning(
                message + f" | FAILED: {error}", extra={"extra_data": log_data}
            )

    @staticmethod
    def log_security_event(
        event_type: str,
        severity: str,
        description: str,
        user_id: Optional[int] = None,
        ip_address: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
    ):
        """
        Логує події безпеки.

        Args:
            event_type: Тип події (unauthorized_access, rate_limit_exceeded, etc.)
            severity: Рівень серйозності (low, medium, high, critical)
            description: Опис події
            user_id: ID користувача
            ip_address: IP адреса
            details: Додаткові деталі
        """
        log_data = {
            "event_type": event_type,
            "severity": severity,
            "description": description,
            "user_id": user_id,
            "ip_address": ip_address,
            "timestamp": datetime.now().isoformat(),
        }

        if details:
            log_data["details"] = details

        message = f"SECURITY | {severity.upper()} | {event_type} | {description}"

        if severity in ["high", "critical"]:
            audit_logger.error(message, extra={"extra_data": log_data})
        elif severity == "medium":
            audit_logger.warning(message, extra={"extra_data": log_data})
        else:
            audit_logger.info(message, extra={"extra_data": log_data})

    @staticmethod
    def log_data_access(
        operation: str,
        table: str,
        record_id: Any,
        user_id: Optional[int] = None,
        fields: Optional[list] = None,
        old_values: Optional[Dict] = None,
        new_values: Optional[Dict] = None,
    ):
        """
        Логує доступ до даних.

        Args:
            operation: Тип операції (select, insert, update, delete)
            table: Назва таблиці
            record_id: ID запису
            user_id: ID користувача
            fields: Список полів які були змінені/прочитані
            old_values: Старі значення (для update)
            new_values: Нові значення (для insert/update)
        """
        log_data = {
            "operation": operation,
            "table": table,
            "record_id": record_id,
            "user_id": user_id,
            "timestamp": datetime.now().isoformat(),
        }

        if fields:
            log_data["fields"] = fields

        if old_values:
            log_data["old_values"] = old_values

        if new_values:
            log_data["new_values"] = new_values

        message = f"DATA | {operation.upper()} | {table} | {record_id}"

        if user_id:
            message += f" | by user {user_id}"

        audit_logger.info(message, extra={"extra_data": log_data})


# Експортуємо для зручного використання
__all__ = ["AuditLogger", "audit_logger"]
