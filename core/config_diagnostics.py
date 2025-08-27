"""Security configuration diagnostics for TetraCore Hub.

Produces a structured report of security-related configuration issues
with severities: critical, warning, info.
"""

from __future__ import annotations

import os
import ipaddress
from typing import Dict, Any, List


def _bool(env: str, default: bool = False) -> bool:
    """Повертає булеве значення з прапора в змінній середовища.

    Args:
        env: Назва змінної середовища.
        default: Значення за замовчуванням, якщо змінна відсутня.

    Returns:
        True, якщо значення схоже на '1/true/yes/on', інакше False.
    """
    val = os.getenv(env)
    if val is None:
        return default
    return val.strip().lower() in ("1", "true", "yes", "on")


def _add(
    issues: List[Dict[str, Any]],
    severity: str,
    code: str,
    message: str,
    remedy: str | None = None,
):
    """Додає запис у список діагностик.

    Args:
        issues: Мутабельний список, куди додається запис.
        severity: Рівень серйозності: critical|warning|info.
        code: Короткий код проблеми.
        message: Людинозрозумілий опис.
        remedy: Підказка щодо виправлення або None.
    """
    issues.append(
        {
            "severity": severity,
            "code": code,
            "message": message,
            "remedy": remedy,
        }
    )


def _check_jwt(issues: List[Dict[str, Any]], prod: bool) -> None:
    """Перевірки JWT/токенів."""
    jwt_alg = os.getenv("JWT_ALGORITHM", "HS256").upper()
    enforce_claims = _bool("ENFORCE_JWT_CLAIMS", prod)
    rotate_refresh = _bool("ROTATE_REFRESH_TOKENS", False)
    kid = os.getenv("JWT_KEY_ID")
    pub_pem = os.getenv("JWT_PUBLIC_KEY_PEM")
    priv_pem = os.getenv("JWT_PRIVATE_KEY_PEM")
    secret_key = os.getenv("SECRET_KEY", "")

    if prod:
        if jwt_alg.startswith("HS"):
            if len(secret_key) < 32:
                _add(
                    issues,
                    "critical",
                    "JWT_SECRET_WEAK",
                    "SECRET_KEY занадто короткий для HS* у проді",
                    "Використати RS256 з ключами або довший секрет (>=32) і краще RS/EdDSA",
                )
        else:
            if not pub_pem or not priv_pem:
                _add(
                    issues,
                    "critical",
                    "JWT_KEYS_MISSING",
                    "Відсутні пари асиметричних ключів JWT (PUBLIC/PRIVATE)",
                    "Встановити JWT_PRIVATE_KEY_PEM і JWT_PUBLIC_KEY_PEM",
                )
            if not kid:
                _add(
                    issues,
                    "warning",
                    "JWT_KID_MISSING",
                    "Відсутній JWT_KEY_ID для JWKS ротації",
                    "Задати JWT_KEY_ID",
                )
        if not enforce_claims:
            _add(
                issues,
                "warning",
                "JWT_CLAIMS_DISABLED",
                "Перевірка iss/aud вимкнена у проді",
                "ENFORCE_JWT_CLAIMS=true",
            )
        if not rotate_refresh:
            _add(
                issues,
                "warning",
                "REFRESH_ROTATION_DISABLED",
                "Ротація refresh токенів вимкнена",
                "ROTATE_REFRESH_TOKENS=true",
            )


def _check_proxy(issues: List[Dict[str, Any]], prod: bool) -> None:
    """Перевірки довірених проксі/IP клієнта."""
    trusted = [
        ip.strip() for ip in os.getenv("TRUSTED_PROXY_IPS", "").split(",") if ip.strip()
    ]
    if prod:
        if not trusted:
            _add(
                issues,
                "warning",
                "PROXY_TRUST_EMPTY",
                "TRUSTED_PROXY_IPS не заданий у проді",
                "Задати IP балансера/проксі",
            )
        else:
            for ip in trusted:
                try:
                    ipaddress.ip_address(ip)
                except ValueError:
                    _add(
                        issues,
                        "warning",
                        "PROXY_TRUST_INVALID",
                        f"Невалідний IP у TRUSTED_PROXY_IPS: {ip}",
                        "Вказати коректні IP-адреси",
                    )


