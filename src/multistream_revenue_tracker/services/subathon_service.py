"""Subathon countdown timer: server-authoritative tick + points-to-seconds from new events."""

from __future__ import annotations

import asyncio
import json
import logging
import math
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable

from ..goals.point_rules import PointRulesStore
from ..goals.points_calculator import points_for_event_fractional
from ..revenue.revenue_db import RevenueDatabase, StoredRevenueEvent

LOGGER = logging.getLogger(__name__)

DEFAULT_SUBATHON_POINTS = 10
DEFAULT_SUBATHON_SECONDS = 60


@dataclass
class SubathonState:
    remaining_seconds: int = 0
    running: bool = False
    last_processed_event_id: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "remaining_seconds": self.remaining_seconds,
            "running": self.running,
            "last_processed_event_id": self.last_processed_event_id,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SubathonState:
        return cls(
            remaining_seconds=max(0, int(data.get("remaining_seconds", 0))),
            running=bool(data.get("running", False)),
            last_processed_event_id=max(0, int(data.get("last_processed_event_id", 0))),
        )


def format_display(total_seconds: int) -> str:
    total = max(0, int(total_seconds))
    hours, rem = divmod(total, 3600)
    minutes, seconds = divmod(rem, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


def format_display_days(total_seconds: int) -> str:
    """Days plus remainder as HH:MM:SS (hours are within the current day)."""
    total = max(0, int(total_seconds))
    days, rem = divmod(total, 86400)
    hours, rem2 = divmod(rem, 3600)
    minutes, seconds = divmod(rem2, 60)
    return f"{days} Days {hours:02d}:{minutes:02d}:{seconds:02d}"


def seconds_to_add(points: float, *, subathon_points: int, subathon_seconds: int) -> int:
    if points <= 0 or subathon_points < 1 or subathon_seconds < 1:
        return 0
    return int(math.floor(points * subathon_seconds / subathon_points))


def parse_time_parts(
    *,
    hours: int | None = None,
    minutes: int | None = None,
    seconds: int | None = None,
    total_seconds: int | None = None,
) -> int:
    if total_seconds is not None:
        return max(0, int(total_seconds))
    h = max(0, int(hours or 0))
    m = max(0, min(59, int(minutes or 0)))
    s = max(0, min(59, int(seconds or 0)))
    return h * 3600 + m * 60 + s


class SubathonService:
    def __init__(
        self,
        state_path: Path,
        database: RevenueDatabase,
        *,
        subathon_points: int = DEFAULT_SUBATHON_POINTS,
        subathon_seconds: int = DEFAULT_SUBATHON_SECONDS,
        show_days: bool = False,
    ) -> None:
        self._state_path = state_path
        self._database = database
        self._lock = threading.Lock()
        self._listeners: list[Callable[[], Awaitable[None]]] = []
        self._subathon_points = max(1, int(subathon_points))
        self._subathon_seconds = max(1, int(subathon_seconds))
        self._show_days = bool(show_days)
        self._state = self._load_state()

    @property
    def subathon_points(self) -> int:
        return self._subathon_points

    @property
    def subathon_seconds(self) -> int:
        return self._subathon_seconds

    def set_conversion(self, points: int, seconds: int) -> None:
        self._subathon_points = max(1, int(points))
        self._subathon_seconds = max(1, int(seconds))

    def set_show_days(self, show_days: bool) -> None:
        self._show_days = bool(show_days)

    def _format_remaining(self, remaining: int) -> str:
        if self._show_days:
            return format_display_days(remaining)
        return format_display(remaining)

    def add_listener(self, callback: Callable[[], Awaitable[None]]) -> None:
        self._listeners.append(callback)

    async def notify_changed(self) -> None:
        for listener in list(self._listeners):
            try:
                await listener()
            except Exception:
                LOGGER.exception("subathon listener failed")

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            remaining = self._state.remaining_seconds
            running = self._state.running
            points = self._subathon_points
            seconds = self._subathon_seconds
        return {
            "remaining_seconds": remaining,
            "running": running,
            "display": self._format_remaining(remaining),
            "show_days": self._show_days,
            "points": points,
            "seconds": seconds,
        }

    def set_remaining_seconds(self, seconds: int) -> None:
        with self._lock:
            self._state.remaining_seconds = max(0, int(seconds))
            self._save_state_locked()

    def set_running(self, running: bool) -> None:
        with self._lock:
            self._state.running = bool(running)
            self._save_state_locked()

    def reset_watermark(self) -> None:
        max_id = self._database.max_event_id()
        with self._lock:
            self._state.last_processed_event_id = max_id
            self._save_state_locked()

    def on_revenue_event(self, stored: StoredRevenueEvent, rules_store: PointRulesStore) -> bool:
        """Add time for a newly stored event. Returns True if state changed."""
        if stored.id is None or stored.id <= 0:
            return False
        with self._lock:
            if stored.id <= self._state.last_processed_event_id:
                return False
            points = points_for_event_fractional(stored, rules_store)
            added = seconds_to_add(
                points,
                subathon_points=self._subathon_points,
                subathon_seconds=self._subathon_seconds,
            )
            self._state.last_processed_event_id = stored.id
            if added > 0:
                self._state.remaining_seconds += added
            self._save_state_locked()
            return True

    def tick_once(self) -> bool:
        """Decrement by one second when running. Returns True if state changed."""
        with self._lock:
            if not self._state.running or self._state.remaining_seconds <= 0:
                return False
            self._state.remaining_seconds -= 1
            self._save_state_locked()
            return True

    async def tick_loop(self, shutdown_event: asyncio.Event) -> None:
        LOGGER.info("subathon tick loop started")
        while not shutdown_event.is_set():
            await asyncio.sleep(1)
            if shutdown_event.is_set():
                break
            changed = await asyncio.to_thread(self.tick_once)
            if changed:
                await self.notify_changed()
        LOGGER.info("subathon tick loop finished")

    def _load_state(self) -> SubathonState:
        if not self._state_path.is_file():
            return SubathonState()
        try:
            raw = json.loads(self._state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            LOGGER.warning("could not load subathon state: %s", exc)
            return SubathonState()
        if not isinstance(raw, dict):
            return SubathonState()
        return SubathonState.from_dict(raw)

    def _save_state_locked(self) -> None:
        self._state_path.parent.mkdir(parents=True, exist_ok=True)
        temp = self._state_path.with_suffix(self._state_path.suffix + ".tmp")
        temp.write_text(json.dumps(self._state.to_dict(), indent=2) + "\n", encoding="utf-8")
        temp.replace(self._state_path)
