"""
Input Validation Module for TetraCore Hub
Безпечна валідація та санітизація вхідних даних
"""

import re
import html
import json
import ipaddress
from typing import Any, Dict, List, Optional, Union, Callable, TypeVar
from datetime import datetime, date
from decimal import Decimal
from urllib.parse import urlparse, quote
import bleach
import structlog
from pydantic import (
    BaseModel, Field, field_validator, model_validator,
    constr, conint, confloat, HttpUrl, EmailStr,
    ValidationError, ConfigDict
)
from pydantic.functional_validators import AfterValidator
from typing import Annotated

logger = structlog.get_logger()

# Типи для генериків
T = TypeVar('T')

# Константи для валідації
MAX_STRING_LENGTH = 10000
MAX_LIST_LENGTH = 1000
MAX_DICT_DEPTH = 10
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB
ALLOWED_FILE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.gif', '.pdf', '.txt', '.csv', '.json'}
ALLOWED_MIME_TYPES = {
    'image/jpeg', 'image/png', 'image/gif',
    'application/pdf', 'text/plain', 'text/csv',
    'application/json'
}

# Regex patterns для валідації
PATTERNS = {
    'username': re.compile(r'^[a-zA-Z0-9_-]{3,30}$'),
    'slug': re.compile(r'^[a-z0-9]+(?:-[a-z0-9]+)*$'),
    'phone': re.compile(r'^\+?[1-9]\d{1,14}$'),
    'alphanumeric': re.compile(r'^[a-zA-Z0-9]+$'),
    'safe_string': re.compile(r'^[a-zA-Z0-9\s\-_.,!?]+$'),
    'uuid': re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'),
    'hex_color': re.compile(r'^#[0-9A-Fa-f]{6}$'),
    'version': re.compile(r'^\d+\.\d+\.\d+$')
}

# SQL injection patterns
SQL_INJECTION_PATTERNS = [
    r'(\b(SELECT|INSERT|UPDATE|DELETE|DROP|UNION|CREATE|ALTER|EXEC|EXECUTE)\b)',
    r'(-{2}|\/\*|\*\/)',  # SQL comments
    r'(\bOR\b.*=.*)',  # OR conditions
    r'(\'|\"|;|\\)',  # Quotes and semicolons
    r'(\bAND\b.*=.*)',  # AND conditions
]

# XSS patterns
XSS_PATTERNS = [
    r'<script[^>]*>.*?</script>',
    r'javascript:',
    r'on\w+\s*=',  # Event handlers
    r'<iframe[^>]*>',
    r'<object[^>]*>',
    r'<embed[^>]*>',
    r'<link[^>]*>',
    r'vbscript:',
    r'data:text/html',
]

# Path traversal patterns
PATH_TRAVERSAL_PATTERNS = [
    r'\.\.',  # Parent directory
    r'\.\./',
    r'\.\.\\',
    r'%2e%2e',  # URL encoded
    r'%252e%252e',  # Double URL encoded
]

# Command injection patterns
COMMAND_INJECTION_PATTERNS = [
    r';\s*(ls|cat|rm|mv|cp|chmod|chown|wget|curl|nc|bash|sh|python|perl|ruby|php)',
    r'\|\s*(ls|cat|rm|mv|cp|chmod|chown|wget|curl|nc|bash|sh|python|perl|ruby|php)',
    r'&\s*(ls|cat|rm|mv|cp|chmod|chown|wget|curl|nc|bash|sh|python|perl|ruby|php)',
    r'`[^`]*`',  # Backticks
    r'\$\([^)]+\)',  # Command substitution
    r'\$\{[^}]+\}',  # Variable expansion
    r'>\s*/dev/null',  # Redirection
    r'2>&1',  # Stderr redirection
]


class ValidationError(Exception):
    """Кастомна помилка валідації"""
    def __init__(self, message: str, field: str = None, value: Any = None):
        self.message = message
        self.field = field
        self.value = value
        super().__init__(message)


