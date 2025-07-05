"""
Custom CORS middleware for dynamic origin handling
"""

from typing import List, Optional, Union
from fastapi import Request
from fastapi.responses import Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp
import re
import structlog

logger = structlog.get_logger(__name__)


class DynamicCORSMiddleware(BaseHTTPMiddleware):
    """
    Dynamic CORS middleware that handles:
    - Same-origin requests
    - Configured allowed origins
    - Wildcard patterns
    - Preflight requests
    """

    def __init__(
        self,
        app: ASGIApp,
        allowed_origins: List[str] = None,
        allow_credentials: bool = True,
        allow_methods: List[str] = None,
        allow_headers: List[str] = None,
        expose_headers: List[str] = None,
        max_age: int = 600,
    ):
        super().__init__(app)
        self.allowed_origins = allowed_origins or []
        self.allow_credentials = allow_credentials
        self.allow_methods = allow_methods or ["*"]
        self.allow_headers = allow_headers or ["*"]
        self.expose_headers = expose_headers or ["*"]
        self.max_age = max_age

        # Compile regex patterns for wildcard origins
        self.origin_patterns = []
        for origin in self.allowed_origins:
            if "*" in origin and origin != "*":
                # Convert wildcard to regex pattern
                pattern = origin.replace(".", r"\.").replace("*", r"[^/]+")
                self.origin_patterns.append(re.compile(f"^{pattern}$"))

    def is_allowed_origin(self, origin: str) -> bool:
        """Check if the origin is allowed"""
        if not origin:
            return False

        # Check exact matches
        if origin in self.allowed_origins:
            return True

        # Check wildcard "*" (allow all)
        if "*" in self.allowed_origins:
            return True

        # Check regex patterns (for wildcard domains)
        for pattern in self.origin_patterns:
            if pattern.match(origin):
                return True

        return False

    def is_same_origin(self, request: Request, origin: str) -> bool:
        """Check if request is from the same origin"""
        if not origin:
            return False

        # Get the request's scheme and host
        scheme = request.url.scheme
        host = request.headers.get("host", "")

        # Construct the expected origin
        expected_origin = f"{scheme}://{host}"

        return origin == expected_origin

    async def dispatch(self, request: Request, call_next):
        """Process the request and add CORS headers"""
        origin = request.headers.get("origin")

        # Handle preflight OPTIONS requests
        if request.method == "OPTIONS":
            response = Response(status_code=200)

            # Add CORS headers
            if origin and (self.is_allowed_origin(origin) or self.is_same_origin(request, origin)):
                response.headers["Access-Control-Allow-Origin"] = origin
                response.headers["Access-Control-Allow-Credentials"] = str(self.allow_credentials).lower()
                response.headers["Access-Control-Allow-Methods"] = ", ".join(self.allow_methods)
                response.headers["Access-Control-Allow-Headers"] = ", ".join(self.allow_headers)
                response.headers["Access-Control-Max-Age"] = str(self.max_age)

                if self.expose_headers:
                    response.headers["Access-Control-Expose-Headers"] = ", ".join(self.expose_headers)

            return response

        # Process the actual request
        response = await call_next(request)

        # Add CORS headers to the response
        if origin:
            # Check if origin is allowed or is same-origin
            if self.is_allowed_origin(origin) or self.is_same_origin(request, origin):
                response.headers["Access-Control-Allow-Origin"] = origin
                response.headers["Access-Control-Allow-Credentials"] = str(self.allow_credentials).lower()

                if self.expose_headers:
                    response.headers["Access-Control-Expose-Headers"] = ", ".join(self.expose_headers)

                # Log successful CORS handling
                logger.debug("CORS headers added",
                           origin=origin,
                           method=request.method,
                           path=request.url.path)
            else:
                # Log rejected origin
                logger.warning("CORS origin rejected",
                             origin=origin,
                             allowed_origins=self.allowed_origins,
                             path=request.url.path)

        return response


def setup_cors(app, settings):
    """Setup CORS middleware with settings"""
    # Get allowed origins from settings
    allowed_origins = settings.allowed_origins.copy() if hasattr(settings, 'allowed_origins') else []

    # In production, add common patterns
    if settings.environment.value == "production":
        # Add herokuapp domains
        allowed_origins.extend([
            "https://*.herokuapp.com",
            "https://*.heroku.com"
        ])

        # Add custom domain
        if hasattr(settings, 'custom_domain'):
            allowed_origins.append(f"https://{settings.custom_domain}")
            allowed_origins.append(f"http://{settings.custom_domain}")  # For local testing

    # Remove duplicates
    allowed_origins = list(set(allowed_origins))

    logger.info("Setting up CORS",
               allowed_origins=allowed_origins,
               environment=settings.environment.value)

    # Add the middleware
    app.add_middleware(
        DynamicCORSMiddleware,
        allowed_origins=allowed_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "PATCH"],
        allow_headers=["*"],
        expose_headers=["*"],
        max_age=3600
    )
