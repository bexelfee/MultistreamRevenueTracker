from datetime import datetime, timezone

import pytest

from multistream_revenue_tracker.revenue.events import EventType, Platform, StreamEvent
from multistream_revenue_tracker.revenue.session_revenue import SessionRevenueStore, row_from_stored, simplify_revenue_event
from test_points_calculator import _stored


def test_simplify_revenue_event_bits():
    event = StreamEvent(
        platform=Platform.TWITCH,
        event_type=EventType.TWITCH_BITS,
        occurred_at=datetime.now(timezone.utc),
        gifter_user_name="viewer1",
        quantity=500,
    )
    row = simplify_revenue_event(event)
    assert row["platform"] == "twitch"
    assert row["type"] == "Bits"
    assert row["amount"] == "×500"
    assert row["user"] == "viewer1"


def test_simplify_revenue_event_super_chat():
    event = StreamEvent(
        platform=Platform.YOUTUBE,
        event_type=EventType.YOUTUBE_SUPER_CHAT,
        occurred_at=datetime.now(timezone.utc),
        amount_display="5.00 EUR",
        gifter_user_name="fan",
    )
    row = simplify_revenue_event(event)
    assert row["amount"] == "5.00 EUR"
    assert row["type"] == "Super Chat"


def test_row_from_stored_valid_and_invalid():
    valid = _stored(event_type=EventType.TWITCH_BITS, quantity=50)
    row = row_from_stored(valid)
    assert row["id"] == 1
    assert row["is_valid"] is True
    assert row["can_remove"] is True
    assert row["can_add"] is False
    assert row["status"] == "Valid"

    from multistream_revenue_tracker.revenue.revenue_validity import build_auto_invalid_raw

    invalid = _stored(
        event_type=EventType.REVENUE_INVALID,
        raw=build_auto_invalid_raw(EventType.TWITCH_RESUBSCRIPTION.value),
    )
    row2 = row_from_stored(invalid)
    assert row2["is_valid"] is False
    assert row2["can_add"] is True
    assert row2["can_remove"] is False
    assert row2["status"] == "Duplicate (auto)"


@pytest.mark.asyncio
async def test_session_revenue_store_update_by_id():
    store = SessionRevenueStore()
    stored = _stored(id=42, event_type=EventType.TWITCH_SUBSCRIPTION, tier="1000")
    await store.append_stored(stored)
    from multistream_revenue_tracker.revenue.revenue_validity import build_auto_invalid_raw

    invalid = _stored(
        id=42,
        event_type=EventType.REVENUE_INVALID,
        tier="1000",
        raw=build_auto_invalid_raw(EventType.TWITCH_SUBSCRIPTION.value),
    )
    assert await store.update_by_id(42, invalid) is True
    snap = store.snapshot()
    assert snap[0]["is_valid"] is False
    assert snap[0]["can_add"] is True


@pytest.mark.asyncio
async def test_session_revenue_store_append_and_snapshot():
    store = SessionRevenueStore(max_items=2)
    event = StreamEvent(
        platform=Platform.TWITCH,
        event_type=EventType.TWITCH_BITS,
        occurred_at=datetime.now(timezone.utc),
        quantity=100,
    )
    await store.append(event)
    await store.append(event)
    await store.append(event)
    assert len(store.snapshot()) == 2
