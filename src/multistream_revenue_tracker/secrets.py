from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from . import bundled_credentials


def _env(name: str) -> str:
    return os.environ.get(name, "").strip()


def _bundled_twitch() -> tuple[str, str]:
    return bundled_credentials.TWITCH_CLIENT_ID.strip(), bundled_credentials.TWITCH_CLIENT_SECRET.strip()


def _bundled_patreon() -> tuple[str, str]:
    return bundled_credentials.PATREON_CLIENT_ID.strip(), bundled_credentials.PATREON_CLIENT_SECRET.strip()


def resolve_twitch_credentials() -> tuple[str, str]:
    """Twitch Developer Application credentials (release bundle or environment variables)."""
    client_id, client_secret = _bundled_twitch()
    if not client_id:
        client_id = _env("TWITCH_CLIENT_ID")
    if not client_secret:
        client_secret = _env("TWITCH_CLIENT_SECRET")
    return client_id, client_secret


def resolve_patreon_credentials(raw_config: dict[str, Any] | None = None) -> tuple[str, str]:
    """Patreon credentials: config.json overrides, then env, then release bundle."""
    client_id, client_secret = _bundled_patreon()
    if raw_config:
        pa = raw_config.get("patreon")
        if isinstance(pa, dict):
            cfg_id = str(pa.get("client_id") or "").strip()
            cfg_secret = str(pa.get("client_secret") or "").strip()
            if cfg_id:
                client_id = cfg_id
            if cfg_secret:
                client_secret = cfg_secret
    if not client_id:
        client_id = _env("PATREON_CLIENT_ID")
    if not client_secret:
        client_secret = _env("PATREON_CLIENT_SECRET") or _env("PATREON_SECRET")
    return client_id, client_secret


def resolve_streamlabs_socket_token(raw_config: dict[str, Any]) -> str:
    """Per-creator Streamlabs Socket API token (environment variable or config.json)."""
    token = _env("STREAMLABS_SOCKET_TOKEN")
    if not token:
        sl = raw_config.get("streamlabs")
        if isinstance(sl, dict):
            token = str(sl.get("socket_api_token") or "").strip()
    return token


def resolve_youtube_oauth_client_config() -> dict[str, Any] | None:
    """
    Google OAuth client config (release bundle, YOUTUBE_OAUTH_CLIENT_JSON, or
    JSON file at YOUTUBE_CLIENT_SECRETS_PATH).
    """
    cfg = bundled_credentials.YOUTUBE_OAUTH_CLIENT_CONFIG
    if isinstance(cfg, dict) and cfg:
        return cfg

    json_inline = _env("YOUTUBE_OAUTH_CLIENT_JSON")
    if json_inline:
        data = json.loads(json_inline)
        return data if isinstance(data, dict) else None

    path_str = _env("YOUTUBE_CLIENT_SECRETS_PATH")
    if path_str:
        path = Path(path_str)
        if not path.is_file():
            raise FileNotFoundError(f"YOUTUBE_CLIENT_SECRETS_PATH not found: {path}")
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None

    return None


def developer_credentials_configured() -> bool:
    """True when Twitch developer credentials are available (bundle or environment)."""
    client_id, client_secret = resolve_twitch_credentials()
    return bool(client_id and client_secret)
