"""
Security Headers Module for TetraCore Hub
Розширені security headers та Content Security Policy
"""

import os
import secrets
from typing import Dict, List, Optional, Set, Any
from datetime import datetime

from fastapi import Request, Response, APIRouter
from fastapi.responses import JSONResponse
import structlog

logger = structlog.get_logger()

# Константи для CSP
CSP_REPORT_URI = "/api/security/csp-report"
NONCE_LENGTH = 32
CSP_DIRECTIVE_SEPARATOR = "; "


class SecurityHeadersManager:
    """Менеджер для управління security headers"""

    def __init__(self, environment: str = "production"):
        self.environment = environment
        self.nonce_cache: Set[str] = set()
        self.csp_violations: List[Dict] = []
        self.report_only_mode = environment == "development"

        # Базові security headers
        self.base_headers = self._get_base_headers()

        # CSP директиви
        self.csp_directives = self._get_csp_directives()

        # Дозволені джерела для різних середовищ
        self.allowed_sources = self._get_allowed_sources()

    def _get_base_headers(self) -> Dict[str, str]:
        """Отримання базових security headers"""
        headers = {
            # Захист від XSS
            "X-XSS-Protection": "1; mode=block",
            # Захист від clickjacking
            "X-Frame-Options": "DENY",
            # Заборона MIME type sniffing
            "X-Content-Type-Options": "nosniff",
            # Referrer Policy
            "Referrer-Policy": "strict-origin-when-cross-origin",
            # Permissions Policy (раніше Feature Policy)
            "Permissions-Policy": self._build_permissions_policy(),
            # Захист від DNS prefetch
            "X-DNS-Prefetch-Control": "off",
            # Вимкнення IE compatibility mode
            "X-UA-Compatible": "IE=edge",
            # Захист від download атак
            "X-Download-Options": "noopen",
            # Очікування Certificate Transparency
            "Expect-CT": "max-age=86400, enforce",
            # Cross-Origin políticas
            "Cross-Origin-Embedder-Policy": "require-corp",
            "Cross-Origin-Opener-Policy": "same-origin",
            "Cross-Origin-Resource-Policy": "same-origin",
            "X-Permitted-Cross-Domain-Policies": "none",
        }

        # HSTS тільки для production
        if self.environment == "production":
            headers["Strict-Transport-Security"] = (
                "max-age=31536000; includeSubDomains; preload"
            )

        return headers

    def _get_csp_directives(self) -> Dict[str, List[str]]:
        """Отримання CSP директив"""
        return {
            "default-src": ["'self'"],
            "script-src": ["'self'"],
            "style-src": ["'self'"],
            "img-src": ["'self'", "data:", "https:"],
            "font-src": ["'self'", "data:"],
            "connect-src": ["'self'"],
            "media-src": ["'self'"],
            "object-src": ["'none'"],
            "frame-src": ["'none'"],
            "base-uri": ["'self'"],
            "form-action": ["'self'"],
            "frame-ancestors": ["'none'"],
            "block-all-mixed-content": [],
            "upgrade-insecure-requests": [],
        }

    def _get_allowed_sources(self) -> Dict[str, List[str]]:
        """Отримання дозволених джерел для різних середовищ"""
        sources = {
            "development": {
                "connect-src": [
                    "http://localhost:*",
                    "ws://localhost:*",
                    "http://127.0.0.1:*",
                    "ws://127.0.0.1:*",
                ],
                "script-src": [
                    "http://localhost:*",
                    "'unsafe-eval'",  # Для React DevTools
                ],
            },
            "production": {
                "connect-src": [
                    "https://hub.tetra-core.website",
                    "wss://hub.tetra-core.website",
                    "https://tetra-core-hub-29fb6c8b7947.herokuapp.com",
                    "wss://tetra-core-hub-29fb6c8b7947.herokuapp.com",
                ],
                "script-src": [],
                "style-src": ["https://fonts.googleapis.com"],
                "font-src": ["https://fonts.gstatic.com"],
            },
        }

        return sources.get(self.environment, sources["production"])

    def _build_permissions_policy(self) -> str:
        """Побудова Permissions Policy (лише підтримувані директиви)"""
        policies = {
            # Камера/мікрофон/геолокація — заборонені за замовчуванням
            "camera": "()",
            "microphone": "()",
            "geolocation": "()",
            # Відтворення/медіа
            "autoplay": "(self)",
            "encrypted-media": "()",
            "picture-in-picture": "()",
            "display-capture": "()",
            # UX/поведінка
            "fullscreen": "(self)",
            "publickey-credentials-get": "()",
            "screen-wake-lock": "()",
            "web-share": "()",
            # WebXR (підтримується у Chromium)
            "xr-spatial-tracking": "()",
        }

        return ", ".join(f"{key}={value}" for key, value in policies.items())

    def generate_nonce(self) -> str:
        """Генерація унікального nonce для inline scripts"""
        nonce = secrets.token_urlsafe(NONCE_LENGTH)
        self.nonce_cache.add(nonce)

        # Очищення старих nonce (зберігаємо тільки останні 100)
        if len(self.nonce_cache) > 100:
            self.nonce_cache = set(list(self.nonce_cache)[-100:])

        return nonce

    def build_csp_header(self, nonce: Optional[str] = None) -> str:
        """Побудова CSP header"""
        directives = self.csp_directives.copy()

        # Додавання nonce для скриптів якщо потрібно
        if nonce:
            script_src = directives.get("script-src", []).copy()
            script_src.append(f"'nonce-{nonce}'")
            directives["script-src"] = script_src

        # Додавання дозволених джерел для середовищ з дедуплікацією
        env_sources = self.allowed_sources
        for directive, sources in env_sources.items():
            if directive in directives:
                # Використовуємо set для видалення дублікатів, потім повертаємо до list
                existing_sources = set(directives[directive])
                new_sources = set(sources)
                directives[directive] = list(existing_sources | new_sources)

        # Додавання report-uri
        if self.environment == "production":
            directives["report-uri"] = [CSP_REPORT_URI]

        # Побудова фінального header з обмеженням довжини
        csp_parts = []
        for directive, sources in directives.items():
            if sources:
                # Обмежуємо кількість джерел для запобігання header overflow
                limited_sources = sources[:10] if len(sources) > 10 else sources
                csp_parts.append(f"{directive} {' '.join(limited_sources)}")
            else:
                csp_parts.append(directive)

        csp_header = CSP_DIRECTIVE_SEPARATOR.join(csp_parts)

        # Перевірка довжини заголовка (HTTP headers мають обмеження ~8KB)
        if len(csp_header) > 8000:
            logger.warning("CSP header too long, truncating", length=len(csp_header))
            # Спрощуємо CSP для запобігання header overflow
            return self._build_simplified_csp_header(nonce)

        return csp_header

    def _build_simplified_csp_header(self, nonce: Optional[str] = None) -> str:
        """Побудова спрощеного CSP header для запобігання header overflow"""
        # Базові директиви без повторень
        simplified_directives = {
            "default-src": ["'self'"],
            "script-src": ["'self'", "'unsafe-inline'", "'unsafe-eval'"],
            "style-src": ["'self'", "'unsafe-inline'", "https://fonts.googleapis.com"],
            "img-src": ["'self'", "data:", "https:"],
            "font-src": ["'self'", "data:", "https://fonts.gstatic.com"],
            "connect-src": ["'self'"],
            "media-src": ["'self'"],
            "object-src": ["'none'"],
            "frame-src": ["'none'"],
            "base-uri": ["'self'"],
            "form-action": ["'self'"],
            "frame-ancestors": ["'none'"],
        }

        # Додавання nonce якщо потрібно
        if nonce:
            simplified_directives["script-src"].append(f"'nonce-{nonce}'")

        # Додавання connect-src для середовища
        if self.environment == "development":
            simplified_directives["connect-src"].extend(
                ["ws://localhost:8000", "http://localhost:8000"]
            )
        else:
            simplified_directives["connect-src"].extend(
                ["https://hub.tetra-core.website", "wss://hub.tetra-core.website"]
            )

        # Побудова header
        csp_parts = []
        for directive, sources in simplified_directives.items():
            if sources:
                csp_parts.append(f"{directive} {' '.join(sources)}")
            else:
                csp_parts.append(directive)

        return CSP_DIRECTIVE_SEPARATOR.join(csp_parts)

    def apply_headers(
        self, response: Response, request: Request, nonce: Optional[str] = None
    ):
        """Застосування всіх security headers до відповіді"""
        # Базові headers
        for header, value in self.base_headers.items():
            response.headers[header] = value

        # Content Security Policy
        csp = self.build_csp_header(nonce)
        if self.report_only_mode:
            response.headers["Content-Security-Policy-Report-Only"] = csp
        else:
            response.headers["Content-Security-Policy"] = csp

        # Заборона індексації конфіденційних сторінок
        if request.url.path.startswith(("/dashboard", "/api")):
            response.headers["X-Robots-Tag"] = "noindex, nofollow, noarchive, nosnippet"

        # Додаткові headers для API endpoints
        if request.url.path.startswith("/api/"):
            response.headers["X-Content-Type-Options"] = "nosniff"
            response.headers["Content-Type"] = "application/json"

        # Cache control для чутливих endpoints
        if request.url.path.startswith(("/api/auth/", "/api/admin/")):
            response.headers["Cache-Control"] = (
                "no-store, no-cache, must-revalidate, private"
            )
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"

    def validate_csp_report(self, report_data: Dict[str, Any]) -> bool:
        """Валідація CSP violation report"""
        required_fields = ["document-uri", "violated-directive", "blocked-uri"]
        csp_report = report_data.get("csp-report", {})

        # Перевірка обов'язкових полів
        for field in required_fields:
            if field not in csp_report:
                return False

        # Додаткові перевірки
        blocked_uri = csp_report.get("blocked-uri", "")

        # Ігноруємо відомі false positives
        if blocked_uri in ["about", "data", "blob"]:
            return False

        # Ігноруємо browser extensions
        if blocked_uri.startswith(("chrome-extension://", "moz-extension://")):
            return False

        return True

    async def handle_csp_report(self, request: Request) -> JSONResponse:
        """Обробка CSP violation reports"""
        try:
            report_data = await request.json()

            if not self.validate_csp_report(report_data):
                return JSONResponse({"status": "ignored"}, status_code=200)

            # Логування violation
            csp_report = report_data.get("csp-report", {})
            logger.warning(
                "CSP Violation",
                document_uri=csp_report.get("document-uri"),
                violated_directive=csp_report.get("violated-directive"),
                blocked_uri=csp_report.get("blocked-uri"),
                source_file=csp_report.get("source-file"),
                line_number=csp_report.get("line-number"),
            )

            # Збереження для аналізу
            self.csp_violations.append(
                {
                    "timestamp": datetime.utcnow().isoformat(),
                    "report": csp_report,
                    "user_agent": request.headers.get("User-Agent"),
                    "ip": request.client.host if request.client else "unknown",
                }
            )

            # Обмеження розміру кешу
            if len(self.csp_violations) > 1000:
                self.csp_violations = self.csp_violations[-1000:]

            return JSONResponse({"status": "received"}, status_code=200)

        except Exception as e:
            logger.error("Error processing CSP report", error=str(e))
            return JSONResponse({"status": "error"}, status_code=400)

    def get_security_headers_info(self) -> Dict[str, Any]:
        """Отримання інформації про налаштовані headers"""
        return {
            "environment": self.environment,
            "report_only_mode": self.report_only_mode,
            "total_headers": len(self.base_headers),
            "csp_directives": len(self.csp_directives),
            "active_nonces": len(self.nonce_cache),
            "csp_violations": len(self.csp_violations),
            "headers": {
                name: value[:50] + "..." if len(value) > 50 else value
                for name, value in self.base_headers.items()
            },
        }

    def check_header_compatibility(self, user_agent: str) -> Dict[str, bool]:
        """Перевірка сумісності headers з браузером"""
        ua_lower = user_agent.lower()

        compatibility = {
            "csp": True,  # Підтримується всіма сучасними браузерами
            "hsts": True,
            "x_frame_options": True,
            "x_content_type_options": True,
            "permissions_policy": "chrome" in ua_lower or "firefox" in ua_lower,
            "cross_origin_policies": "chrome" in ua_lower or "firefox" in ua_lower,
        }

        # Старі версії IE
        if "msie" in ua_lower or "trident" in ua_lower:
            compatibility["permissions_policy"] = False
            compatibility["cross_origin_policies"] = False

        return compatibility


