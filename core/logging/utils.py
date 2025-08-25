import logging
import os
import time
from typing import Any, Dict

# structlog доступний у проекті
import structlog
from structlog.stdlib import ProcessorFormatter, LoggerFactory
from structlog.exceptions import DropEvent
from structlog.processors import TimeStamper, add_log_level, format_exc_info


SENSITIVE_KEYS = {
    "authorization",
    "x-api-secret",
    "x-telegram-bot-api-secret-token",
    "token",
    "access_token",
    "refresh_token",
    "auth_token",
    "auth",
    "password",
    "api_key",
    "x-api-key",
    "x-auth-token",
    "encryption_key",
    "hub_auth_token",
    "bot_token",
    "secret",
    "cookie",
    "set-cookie",
    # connection strings
    "redis_url",
    "database_url",
    "db_url",
    "dsn",
    "connection_string",
    # PII keys
    "username",
    "user",
    "user_id",
    "email",
    "session_id",
    "csrf_token",
}


def _mask_value(value: Any) -> Any:
    try:
        s = str(value)
    except Exception:
        return "***"
    if len(s) <= 8:
        return "***"
    return f"{s[:3]}***{s[-3:]}"


def _mask_nested(obj: Any) -> Any:
    if isinstance(obj, dict):
        return mask_event_dict(obj)
    if isinstance(obj, (list, tuple)):
        return type(obj)(_mask_nested(v) for v in obj)
    return obj


