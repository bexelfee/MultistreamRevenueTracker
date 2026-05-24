"""Tests for log secret scrubbing."""
from __future__ import annotations

import logging

from multistream_revenue_tracker.log_scrubbing import (
    REDACTED,
    SecretScrubbingFilter,
    get_registry,
    scrub_text,
)


def test_scrub_literal_secret():
    registry = get_registry()
    registry.register("super_secret_token_value_12345")
    assert scrub_text("failed with super_secret_token_value_12345") == f"failed with {REDACTED}"


def test_scrub_longest_literal_first():
    registry = get_registry()
    registry.register("abc")
    registry.register("abcdefgh")
    assert scrub_text("prefix abcdefgh suffix") == f"prefix {REDACTED} suffix"


def test_scrub_bearer_and_paths():
    text = "Bearer ya29.super-long-token-value-here C:\\Users\\x\\secrets.json"
    out = scrub_text(text)
    assert "ya29" not in out
    assert "Bearer" in out
    assert REDACTED in out
    assert "C:\\Users" not in out
    assert "[path]" in out


def test_filter_scrubs_log_record():
    registry = get_registry()
    registry.register("my_streamlabs_socket_token_xyz")
    filt = SecretScrubbingFilter()
    record = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname="",
        lineno=0,
        msg="connected token=%s",
        args=("my_streamlabs_socket_token_xyz",),
        exc_info=None,
    )
    assert filt.filter(record) is True
    assert record.getMessage() == f"connected token={REDACTED}"
    assert record.args == ()


def test_short_channel_name_scrubbed():
    registry = get_registry()
    registry.register("xqc", min_length=3)
    assert scrub_text("login=xqc done") == f"login={REDACTED} done"