class InputValidator:
    """Основний клас для валідації вхідних даних"""

    @staticmethod
    def sanitize_string(value: str, max_length: int = MAX_STRING_LENGTH,
                       allow_html: bool = False) -> str:
        """
        Санітизація рядка з видаленням небезпечних символів
        
        Args:
            value: Значення для санітизації
            max_length: Максимальна довжина рядка
            allow_html: Чи дозволяти HTML теги
            
        Returns:
            Санітизований рядок
        """
        if not isinstance(value, str):
            raise ValidationError("Input must be a string")
        
        # Unicode normalization to prevent bypass attempts
        import unicodedata
        value = unicodedata.normalize('NFKC', value)
        
        # Decode Unicode escapes
        try:
            value = value.encode('utf-8').decode('unicode-escape')
        except:
            pass
            
        # Remove null bytes
        value = value.replace('\x00', '')
        
        # Strip whitespace
        value = value.strip()
        
        # Check length before processing
        if max_length and len(value) > max_length:
            value = value[:max_length]
        
        if not allow_html:
            # Aggressive HTML sanitization
            # First, decode HTML entities multiple times
            import html
            for _ in range(3):  # Handle triple encoding
                prev = value
                value = html.unescape(value)
                if prev == value:
                    break
                    
            # Remove all HTML tags and dangerous patterns
            value = bleach.clean(value, tags=[], strip=True)
            
            # Additional sanitization for event handlers and javascript
            dangerous_patterns = [
                (r'on\w+\s*=', ''),  # Event handlers
                (r'javascript\s*:', ''),  # JavaScript protocol
                (r'vbscript\s*:', ''),  # VBScript protocol
                (r'data\s*:', ''),  # Data URLs
                (r'expression\s*\(', ''),  # CSS expressions
                (r'import\s*\(', ''),  # CSS imports
                (r'@import', ''),  # CSS imports
                (r'<!\[CDATA\[', ''),  # CDATA sections
                (r'\\\w{4,6}', ''),  # Unicode escapes
            ]
            
            for pattern, replacement in dangerous_patterns:
                value = re.sub(pattern, replacement, value, flags=re.IGNORECASE)
        else:
            # Санітизація з дозволеними тегами
            allowed_tags = ['p', 'br', 'strong', 'em', 'u', 'i', 'b']
            allowed_attributes = {}
            value = bleach.clean(
                value,
                tags=allowed_tags,
                attributes=allowed_attributes,
                strip=True
            )
        
        # Final length check after sanitization
        if max_length and len(value) > max_length:
            value = value[:max_length]
            
        return value

    @staticmethod
    def validate_pattern(value: str, pattern_name: str) -> bool:
        """Валідація за патерном"""
        pattern = PATTERNS.get(pattern_name)
        if not pattern:
            raise ValidationError(f"Unknown pattern: {pattern_name}")

        return bool(pattern.match(value))

    @staticmethod
    def check_sql_injection(value: str) -> bool:
        """Перевірка на SQL injection"""
        value_lower = value.lower()
        for pattern in SQL_INJECTION_PATTERNS:
            if re.search(pattern, value_lower, re.IGNORECASE):
                logger.warning("Potential SQL injection detected", value=value[:100])
                return True
        return False

    @staticmethod
    def check_xss(value: str) -> bool:
        """Перевірка на XSS"""
        value_lower = value.lower()
        for pattern in XSS_PATTERNS:
            if re.search(pattern, value_lower, re.IGNORECASE):
                logger.warning("Potential XSS detected", value=value[:100])
                return True
        return False

    @staticmethod
    def check_path_traversal(value: str) -> bool:
        """Перевірка на path traversal"""
        for pattern in PATH_TRAVERSAL_PATTERNS:
            if re.search(pattern, value, re.IGNORECASE):
                logger.warning("Potential path traversal detected", value=value)
                return True
        return False

    @staticmethod
    def check_command_injection(value: str) -> bool:
        """
        Перевірка на спроби command injection
        
        Args:
            value: Рядок для перевірки
            
        Returns:
            True якщо знайдено ознаки command injection
        """
        if not value:
            return False
            
        value_lower = value.lower()
        
        # Check against patterns
        for pattern in COMMAND_INJECTION_PATTERNS:
            if re.search(pattern, value, re.IGNORECASE):
                return True
                
        # Check for common command separators
        dangerous_chars = [';', '|', '&', '`', '$', '\n', '\r']
        if any(char in value for char in dangerous_chars):
            # Additional context check
            suspicious_commands = ['sh', 'bash', 'cmd', 'powershell', 'exec', 'system', 'eval']
            for cmd in suspicious_commands:
                if cmd in value_lower:
                    return True
                    
        return False

    @classmethod
    def validate_safe_string(cls, value: str, max_length: Optional[int] = None) -> str:
        """
        Валідація безпечного рядка
        
        Args:
            value: Рядок для валідації
            max_length: Максимальна довжина
            
        Returns:
            Валідований рядок
            
        Raises:
            ValidationError: Якщо рядок небезпечний
        """
        if not value:
            raise ValidationError("String cannot be empty")
        
        # Санітизація
        sanitized = cls.sanitize_string(value, max_length)
        
        # Перевірка на атаки
        if cls.check_sql_injection(sanitized):
            raise ValidationError("Potential SQL injection detected")
            
        if cls.check_xss(sanitized):
            raise ValidationError("Potential XSS attack detected")
            
        if cls.check_path_traversal(sanitized):
            raise ValidationError("Potential path traversal detected")
            
        if cls.check_command_injection(sanitized):
            raise ValidationError("Potential command injection detected")
        
        return sanitized

    @classmethod
    def validate_username(cls, username: str) -> str:
        """Валідація username"""
        if not cls.validate_pattern(username, 'username'):
            raise ValidationError(
                "Username must be 3-30 characters and contain only letters, numbers, _ or -",
                field="username"
            )
        return username.lower()

    @classmethod
    def validate_email(cls, email: str) -> str:
        """Валідація email"""
        try:
            # Використовуємо Pydantic EmailStr
            validated = EmailStr.validate(email)
            return validated.lower()
        except Exception:
            raise ValidationError("Invalid email format", field="email")

    @classmethod
    def validate_url(cls, url: str, allowed_schemes: List[str] = None) -> str:
        """Валідація URL"""
        if allowed_schemes is None:
            allowed_schemes = ['http', 'https']

        try:
            parsed = urlparse(url)

            if parsed.scheme not in allowed_schemes:
                raise ValidationError(
                    f"URL scheme must be one of: {', '.join(allowed_schemes)}",
                    field="url"
                )

            # Перевірка на локальні адреси
            if parsed.hostname:
                try:
                    ip = ipaddress.ip_address(parsed.hostname)
                    if ip.is_private or ip.is_loopback:
                        raise ValidationError("Local URLs are not allowed", field="url")
                except ValueError:
                    # Не IP адреса, перевіряємо домен
                    if parsed.hostname in ['localhost', '127.0.0.1', '0.0.0.0']:
                        raise ValidationError("Local URLs are not allowed", field="url")

            return url
        except Exception as e:
            raise ValidationError(f"Invalid URL: {str(e)}", field="url")

    @classmethod
    def validate_ip_address(cls, ip: str, allow_private: bool = False) -> str:
        """Валідація IP адреси"""
        try:
            ip_obj = ipaddress.ip_address(ip)

            if not allow_private and (ip_obj.is_private or ip_obj.is_loopback):
                raise ValidationError("Private IP addresses are not allowed", field="ip_address")

            return str(ip_obj)
        except ValueError:
            raise ValidationError("Invalid IP address", field="ip_address")

    @classmethod
    def validate_file_upload(cls, filename: str, content_type: str,
                           file_size: int) -> Dict[str, Any]:
        """Валідація завантаженого файлу"""
        # Перевірка розміру
        if file_size > MAX_FILE_SIZE:
            raise ValidationError(
                f"File too large. Maximum size is {MAX_FILE_SIZE / 1024 / 1024}MB",
                field="file"
            )

        # Санітизація імені файлу
        safe_filename = cls.sanitize_string(filename, allow_html=False)
        safe_filename = re.sub(r'[^\w\s.-]', '_', safe_filename)

        # Перевірка розширення
        extension = safe_filename.lower().rsplit('.', 1)[-1] if '.' in safe_filename else ''
        if f'.{extension}' not in ALLOWED_FILE_EXTENSIONS:
            raise ValidationError(
                f"File type not allowed. Allowed types: {', '.join(ALLOWED_FILE_EXTENSIONS)}",
                field="file"
            )

        # Перевірка MIME типу
        if content_type not in ALLOWED_MIME_TYPES:
            raise ValidationError(
                f"Content type not allowed. Allowed types: {', '.join(ALLOWED_MIME_TYPES)}",
                field="file"
            )

        return {
            'filename': safe_filename,
            'extension': extension,
            'content_type': content_type,
            'size': file_size
        }

    @classmethod
    def validate_json(cls, value: Union[str, Dict]) -> Dict:
        """Валідація JSON"""
        if isinstance(value, str):
            try:
                value = json.loads(value)
            except json.JSONDecodeError as e:
                raise ValidationError(f"Invalid JSON: {str(e)}", field="json")

        if not isinstance(value, dict):
            raise ValidationError("JSON must be an object", field="json")

        # Перевірка глибини
        def check_depth(obj, depth=0):
            if depth > MAX_DICT_DEPTH:
                raise ValidationError(f"JSON depth exceeds maximum of {MAX_DICT_DEPTH}")

            if isinstance(obj, dict):
                for v in obj.values():
                    check_depth(v, depth + 1)
            elif isinstance(obj, list):
                for item in obj:
                    check_depth(item, depth + 1)

        check_depth(value)
        return value

    @classmethod
    def validate_list(cls, value: List[Any], item_validator: Callable = None,
                     max_length: int = MAX_LIST_LENGTH) -> List[Any]:
        """Валідація списку"""
        if not isinstance(value, list):
            raise ValidationError("Value must be a list", field="list")

        if len(value) > max_length:
            raise ValidationError(f"List too long. Maximum {max_length} items allowed", field="list")

        if item_validator:
            validated_items = []
            for i, item in enumerate(value):
                try:
                    validated_items.append(item_validator(item))
                except ValidationError as e:
                    e.field = f"list[{i}]"
                    raise

            return validated_items

        return value

    @classmethod
    def validate_pagination(cls, page: int = 1, per_page: int = 20) -> Dict[str, int]:
        """Валідація параметрів пагінації"""
        if page < 1:
            raise ValidationError("Page must be >= 1", field="page")

        if per_page < 1 or per_page > 100:
            raise ValidationError("Per page must be between 1 and 100", field="per_page")

        return {
            'page': page,
            'per_page': per_page,
            'offset': (page - 1) * per_page,
            'limit': per_page
        }