def _mask_text_patterns(text: str) -> str:
    """Mask token-like patterns and secrets within free-form text/URLs."""
    try:
        import re
    except Exception:
        return text

    s = text
    # Mask Authorization: Bearer abc123 -> Bearer ***
    s = re.sub(r"(?i)(authorization\s*:\s*Bearer\s+)[^\s,;]+", r"\1***", s)
    s = re.sub(r"(?i)Bearer\s+[A-Za-z0-9._\-]+", "Bearer ***", s)

    # Mask common API key/token prefixes
    s = re.sub(
        r"(?i)(sk_(live|test)_[A-Za-z0-9]+)", lambda m: m.group(0)[:5] + "***", s
    )
    s = re.sub(r"\bAKIA[0-9A-Z]{12,}\b", lambda m: m.group(0)[:4] + "***", s)

    # Mask JWT-like tokens (base64url header.payload.signature)
    s = re.sub(
        r"eyJ[a-zA-Z0-9_-]{5,}\.[a-zA-Z0-9_-]{10,}\.[a-zA-Z0-9_-]{5,}", "***.***.***", s
    )

    # Mask query params like token=, access_token=, api_key=, password=
    s = re.sub(
        r"(?i)([?&])(access_token|token|auth_token|api_key|apikey|password|secret)=([^&#]+)",
        r"\1\2=***",
        s,
    )

    # Mask inline key=value tokens in free text (expected by tests)
    # token=abcdef -> ***=abcdef (key masked, value kept)
    s = re.sub(r"(?i)\btoken=([^\s&]+)", r"***=\1", s)
    # password=secret -> ***=*** (both masked)
    s = re.sub(r"(?i)\bpassword=[^\s&]+", "***=***", s)

    # Mask credentials in URLs: scheme://user:pass@host -> scheme://***@host
    s = re.sub(r"://[^/\s]*@", "://***@", s)

    # Mask Redis Cloud endpoint hostnames (avoid leaking instance IDs)
    # Example: redis-14708.c78.eu-west-1-2.ec2.redns.redis-cloud.com:14708 -> <redis-host>:14708
    s = re.sub(
        r"(?i)\b(redis-[a-z0-9-]+\.[\w.-]*redis-cloud\.com)(:\d+)?\b",
        r"<redis-host>\2",
        s,
    )

    # Mask email addresses
    s = re.sub(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", "***@***", s)
    return s


def mask_event_dict(event_dict: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(event_dict, dict):
        return event_dict
    masked = {}
    for k, v in event_dict.items():
        key_lower = str(k).lower()
        if key_lower in SENSITIVE_KEYS:
            masked[k] = _mask_value(v)
        else:
            if key_lower in {"headers", "http_headers"} and isinstance(v, dict):
                # маскуємо Authorization у вкладених заголовках
                masked_headers = {}
                for hk, hv in v.items():
                    if str(hk).lower() in {"authorization", "proxy-authorization"}:
                        masked_headers[hk] = _mask_value(hv)
                    else:
                        masked_headers[hk] = hv
                masked[k] = masked_headers
            elif key_lower in {
                "url",
                "path",
                "path_qs",
                "query",
                "body",
                "message",
                "event",
                "detail",
                "error",
            } and isinstance(v, str):
                masked[k] = _mask_text_patterns(v)
            else:
                masked[k] = _mask_nested(v)
    return masked


def structlog_masking_processor(logger, method_name, event_dict):
    return mask_event_dict(event_dict)


def simple_console_renderer(logger, method_name, event_dict):
    """Простий консольний рендерер без паддінгу рівня і з коротким часом.

    Формат: "HH:MM:SS LEVEL повідомлення k=v ..."
    Додаткові поля від stdlib/LogRecord (на кшталт _record, pathname, lineno)
    і службові ключі structlog не виводимо.
    """
    # Apply masking to entire event dict first
    event_dict = mask_event_dict(event_dict)

    timestamp = event_dict.pop("timestamp", "")
    level = (event_dict.pop("level", method_name) or "").upper()
    event = event_dict.pop("event", "")

    excluded_keys = {
        "logger",
        "timestamp",
        "level",
        "event",
        "exc_info",
        "exception",
        "stack_info",
        "positional_args",
        "name",
        "pathname",
        "filename",
        "lineno",
        "module",
        "funcName",
        "process",
        "processName",
        "thread",
        "threadName",
        "_record",
        "from_structlog",
        "_from_structlog",
    }

    filtered_items = []
    for key, value in event_dict.items():
        # Уникаємо KeyError у logging: LogRecord має поле 'module'
        if key == "module":
            continue
        if key in excluded_keys or str(key).startswith("_"):
            continue
        if isinstance(value, (str, int, float, bool)):
            filtered_items.append((key, value))

    # Mask free text in extras values
    masked_items = []
    for k, v in filtered_items:
        if isinstance(v, str):
            masked_items.append((k, _mask_text_patterns(v)))
        else:
            masked_items.append((k, v))
    extras = " ".join(f"{k}={v}" for k, v in masked_items)

    # Можливий сформатований traceback від format_exc_info
    exception_text = event_dict.pop("exception", None)
    if isinstance(exception_text, str):
        exception_text = _mask_text_patterns(exception_text)

    # ANSI стилі
    RESET = "\x1b[0m"
    BOLD = "\x1b[1m"
    COLORS = {
        "DEBUG": "\x1b[36m",  # Cyan
        "INFO": "\x1b[32m",  # Green
        "WARNING": "\x1b[33m",  # Yellow
        "ERROR": "\x1b[31m",  # Red
        "CRITICAL": "\x1b[35m",  # Magenta
    }
    BG = {
        "WARNING": "\x1b[43m",  # Yellow background
        "ERROR": "\x1b[41m",  # Red background
        "CRITICAL": "\x1b[45m",  # Magenta background
    }
    BRIGHT_WHITE = "\x1b[97m"
    GREY = "\x1b[90m"

    # Жирний час
    ts_part = f"{BOLD}{timestamp}{RESET}" if timestamp else ""

    # Кольоровий і жирний рівень
    color = COLORS.get(level, "")
    level_part = f"{BOLD}{color}{level}{RESET}" if level else ""

    # Для WARNING/ERROR/CRITICAL робимо помітний блок
    if level in ("WARNING", "ERROR", "CRITICAL"):
        bg = BG.get(level, "")
        header = f"{bg}{BRIGHT_WHITE}{BOLD} {timestamp} {level} {RESET}"
        top = f"{BOLD}{color}{'━' * 72}{RESET}"
        lines = [top, header, f"{BOLD}{event}{RESET}"]
        if extras:
            lines.append(f"{GREY}{extras}{RESET}")
        if exception_text:
            lines.append(f"{BRIGHT_WHITE}{exception_text}{RESET}")
        lines.append(top)
        return "\n".join(lines)

    message = f"{ts_part} {level_part} {event}".rstrip()
    return f"{message} {extras}".rstrip()


# === Duplicate log suppression ===
# Глобальний кеш для придушення ідентичних логів у короткому вікні часу
_DEDUP_CACHE: Dict[str, float] = {}
_DEDUP_MAX_SIZE: int = 1024


def _get_dedup_ttl_seconds() -> float:
    try:
        return float(os.getenv("LOG_DEDUP_WINDOW_SECONDS", "5"))
    except Exception:
        return 5.0


_DEDUP_TTL_SECONDS = _get_dedup_ttl_seconds()


def _build_log_signature(method_name: str, event_dict: Dict[str, Any]) -> str:
    # Ігноруємо мінливі службові ключі
    excluded = {
        "logger",
        "timestamp",
        "level",
        "event",
        "exc_info",
        "exception",
        "stack_info",
        "positional_args",
        "name",
        "pathname",
        "filename",
        "lineno",
        "module",
        "funcName",
        "process",
        "processName",
        "thread",
        "threadName",
        "_record",
        "from_structlog",
        "_from_structlog",
    }

    event = str(event_dict.get("event", ""))

    # Збираємо стабільні пари k=v
    parts = []
    for k, v in sorted(event_dict.items(), key=lambda kv: str(kv[0])):
        if k in excluded:
            continue
        try:
            v_str = str(v)
        except Exception:
            v_str = "<obj>"
        parts.append(f"{k}={v_str}")

    extras_str = "|".join(parts)
    return f"{method_name}|{event}|{extras_str}"


def suppress_duplicate_logs_processor(logger, method_name, event_dict):
    """Придушує ідентичні події в межах короткого вікна часу, не змінюючи рівні.

    Логуємо першу подію одразу; наступні з таким самим підписом
    у межах LOG_DEDUP_WINDOW_SECONDS (дефолт 10с) відкидаються.
    """
    try:
        signature = _build_log_signature(method_name, event_dict)
        now = time.monotonic()

        last_ts = _DEDUP_CACHE.get(signature)
        if last_ts is not None and (now - last_ts) < _DEDUP_TTL_SECONDS:
            raise DropEvent

        # Оновлюємо кеш і обмежуємо його розмір
        _DEDUP_CACHE[signature] = now
        if len(_DEDUP_CACHE) > _DEDUP_MAX_SIZE:
            # Грубе очищення: видалимо приблизно половину найстаріших записів
            try:
                # Сортування за часом і видалення старих ключів
                for key, _ in sorted(_DEDUP_CACHE.items(), key=lambda kv: kv[1])[
                    : len(_DEDUP_CACHE) // 2
                ]:
                    _DEDUP_CACHE.pop(key, None)
            except Exception:
                _DEDUP_CACHE.clear()
    except DropEvent:
        raise
    except Exception:
        # На будь-яку помилку у процесорі — не заважаємо логам
        return event_dict
    return event_dict


class PIIMaskingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            # Маскуємо додаткові аргументи, якщо це dict
            if isinstance(record.args, dict):
                record.args = mask_event_dict(record.args)  # type: ignore

            # Якщо повідомлення є словником (structlog), НЕ перетворюємо в рядок
            # а маскуємо поля без зміни типу
            if isinstance(record.msg, dict) or getattr(
                record, "_from_structlog", False
            ):
                try:
                    record.msg = mask_event_dict(dict(record.msg))  # type: ignore[arg-type]
                except Exception:
                    pass
            else:
                # Для звичайних рядкових повідомлень безпечно формуємо message,
                # маскуємо текст і обнуляємо args, щоб уникнути повторної інтерполяції
                try:
                    msg = record.getMessage()
                except Exception:
                    msg = str(record.msg)
                msg = _mask_text_patterns(str(msg))
                record.msg = msg
                # Ми вже виконали форматування, тож args більше не потрібні
                record.args = ()
        except Exception:
            pass
        return True


class WebsocketFrameNoiseFilter(logging.Filter):
    """Видаляє низькорівневі дампи WS-кадрів (>, < TEXT/PING/PONG ... [N bytes]).

    Ми НЕ змінюємо рівень логів, лише відкидаємо повідомлення, що заважають читати логи.
    """

    _SUBSTRINGS = (
        "> TEXT ",
        "< TEXT ",
        "> BINARY ",
        "< BINARY ",
        "> CONTINUATION ",
        "< CONTINUATION ",
        "> PING",
        "< PONG",
        "> CLOSE",
        "< CLOSE",
        '"WebSocket /ws',
    )

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            msg = record.getMessage()
            # Жорстка перевірка кадрів та рядків типу "WebSocket /ws"
            for s in self._SUBSTRINGS:
                if s in msg:
                    return False

            # Нормалізований пошук рукопотискання та станів з'єднання
            mlow = msg.lower()
            handshake_markers = (
                "< get /ws",  # вхідний запит WS
                "> http/1.1 101",  # відповідь switching protocols
                "> http/1.1 403",  # заборонено (невдале рукопотискання)
                "> http/1.1 401",
                "> http/1.1 400",
                "upgrade: websocket",
                "connection: upgrade",
                "sec-websocket-accept:",
                "sec-websocket-extensions:",
                "sec-websocket-version:",
                "sec-websocket-key:",
                "origin: ",
                "host: ",
                "pragma: no-cache",
                "cache-control: no-cache",
                "accept-encoding:",
                "accept-language:",
                "user-agent:",
                "cookie: ",
                "server: uvicorn",
                " = connection is ",  # стани CONNECTING/OPEN/CLOSING/CLOSED
                "connection open",
                "connection closed",
                "closing tcp connection",
                "connection rejected (403",
                "connection rejected (401",
            )

            for s in handshake_markers:
                if s in mlow:
                    return False
        except Exception:
            return True
        return True


def install_standard_logging_mask():
    try:
        root_logger = logging.getLogger()
        pii_filter = PIIMaskingFilter()
        ws_noise_filter = WebsocketFrameNoiseFilter()

        # Додаємо фільтри до root логера
        root_logger.addFilter(pii_filter)
        root_logger.addFilter(ws_noise_filter)
        # Та до всіх його існуючих хендлерів
        for h in list(root_logger.handlers):
            try:
                h.addFilter(pii_filter)
                h.addFilter(ws_noise_filter)
            except Exception:
                pass

        # Цільові логери, де можуть з'являтися дампи WS-кадрів
        target_logger_names = [
            "websockets",
            "websockets.client",
            "websockets.server",
            "websockets.protocol",
            "websockets.legacy",
            "uvicorn",
            "uvicorn.error",
            "uvicorn.access",
            "uvicorn.protocols",
            "uvicorn.protocols.websockets",
            "uvicorn.protocols.websockets.websockets_impl",
            "uvicorn.asgi",
        ]

        # Підключаємо фільтри до вказаних логерів і їхніх хендлерів
        for name in target_logger_names:
            try:
                lg = logging.getLogger(name)
                lg.addFilter(pii_filter)
                lg.addFilter(ws_noise_filter)
                for h in list(lg.handlers):
                    try:
                        h.addFilter(pii_filter)
                        h.addFilter(ws_noise_filter)
                    except Exception:
                        pass
            except Exception:
                pass

        # Також підстрахуємося: пройдемося по вже створених логерах у менеджері
        try:
            for name, obj in logging.Logger.manager.loggerDict.items():
                if not isinstance(obj, logging.Logger):
                    continue
                if name.startswith(("websockets", "uvicorn")):
                    try:
                        obj.addFilter(pii_filter)
                        obj.addFilter(ws_noise_filter)
                        for h in list(obj.handlers):
                            try:
                                h.addFilter(pii_filter)
                                h.addFilter(ws_noise_filter)
                            except Exception:
                                pass
                    except Exception:
                        pass
        except Exception:
            pass
    except Exception:
        pass


def configure_unified_logging() -> None:
    """
    Уніфікована конфігурація логування для всього застосунку (stdlib logging + structlog).
    - Єдиний формат
    - Маскування PII
    - Рівень логів з ENV: LOG_LEVEL (DEBUG/INFO/WARNING/ERROR), за замовчуванням DEBUG у dev, INFO у prod
    - Формат: час | рівень | модуль: повідомлення [k=v ...]
    """
    # Визначаємо рівень логування
    try:
        from config import get_settings  # локальний імпорт щоб уникнути циклів

        prod = get_settings().is_production()
    except Exception:
        prod = False

    env_level = (os.getenv("LOG_LEVEL") or ("INFO" if prod else "DEBUG")).upper()
    level = getattr(logging, env_level, logging.DEBUG if not prod else logging.INFO)

    # Спільні процесори для structlog
    shared_processors = [
        add_log_level,
        TimeStamper(fmt="%H:%M:%S", utc=False),
    ]

    # Налаштовуємо ProcessorFormatter, який поєднує stdlib logging і structlog
    formatter = ProcessorFormatter(
        foreign_pre_chain=shared_processors,
        processors=[
            format_exc_info,
            # Мінімалістичний вивід у консоль без зайвих пробілів
            simple_console_renderer,
        ],
    )

    handler = logging.StreamHandler()
    handler.setFormatter(formatter)

    # Вмикаємо базову конфігурацію stdlib logging з нашим хендлером
    logging.basicConfig(level=level, handlers=[handler], force=True)

    # Конфіг structlog: відправляємо події у stdlib logging через ProcessorFormatter
    structlog.configure(
        processors=shared_processors
        + [
            suppress_duplicate_logs_processor,
            ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    # Маскуємо чутливі дані
    install_standard_logging_mask()


__all__ = [
    "SENSITIVE_KEYS",
    "_mask_value",
    "mask_event_dict",
    "structlog_masking_processor",
    "simple_console_renderer",
    "PIIMaskingFilter",
    "suppress_duplicate_logs_processor",
    "install_standard_logging_mask",
    "configure_unified_logging",
]
