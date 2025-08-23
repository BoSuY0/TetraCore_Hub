import structlog
import pytest


def test_redact_and_rate_limit_processors(monkeypatch):
    from core.logging_utils import (
        RedactSecretsProcessor,
        RateLimiterProcessor,
        SampleInfoProcessor,
    )

    rp = RedactSecretsProcessor()
    event = {
        "event": "test",
        "Authorization": "Bearer abc.def.ghi",
        "password": "secret",
        "nested": {"Token": "tok"},
        "task_data": {"a": 1},
    }
    out = rp(None, "info", dict(event))
    assert out["Authorization"] == "Bearer <redacted>"
    assert out["password"] == "<redacted>"
    assert out["nested"]["Token"] == "<redacted>"
    assert out["task_data"] == "<hidden>"
    assert out["task_data_preview"] == ["a"]

    # Rate limiter: allow first, drop immediate second
    rl = RateLimiterProcessor(min_interval=0.5)
    assert rl(None, "info", {"event": "same"}) == {"event": "same"}
    with pytest.raises(structlog.DropEvent):
        rl(None, "info", {"event": "same"})

    # SampleInfoProcessor respects rate env
    monkeypatch.setenv("LOG_INFO_SAMPLE_RATE", "0.0")
    sp = SampleInfoProcessor()
    with pytest.raises(structlog.DropEvent):
        sp(None, "info", {"event": "x"})