# Pydantic моделі для типових випадків

def validate_safe_string_field(v: str) -> str:
    """Валідатор для безпечних строк"""
    if not isinstance(v, str):
        raise TypeError('string required')
    return InputValidator.validate_safe_string(v)

# Анотований тип для безпечних строк
SafeStringField = Annotated[str, AfterValidator(validate_safe_string_field)]


class PaginationParams(BaseModel):
    """Параметри пагінації"""
    page: conint(ge=1) = 1
    per_page: conint(ge=1, le=100) = 20

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.per_page

    @property
    def limit(self) -> int:
        return self.per_page


class SearchParams(BaseModel):
    """Параметри пошуку"""
    model_config = ConfigDict(str_strip_whitespace=True)

    query: SafeStringField = Field(..., min_length=1, max_length=200)
    filters: Optional[Dict[str, Any]] = None
    sort_by: Optional[str] = None
    sort_order: Optional[str] = Field(None, pattern='^(asc|desc)$')

    @field_validator('filters')
    @classmethod
    def validate_filters(cls, v):
        if v:
            return InputValidator.validate_json(v)
        return v

    @field_validator('sort_by')
    @classmethod
    def validate_sort_by(cls, v):
        if v:
            # Дозволяємо тільки безпечні назви полів
            if not re.match(r'^[a-zA-Z_][a-zA-Z0-9_]*$', v):
                raise ValueError('Invalid sort field name')
        return v


class FileUploadParams(BaseModel):
    """Параметри завантаження файлу"""
    model_config = ConfigDict(str_strip_whitespace=True)

    filename: str
    content_type: str
    size: int

    @model_validator(mode='after')
    def validate_upload(self):
        result = InputValidator.validate_file_upload(
            self.filename,
            self.content_type,
            self.size
        )
        # Оновлюємо значення з результату валідації
        for key, value in result.items():
            setattr(self, key, value)
        return self


# Декоратор для валідації
def validate_input(model_class: BaseModel):
    """Декоратор для автоматичної валідації вхідних даних"""
    def decorator(func):
        async def wrapper(*args, **kwargs):
            # Знаходимо дані для валідації
            data = kwargs.get('data') or (args[0] if args else {})

            try:
                # Валідуємо через Pydantic
                validated = model_class(**data)
                kwargs['data'] = validated.dict()
            except ValidationError as e:
                logger.warning("Input validation failed", errors=e.errors())
                raise ValidationError(f"Validation failed: {e}")

            return await func(*args, **kwargs)
        return wrapper
    return decorator
