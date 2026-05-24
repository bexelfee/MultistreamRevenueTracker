from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

LOGGER = logging.getLogger(__name__)

MAX_MEMBERSHIP_LEVELS = 6


class YoutubeMembershipLevelsError(Exception):
    """Non-fatal failure loading membership levels (OAuth succeeded)."""


@dataclass(frozen=True)
class YoutubeLevelInfo:
    id: str
    name: str


def parse_membership_levels_response(payload: dict[str, Any]) -> list[YoutubeLevelInfo]:
    """Parse a membershipsLevels.list API response."""
    items = payload.get("items") or []
    levels: list[YoutubeLevelInfo] = []
    for item in items[:MAX_MEMBERSHIP_LEVELS]:
        if not isinstance(item, dict):
            continue
        level_id = str(item.get("id") or "").strip()
        snippet = item.get("snippet") if isinstance(item.get("snippet"), dict) else {}
        details = snippet.get("levelDetails") if isinstance(snippet.get("levelDetails"), dict) else {}
        name = str(
            details.get("displayName")
            or details.get("display_name")
            or snippet.get("displayName")
            or ""
        ).strip()
        if level_id and name:
            levels.append(YoutubeLevelInfo(id=level_id, name=name))
    return sorted(levels, key=lambda level: level.name.lower())


def fetch_membership_levels(credentials) -> list[YoutubeLevelInfo]:
    """List channel membership levels for the authenticated creator."""
    try:
        from googleapiclient.discovery import build
        from googleapiclient.errors import HttpError
    except ImportError as exc:
        raise RuntimeError(
            "Missing Google API client dependency. Install requirements.txt before running YouTube monitor."
        ) from exc

    service = build("youtube", "v3", credentials=credentials)
    try:
        response = service.membershipsLevels().list(part="id,snippet").execute()
    except HttpError as exc:
        status = getattr(exc, "status_code", None) or getattr(getattr(exc, "resp", None), "status", None)
        LOGGER.warning("membershipsLevels.list failed (status=%s): %s", status, exc)
        raise YoutubeMembershipLevelsError(
            "Could not load YouTube membership levels. Reconnect YouTube after enabling channel memberships."
        ) from exc
    levels = parse_membership_levels_response(response)
    if not levels:
        LOGGER.info("membershipsLevels.list returned no levels")
    else:
        LOGGER.info("loaded %s YouTube membership level(s)", len(levels))
    return levels


def resolve_level_id(levels: list[YoutubeLevelInfo], member_level_name: str | None) -> str | None:
    """Map live-chat level display name to stable level id (case-insensitive)."""
    name = str(member_level_name or "").strip()
    if not name:
        return None
    lowered = name.casefold()
    for level in levels:
        if level.name.casefold() == lowered:
            return level.id
    return None
