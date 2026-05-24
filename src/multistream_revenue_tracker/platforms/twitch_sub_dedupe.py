from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

LOGGER = logging.getLogger(__name__)

DEFAULT_TWITCH_SUB_RESUB_DEDUPE_SECONDS = 300


class RecentSubTracker:
    """Tracks recent channel.subscribe events to detect duplicate Twitch resub pairs."""

    def __init__(self, window_seconds: int) -> None:
        self._window = max(0, int(window_seconds))
        self._recent: dict[str, datetime] = {}

    @property
    def enabled(self) -> bool:
        return self._window > 0

    @property
    def window_seconds(self) -> int:
        return self._window

    def record_subscribe(self, user_id: str | None, occurred_at: datetime) -> None:
        if not self.enabled or not user_id:
            return
        self._recent[user_id] = _as_utc(occurred_at)
        self._prune(occurred_at)

    def should_suppress_resub(
        self,
        user_id: str | None,
        occurred_at: datetime,
        *,
        cumulative_months: int | None = None,
    ) -> bool:
        if not self.enabled or not user_id:
            return False
        self._prune(occurred_at)
        recorded = self._recent.get(user_id)
        if recorded is None:
            return False
        delta = _as_utc(occurred_at) - recorded
        return 0 <= delta.total_seconds() <= self._window

    def _prune(self, now: datetime) -> None:
        if not self.enabled:
            self._recent.clear()
            return
        cutoff = _as_utc(now) - timedelta(seconds=self._window)
        self._recent = {uid: ts for uid, ts in self._recent.items() if ts >= cutoff}


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