def _read_cors_hosts(settings) -> tuple[list[str], list[str]]:
    """Збирає списки ALLOWED_ORIGINS та ALLOWED_HOSTS."""
    allowed_origins = os.getenv(
        "ALLOWED_ORIGINS", ",".join(settings.allowed_origins or [])
    ).split(",")
    allowed_origins = [o.strip() for o in allowed_origins if o.strip()]
    allowed_hosts = os.getenv("ALLOWED_HOSTS", "").split(",")
    allowed_hosts = [h.strip() for h in allowed_hosts if h.strip()]
    return allowed_origins, allowed_hosts


def _check_cors_hosts(
    issues: List[Dict[str, Any]],
    prod: bool,
    allowed_origins: list[str],
    allowed_hosts: list[str],
) -> None:
    """Перевірки CORS/Hosts."""
    if prod:
        if not allowed_origins:
            _add(
                issues,
                "warning",
                "CORS_EMPTY",
                "ALLOWED_ORIGINS порожній у проді",
                "Додати прод-домени у ALLOWED_ORIGINS",
            )
        if "*" in allowed_origins:
            _add(
                issues,
                "critical",
                "CORS_WILDCARD",
                "CORS містить '*' у проді",
                "Прибрати '*' із ALLOWED_ORIGINS",
            )
        if not allowed_hosts:
            _add(
                issues,
                "warning",
                "HOSTS_EMPTY",
                "ALLOWED_HOSTS порожній у проді",
                "Додати прод-хости у ALLOWED_HOSTS",
            )
        if any(h == "*" for h in allowed_hosts):
            _add(
                issues,
                "warning",
                "HOSTS_WILDCARD",
                "ALLOWED_HOSTS містить '*'",
                "Прибрати wildcard у ALLOWED_HOSTS",
            )


def _check_redis(issues: List[Dict[str, Any]]) -> None:
    """Перевірки Redis/TLS (REDIS_ENABLED використовується як тригер)."""
    if os.getenv("REDIS_ENABLED") is not None:
        url = os.getenv("REDISCLOUD_URL", "")
        tls_cert_reqs = os.getenv("REDIS_SSL_CERT_REQS", "required").lower()
        check_host = os.getenv("REDIS_SSL_CHECK_HOSTNAME", "true").lower() in (
            "1",
            "true",
            "yes",
        )
        if url.startswith("rediss://"):
            if tls_cert_reqs != "required":
                _add(
                    issues,
                    "warning",
                    "REDIS_TLS_WEAK",
                    "REDIS_SSL_CERT_REQS != 'required' при TLS",
                    "Встановити REDIS_SSL_CERT_REQS=required",
                )
            if not check_host:
                _add(
                    issues,
                    "warning",
                    "REDIS_TLS_HOSTNAME",
                    "REDIS_SSL_CHECK_HOSTNAME вимкнено",
                    "Увімкнути REDIS_SSL_CHECK_HOSTNAME=true",
                )
        else:
            _add(
                issues,
                "warning",
                "REDIS_NO_TLS",
                "REDISCLOUD_URL без TLS (не rediss://)",
                "Використати TLS (rediss://)",
            )


def _check_secret_provider(issues: List[Dict[str, Any]], prod: bool) -> None:
    """Перевірка джерела секретів."""
    secret_provider = os.getenv("SECRET_PROVIDER", "env").lower()
    if prod and secret_provider == "env":
        _add(
            issues,
            "critical",
            "SECRETS_ENV",
            "SECRET_PROVIDER=env у проді",
            "Використати AWS/Vault секрети",
        )


def _check_auth_admin(issues: List[Dict[str, Any]], prod: bool) -> None:
    """Перевірка автентифікації та адмін-паролю."""
    require_auth = _bool("REQUIRE_AUTHENTICATION", True)
    if prod and not require_auth:
        _add(
            issues,
            "critical",
            "AUTH_DISABLED",
            "REQUIRE_AUTHENTICATION=false у проді",
            "Увімкнути автентифікацію",
        )
    admin_password = os.getenv("ADMIN_PASSWORD")
    if prod and admin_password and not admin_password.startswith("$2"):
        _add(
            issues,
            "critical",
            "ADMIN_PLAIN",
            "ADMIN_PASSWORD не є bcrypt-хешем у проді",
            "Встановити bcrypt-хеш у ADMIN_PASSWORD",
        )


