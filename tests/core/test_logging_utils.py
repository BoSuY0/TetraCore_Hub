import os
import pytest
import structlog

from core.logging_utils import (
    RateLimiterProcessor,
    RedactSecretsProcessor,
    SampleInfoProcessor,
)


def test_redact_secrets_processor_masks_sensitive_keys_and_previews():
    rp = RedactSecretsProcessor()

    event = {
        "event": "test_event",
        "Authorization": "Bearer abc.def.ghi",
        "password": "supersecret",
        "Token": "tok_value",
        "nested": {
            "apiToken": "nested_value",
            "inner": {"Password": "12345"},
            "safe": "ok",
        },
        "task_data": {"a": 1, "b": 2},
        "data": {"x": "y"},
        "list": [{"password": "123"}, "ok"],
    }

    result = rp(None, "info", event)

    # Root-level redactions
    assert result["Authorization"] == "Bearer <redacted>"
    assert result["password"] == "<redacted>"
    assert result["Token"] == "<redacted>"

    # Nested redactions
    assert result["nested"]["apiToken"] == "<redacted>"
    assert result["nested"]["inner"]["Password"] == "<redacted>"
    assert result["nested"]["safe"] == "ok"

    # Previews for task_data/data
    assert result["task_data"] == "<hidden>"
    assert set(result["task_data_preview"]) == {"a", "b"}
    assert result["data"] == "<hidden>"
    assert set(result["data_preview"]) == {"x"}

    # Lists redaction propagation
    assert isinstance(result["list"], list)
    assert result["list"][0]["password"] == "<redacted>"
    assert result["list"][1] == "ok"


def test_rate_limiter_processor_drops_and_allows_after_interval(monkeypatch):
    # Control time progression deterministically
    times = iter(
        [0.0, 0.1, 0.6]
    )  # 2nd call within 0.5s -> drop, 3rd at boundary -> allow

    def fake_time():
        try:
            return next(times)
        except StopIteration:
            return 1.0

    monkeypatch.setattr("core.logging_utils.time.time", fake_time)

    rl = RateLimiterProcessor(min_interval=0.5)

    event = {"event": "repeat_event"}

    # First call allowed
    out1 = rl(None, "info", dict(event))
    assert out1["event"] == "repeat_event"

    # Second call should be dropped
    with pytest.raises(structlog.DropEvent):
        rl(None, "info", dict(event))

    # Third call (after interval) allowed again
    out3 = rl(None, "info", dict(event))
    assert out3["event"] == "repeat_event"


def test_sample_info_processor_sampling(monkeypatch):
    # Case 1: rate = 0.0 -> always drop INFO (deterministic by forcing random()=1.0)
    monkeypatch.setenv("LOG_INFO_SAMPLE_RATE", "0.0")
    s1 = SampleInfoProcessor()
    monkeypatch.setattr(s1.random, "random", lambda: 1.0, raising=False)

    with pytest.raises(structlog.DropEvent):
        s1(None, "info", {"event": "info_log"})

    # Non-INFO is never dropped by this processor
    assert s1(None, "debug", {"event": "debug_log"}) == {"event": "debug_log"}

    # Case 2: rate = 1.0 -> never drop INFO regardless of random value
    monkeypatch.setenv("LOG_INFO_SAMPLE_RATE", "1.0")
    s2 = SampleInfoProcessor()
    monkeypatch.setattr(s2.random, "random", lambda: 1.0, raising=False)

    assert s2(None, "info", {"event": "info_log"}) == {"event": "info_log"}
