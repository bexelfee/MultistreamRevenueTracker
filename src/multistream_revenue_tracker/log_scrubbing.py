"""Redact secrets from log lines before they reach the UI or session log files."""
from __future__ import annotations

import json
import logging
import re
import threading
from pathlib import Path
from typing import Any

REDACTED = "[REDACTED]"
MIN_SECRET_LENGTH = 8
MIN_CHANNEL_NAME_LENGTH = 3

_PATH_WIN_RE = re.compile(r"[A-Za-z]:\\[^\s]+")
_PATH_UNIX_RE = re.compile(r"/[\w./-]+\.(?:py|json|txt|log|db)\b", re.IGNORECASE)
_TOKEN_RE = re.compile(r"\b(?:sk|pk)_(?:live|test)?_?[A-Za-z0-9]{8,}\b", re.IGNORECASE)
# Google OAuth access tokens (ya29.*) and refresh tokens (1//*) — visible in
# google-auth library logs and exception traces.
_GOOGLE_TOKEN_RE = re.compile(r"\bya29\.[A-Za-z0-9_\-]{20,}\b")
_GOOGLE_REFRESH_RE = re.compile(r"\b1//0[A-Za-z0-9_\-]{20,}\b")
_BEARER_RE = re.compile(r"\bBearer\s+[A-Za-z0-9._\-]+", re.IGNORECASE)
_CLIENT_SECRET_KV_RE = re.compile(
    r"(client_secret|access_token|refresh_token|socket_api_token)\s*[=:]\s*['\"]?"
    r"[^\s'\",}]+",
    re.IGNORECASE,
)

_scrub_filter: logging.Filter | None = None


class SecretRegistry:
    """Thread-safe set of literal substrings to replace in log output."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._secrets: set[str] = set()

    def register(self, value: str | None, *, min_length: int = MIN_SECRET_LENGTH) -> None:
        if value is None:
            return
        text = str(value).strip()
        if len(text) < min_length:
            return
        with self._lock:
            self._secrets.add(text)

    def register_many(self, values: list[str | None], *, min_length: int = MIN_SECRET_LENGTH) -> None:
        for value in values:
            self.register(value, min_length=min_length)

    def literals_sorted(self) -> list[str]:
        with self._lock:
            return sorted(self._secrets, key=len, reverse=True)


_registry = SecretRegistry()


def get_registry() -> SecretRegistry:
    return _registry


def scrub_text(text: str) -> str:
    if not text:
        return text
    out = text
    for literal in _registry.literals_sorted():
        out = out.replace(literal, REDACTED)
    out = _PATH_WIN_RE.sub("[path]", out)
    out = _PATH_UNIX_RE.sub("[file]", out)
    out = _TOKEN_RE.sub(REDACTED, out)
    out = _GOOGLE_TOKEN_RE.sub(REDACTED, out)
    out = _GOOGLE_REFRESH_RE.sub(REDACTED, out)
    out = _BEARER_RE.sub(f"Bearer {REDACTED}", out)
    out = _CLIENT_SECRET_KV_RE.sub(
        lambda m: f"{m.group(1)}={REDACTED}",
        out,
    )
    return out


class SecretScrubbingFilter(logging.Filter):
    """Scrub formatted log messages before handlers write them."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:
            return True
        record.msg = scrub_text(message)
        record.args = ()
        return True


def _get_scrub_filter() -> SecretScrubbingFilter:
    global _scrub_filter
    if _scrub_filter is None:
        _scrub_filter = SecretScrubbingFilter()
    return _scrub_filter


def attach_scrubber_to_handler(handler: logging.Handler) -> None:
    handler.addFilter(_get_scrub_filter())


def install_log_scrubbing_filter() -> None:
    """Attach scrubbing to the root logger and all handlers already registered."""
    filt = _get_scrub_filter()
    root = logging.getLogger()
    if filt not in root.filters:
        root.addFilter(filt)
    for handler in root.handlers:
        if filt not in handler.filters:
            handler.addFilter(filt)


def _youtube_oauth_secrets(oauth_config: dict[str, Any] | None) -> list[str | None]:
    if not oauth_config:
        return []
    found: list[str | None] = []
    for section in oauth_config.values():
        if not isinstance(section, dict):
            continue
        found.append(section.get("client_id"))
        found.append(section.get("client_secret"))
    return found


def register_from_app_config(app_cfg: Any) -> None:
    """Register static credentials and config fields for the current session.

    Safe to call on every config reload — registers are idempotent (a set).
    Callers MUST invoke this after any in-place token swap so a newly-pasted
    Streamlabs / Twitch / channel-name value never leaks unscrubbed into the
    UI log stream before the next process start.
    """
    from .secrets import (
        resolve_patreon_credentials,
        resolve_twitch_credentials,
        resolve_youtube_oauth_client_config,
    )

    twitch_id, twitch_secret = resolve_twitch_credentials()
    patreon_id, patreon_secret = resolve_patreon_credentials()

    _registry.register_many([
        twitch_id,
        twitch_secret,
        patreon_id,
        patreon_secret,
        app_cfg.twitch.client_id,
        app_cfg.twitch.client_secret,
        app_cfg.patreon.client_id,
        app_cfg.patreon.client_secret,
        app_cfg.streamlabs.socket_api_token,
    ])
    _registry.register(app_cfg.twitch.channel_name, min_length=MIN_CHANNEL_NAME_LENGTH)
    _registry.register_many(_youtube_oauth_secrets(app_cfg.youtube.oauth_client_config))
    _registry.register_many(_youtube_oauth_secrets(resolve_youtube_oauth_client_config()))


def register_patreon_token(token: Any | None) -> None:
    if token is None:
        return
    _registry.register(getattr(token, "access_token", None))
    refresh = getattr(token, "refresh_token", None)
    if refresh:
        _registry.register(refresh)


def register_youtube_credentials(credentials: Any | None) -> None:
    if credentials is None:
        return
    _registry.register(getattr(credentials, "token", None))
    refresh = getattr(credentials, "refresh_token", None)
    if refresh:
        _registry.register(refresh)
    _registry.register(getattr(credentials, "client_secret", None))
    _registry.register(getattr(credentials, "client_id", None))


def register_token_file(path: Path) -> None:
    """Register token fields from patreon_token.json or yt_token.json if present."""
    if not path.is_file():
        return
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    if not isinstance(raw, dict):
        return
    for key in ("access_token", "refresh_token", "token", "client_secret", "client_id"):
        value = raw.get(key)
        if isinstance(value, str) and value.strip():
            _registry.register(value.strip())
