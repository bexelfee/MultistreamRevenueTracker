from __future__ import annotations

import uuid
from typing import Any

from .revenue.events import REVENUE_EVENT_TYPES, EventType, Platform, StreamEvent, utc_now

TEST_SOURCE_PREFIX = "test:"

TEST_DEFAULTS: dict[str, dict[str, Any]] = {
    EventType.TWITCH_BITS.value: {"quantity": 100},
    EventType.TWITCH_SUBSCRIPTION.value: {"tier": "1000"},
    EventType.TWITCH_SUBSCRIPTION_GIFT.value: {"tier": "1000", "quantity": 1},
    EventType.TWITCH_RESUBSCRIPTION.value: {"tier": "2000", "message": "test resub"},
    EventType.YOUTUBE_SUPER_CHAT.value: {"amount_micros": 5_000_000, "currency": "EUR", "amount_display": "5.00 EUR"},
    EventType.YOUTUBE_SUPER_STICKER.value: {"amount_micros": 2_000_000, "currency": "USD", "amount_display": "2.00 USD"},
    EventType.YOUTUBE_MEMBERSHIP.value: {},
    EventType.YOUTUBE_MEMBERSHIP_GIFT.value: {"quantity": 1},
    EventType.YOUTUBE_GIFT.value: {"quantity": 10},
    EventType.PATREON_PLEDGE_CREATE.value: {"tier": "1000"},
    EventType.STREAMLABS_DONATION.value: {
        "amount_micros": 5_000_000,
        "currency": "EUR",
        "amount_display": "5.00 EUR",
    },
}


def overrides_from_ui(inputs: dict[str, Any]) -> dict[str, Any]:
    """Map UI test form values to StreamEvent field overrides."""
    overrides: dict[str, Any] = {}
    if not inputs:
        return overrides
    if inputs.get("quantity") not in (None, ""):
        overrides["quantity"] = max(0, int(inputs["quantity"]))
    if inputs.get("tier") not in (None, ""):
        tier = str(inputs["tier"]).strip()
        overrides["tier"] = {"1": "1000", "2": "2000", "3": "3000"}.get(tier, tier)
    if inputs.get("amount") not in (None, ""):
        amount = max(0.0, float(inputs["amount"]))
        currency = str(inputs.get("currency") or "EUR").strip().upper() or "EUR"
        overrides["amount_micros"] = int(round(amount * 1_000_000))
        overrides["currency"] = currency
        overrides["amount_display"] = f"{amount:.2f} {currency}"
    return overrides


def build_test_stream_event(event_type_name: str, overrides: dict[str, Any] | None = None) -> StreamEvent:
    try:
        event_type = EventType(event_type_name)
    except ValueError as exc:
        raise ValueError(f"unknown revenue event type: {event_type_name}") from exc
    if event_type not in REVENUE_EVENT_TYPES:
        raise ValueError(f"not a revenue event type: {event_type_name}")

    fields = dict(TEST_DEFAULTS.get(event_type.value, {}))
    if overrides:
        fields.update(overrides)

    if event_type.value.startswith("twitch"):
        platform = Platform.TWITCH
    elif event_type.value.startswith("patreon"):
        platform = Platform.PATREON
    elif event_type.value.startswith("streamlabs"):
        platform = Platform.STREAMLABS
    else:
        platform = Platform.YOUTUBE
    source_event_id = fields.pop("source_event_id", None) or f"{TEST_SOURCE_PREFIX}{uuid.uuid4()}"
    return StreamEvent(
        platform=platform,
        event_type=event_type,
        occurred_at=utc_now(),
        source_event_id=source_event_id,
        gifter_user_name=str(fields.pop("gifter_user_name", "test_viewer")),
        amount_micros=fields.pop("amount_micros", None),
        amount_display=fields.pop("amount_display", None),
        currency=fields.pop("currency", None),
        quantity=fields.pop("quantity", None),
        tier=fields.pop("tier", None),
        message=fields.pop("message", None),
        raw={"test": True},
        is_test=True,
    )
