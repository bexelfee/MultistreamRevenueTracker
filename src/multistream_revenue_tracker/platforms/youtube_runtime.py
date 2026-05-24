from __future__ import annotations

import logging
from typing import Any

from .youtube_catalog import (
    YoutubeLevelInfo,
    YoutubeMembershipLevelsError,
    fetch_membership_levels,
    resolve_level_id,
)

LOGGER = logging.getLogger(__name__)


class YoutubeRuntime:
    def __init__(self) -> None:
        self.levels: list[YoutubeLevelInfo] = []
        self.load_error: str | None = None
        self._warned_unknown_levels: set[str] = set()

    @property
    def enabled(self) -> bool:
        return self.load_error is None and bool(self.levels)

    def load_levels(self, credentials) -> None:
        self._warned_unknown_levels.clear()
        try:
            self.levels = fetch_membership_levels(credentials)
            if not self.levels:
                self.load_error = (
                    "No YouTube membership levels found. Enable channel memberships in YouTube Studio."
                )
            else:
                self.load_error = None
        except YoutubeMembershipLevelsError as exc:
            self.levels = []
            self.load_error = str(exc)
            LOGGER.warning("YouTube membership levels: %s", exc)
        except RuntimeError:
            raise
        except Exception as exc:
            self.levels = []
            self.load_error = f"Failed to load YouTube membership levels: {exc}"
            LOGGER.exception("YouTube membership levels load failed")

    def resolve_level_id(self, member_level_name: str | None) -> str | None:
        level_id = resolve_level_id(self.levels, member_level_name)
        name = str(member_level_name or "").strip()
        if name and level_id is None and name not in self._warned_unknown_levels:
            self._warned_unknown_levels.add(name)
            known = [level.name for level in self.levels]
            LOGGER.warning(
                "YouTube membership level name %r did not match any loaded level; "
                "event scores 0 points until rules match. known_levels=%s",
                name,
                known,
            )
        return level_id

    def levels_for_ui(self) -> list[dict[str, str]]:
        return [{"level_id": level.id, "name": level.name} for level in self.levels]

    def for_ui(self, point_rules: dict[str, dict], *, feature_enabled: bool = True) -> dict[str, Any]:
        del point_rules
        return {
            "feature_enabled": feature_enabled,
            "enabled": feature_enabled and self.enabled,
            "load_error": self.load_error,
            "levels": self.levels_for_ui(),
        }
