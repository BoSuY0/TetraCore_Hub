import pytest


def test_validate_safe_string_and_patterns():
    from core.input_validator import InputValidator

    safe = "Hello, world!"
    assert InputValidator.validate_safe_string(safe)
    assert InputValidator.validate_pattern("user_123", "username") is True
    assert InputValidator.validate_pattern("bad space", "username") is False


def test_email_url_ip_validation():
    from core.input_validator import InputValidator, ValidationError

    assert InputValidator.validate_email("user@example.com") == "user@example.com"
    with pytest.raises(ValidationError):
        InputValidator.validate_email("bad@@example")

    assert InputValidator.validate_url("https://example.com") == "https://example.com"
    with pytest.raises(ValidationError):
        InputValidator.validate_url("javascript:alert(1)")

    assert (
        InputValidator.validate_ip_address("8.8.8.8", allow_private=True) == "8.8.8.8"
    )
    with pytest.raises(ValidationError):
        InputValidator.validate_ip_address("999.1.1.1")


def test_file_upload_validation():
    from core.input_validator import InputValidator, ValidationError

    ok = InputValidator.validate_file_upload(
        filename="file.pdf", content_type="application/pdf", file_size=1024
    )
    assert ok["filename"].endswith("file.pdf")

    with pytest.raises(ValidationError):
        InputValidator.validate_file_upload(
            filename="file.exe", content_type="application/x-msdownload", file_size=10
        )