# Глобальний екземпляр з правильним environment
environment = os.getenv("ENVIRONMENT", "development")
security_headers = SecurityHeadersManager(environment=environment)


# Middleware для автоматичного додавання headers
async def security_headers_middleware(request: Request, call_next):
    """Middleware для додавання security headers до всіх відповідей"""
    # Генерація nonce для цього запиту
    nonce = (
        security_headers.generate_nonce()
        if request.url.path.endswith(".html")
        else None
    )

    # Додавання nonce до request state для використання в templates
    request.state.csp_nonce = nonce

    # Обробка запиту
    response = await call_next(request)

    # Застосування headers
    security_headers.apply_headers(response, request, nonce)

    return response


# API endpoint для CSP reports
security_headers_router = APIRouter(prefix="/api/security", tags=["security"])


@security_headers_router.post("/csp-report")
async def csp_report_endpoint(request: Request):
    """Endpoint для прийому CSP violation reports"""
    return await security_headers.handle_csp_report(request)


@security_headers_router.get("/headers-info")
async def get_headers_info():
    """Отримання інформації про security headers"""
    return security_headers.get_security_headers_info()


@security_headers_router.get("/csp-violations")
async def get_csp_violations(limit: int = 100):
    """Отримання останніх CSP violations"""
    violations = security_headers.csp_violations[-limit:]
    return {"total": len(security_headers.csp_violations), "violations": violations}
