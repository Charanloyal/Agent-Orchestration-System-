import json
import logging

from app.observability.context import reset_request_id, set_request_id
from app.observability.logging import JsonFormatter, redact


def test_redacts_common_secret_shapes() -> None:
    samples = [
        "Authorization: Bearer abcdefghijklmnop.qrstuvwxyz",
        "api_key=sk-1234567890abcdef",
        "postgresql://postgres:hunter2pass@127.0.0.1:5432/aos",
        "token: 'tvly-abcdef1234567890'",
        "password=correct-horse-battery",
    ]
    for sample in samples:
        out = redact(sample)
        assert "[REDACTED]" in out, sample
        for secret in (
            "abcdefghijklmnop",
            "1234567890abcdef",
            "hunter2pass",
            "tvly-abcdef",
            "correct-horse",
        ):
            assert secret not in out


def test_json_formatter_includes_context_and_redacts_extras() -> None:
    token = set_request_id("req-12345678")
    try:
        record = logging.LogRecord(
            "aos.test",
            logging.INFO,
            __file__,
            1,
            "connecting to %s",
            ("postgresql://u:s3cretpw@h/db",),
            None,
        )
        record.api_key = "sk-abcdefghijklmnop"
        record.step = "planner"
        payload = json.loads(JsonFormatter().format(record))
    finally:
        reset_request_id(token)
    assert payload["request_id"] == "req-12345678"
    assert payload["step"] == "planner"
    assert payload["api_key"] == "[REDACTED]"
    assert "s3cretpw" not in payload["msg"]