def _check_docs_endpoints(issues: List[Dict[str, Any]], prod: bool, env: str) -> None:
    """Перевірка безпечності службових ендпоінтів."""
    enable_sec_endpoints = _bool("ENABLE_SECURITY_ENDPOINTS", env == "development")
    if prod and enable_sec_endpoints:
        _add(
            issues,
            "warning",
            "SEC_ENDPOINTS_ENABLED",
            "ENABLE_SECURITY_ENDPOINTS=true у проді",
            "Вимкнути ENABLE_SECURITY_ENDPOINTS",
        )


def _check_https(issues: List[Dict[str, Any]], prod: bool) -> None:
    """Перевірка форсування HTTPS."""
    force_https = _bool("FORCE_HTTPS", prod)
    if prod and not force_https:
        _add(
            issues,
            "warning",
            "HTTPS_NOT_FORCED",
            "FORCE_HTTPS вимкнено у проді",
            "FORCE_HTTPS=true",
        )


def _check_logging(issues: List[Dict[str, Any]], prod: bool) -> None:
    """Перевірка рівня логування."""
    log_level = os.getenv("LOG_LEVEL", "INFO").upper()
    if prod and log_level == "DEBUG":
        _add(
            issues,
            "warning",
            "DEBUG_LOG",
            "LOG_LEVEL=DEBUG у проді",
            "Змінити на INFO або вище",
        )


def _check_trusted_host_middleware(issues: List[Dict[str, Any]], prod: bool) -> None:
    """Перевірка TrustedHostMiddleware."""
    if prod and os.getenv("DISABLE_TRUSTED_HOST_MW", "").lower() in (
        "1",
        "true",
        "yes",
    ):
        _add(
            issues,
            "critical",
            "TRUSTED_HOST_DISABLED",
            "Вимкнено TrustedHostMiddleware у проді",
            "Прибрати DISABLE_TRUSTED_HOST_MW",
        )


def _check_ws(issues: List[Dict[str, Any]], prod: bool) -> None:
    """Перевірка статичного AUTH_TOKEN для WS."""
    auth_token = os.getenv("AUTH_TOKEN")
    if prod and auth_token:
        _add(
            issues,
            "info",
            "WS_STATIC_TOKEN",
            "Встановлено статичний AUTH_TOKEN для WS (переконайтесь у його мінімальному доступі)",
            "Розглянути перехід на JWT тільки",
        )


def run_security_config_diagnostics(settings) -> Dict[str, Any]:
    """Виконує діагностику налаштувань безпеки.

    Приймає об'єкт `settings` (очікується, що має властивості на кшталт
    `allowed_origins`, `redis_url` тощо) і повертає словник зі структурованим
    звітом: список `issues` з полями `severity`, `code`, `message`, `remedy`,
    а також допоміжні метадані за потреби.
    """
    env = os.getenv("ENVIRONMENT", "development").lower()
    prod = env == "production"

    issues: List[Dict[str, Any]] = []

    # Перевірки
    _check_jwt(issues, prod)
    _check_proxy(issues, prod)
    allowed_origins, allowed_hosts = _read_cors_hosts(settings)
    _check_cors_hosts(issues, prod, allowed_origins, allowed_hosts)
    _check_redis(issues)
    _check_secret_provider(issues, prod)
    _check_auth_admin(issues, prod)
    _check_docs_endpoints(issues, prod, env)
    _check_https(issues, prod)
    _check_logging(issues, prod)
    _check_trusted_host_middleware(issues, prod)
    _check_ws(issues, prod)

    status = (
        "ok" if not any(i["severity"] == "critical" for i in issues) else "attention"
    )
    return {
        "environment": env,
        "status": status,
        "issues": issues,
    }
