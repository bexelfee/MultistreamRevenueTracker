"""
Developer-application credentials bundled at release build time.

Release builds run scripts/generate_bundled_credentials.py to populate these values.
Empty strings mean "not bundled" — local development may use environment variables
(see README developer section).
"""

from __future__ import annotations

from typing import Any

# Twitch Developer Application
TWITCH_CLIENT_ID: str = ""
TWITCH_CLIENT_SECRET: str = ""

# Patreon Developer Application
PATREON_CLIENT_ID: str = ""
PATREON_CLIENT_SECRET: str = ""

# Google Cloud OAuth client (full client_secrets.json structure, e.g. {"installed": {...}})
YOUTUBE_OAUTH_CLIENT_CONFIG: dict[str, Any] | None = None


def has_bundled_developer_credentials() -> bool:
    """True when a release build populated at least one bundled credential."""
    if TWITCH_CLIENT_ID and TWITCH_CLIENT_SECRET:
        return True
    if PATREON_CLIENT_ID and PATREON_CLIENT_SECRET:
        return True
    return bool(YOUTUBE_OAUTH_CLIENT_CONFIG)
