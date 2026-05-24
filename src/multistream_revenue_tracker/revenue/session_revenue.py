from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from .events import StreamEvent
from .revenue_db import StoredRevenueEvent
from .revenue_validity import effective_event_type_value, is_scoring_valid, status_label

LOGGER = logging.getLogger(__name__)

_EVENT_TYPE_LABELS: dict[str, str] = {
    "twitch_bits": "Bits",
    "twitch_subscription": "Sub",
    "twitch_subscription_gift": "Sub gift",
    "twitch_resubscription": "Resub",
    "twitch_resubscription_suppressed": "Resub",
    "revenue_invalid": "Invalid",
    "youtube_super_chat": "Super Chat",
    "youtube_super_sticker": "Super Sticker",
    "youtube_membership": "Membership",
    "youtube_membership_gift": "Membership gift",
    "youtube_gift": "Gift",
    "patreon_pledge_create": "Pledge",
    "streamlabs_donation": "Donation",
}


def _type_label(event_type_value: str) -> str:
    return _EVENT_TYPE_LABELS.get(event_type_value, event_type_value)


def _format_amount_from_stored(event: StoredRevenueEvent) -> str:
    amount = event.amount_display
    if not amount and event.amount_micros is not None:
        value = event.amount_micros / 1_000_000
        amount = f"{value:.2f}"
        if event.currency:
            amount = f"{amount} {event.currency}"
    if not amount and event.quantity is not None:
        if event.tier:
            amount = f"×{event.quantity} (tier {event.tier})"
        else:
            amount = f"×{event.quantity}"
    elif not amount and event.tier:
        amount = f"tier {event.tier}"
    if not amount:
        amount = "—"
    return amount


def row_from_stored(stored: StoredRevenueEvent) -> dict[str, Any]:
    user = stored.gifter_user_name or stored.recipient_user_name
    valid = is_scoring_valid(stored)
    return {
        "id": stored.id,
        "platform": stored.platform.value,
        "type": _type_label(effective_event_type_value(stored)),
        "amount": _format_amount_from_stored(stored),
        "user": user or "—",
        "is_test": stored.is_test,
        "is_valid": valid,
        "status": status_label(stored),
        "can_add": not valid,
        "can_remove": valid,
    }


def simplify_revenue_event(event: StreamEvent) -> dict[str, Any]:
    """Legacy helper for tests; prefer row_from_stored after DB insert."""
    user = event.gifter_user_name or event.recipient_user_name
    amount = event.amount_display
    if not amount and event.amount_micros is not None:
        value = event.amount_micros / 1_000_000
        amount = f"{value:.2f}"
        if event.currency:
            amount = f"{amount} {event.currency}"
    if not amount and event.quantity is not None:
        if event.tier:
            amount = f"×{event.quantity} (tier {event.tier})"
        else:
            amount = f"×{event.quantity}"
    elif not amount and event.tier:
        amount = f"tier {event.tier}"
    if not amount:
        amount = "—"
    type_value = (
        event.raw.get("valid_event_type", event.event_type.value)
        if event.event_type.value == "revenue_invalid"
        else event.event_type.value
    )
    valid = event.event_type.value != "revenue_invalid"
    return {
        "platform": event.platform.value,
        "type": _type_label(type_value),
        "amount": amount,
        "user": user or "—",
        "is_test": event.is_test,
        "is_valid": valid,
        "status": "Valid" if valid else "Duplicate (auto)",
        "can_add": not valid,
        "can_remove": valid,
    }


class SessionRevenueStore:
    """In-memory revenue events for the current process session (UI feed)."""

    def __init__(self, *, max_items: int = 500) -> None:
        self._max_items = max_items
        self._items: list[dict[str, Any]] = []
        self._lock = asyncio.Lock()
        self._on_change: Callable[[], Awaitable[None]] | None = None

    def snapshot(self) -> list[dict[str, Any]]:
        return list(self._items)

    async def append(self, event: StreamEvent) -> dict[str, Any] | None:
        if not event.is_revenue:
            return None
        row = simplify_revenue_event(event)
        async with self._lock:
            self._items.append(row)
            if len(self._items) > self._max_items:
                self._items = self._items[-self._max_items :]
        await self._notify()
        return row

    async def append_stored(self, stored: StoredRevenueEvent) -> dict[str, Any]:
        row = row_from_stored(stored)
        async with self._lock:
            self._items.append(row)
            if len(self._items) > self._max_items:
                self._items = self._items[-self._max_items :]
        await self._notify()
        return row

    async def update_by_id(self, event_id: int, stored: StoredRevenueEvent) -> bool:
        row = row_from_stored(stored)
        async with self._lock:
            for index, item in enumerate(self._items):
                if item.get("id") == event_id:
                    self._items[index] = row
                    await self._notify()
                    return True
        return False

    async def remove_test_events(self) -> int:
        async with self._lock:
            before = len(self._items)
            self._items = [row for row in self._items if not row.get("is_test")]
            removed = before - len(self._items)
        if removed:
            await self._notify()
        return removed

    def set_on_change(self, callback: Callable[[], Awaitable[None]] | None) -> None:
        self._on_change = callback

    async def _notify(self) -> None:
        if self._on_change is None:
            return
        try:
            await self._on_change()
        except Exception:
            LOGGER.exception("session revenue on_change callback failed")
