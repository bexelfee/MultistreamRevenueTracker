from datetime import datetime, timezone

import pytest

from multistream_revenue_tracker.revenue.events import EventType, Platform, StreamEvent
from multistream_revenue_tracker.revenue.revenue_db import RevenueDatabase
from multistream_revenue_tracker.test_events import TEST_SOURCE_PREFIX, build_test_stream_event


def test_build_test_patreon_pledge():
    event = build_test_stream_event(EventType.PATREON_PLEDGE_CREATE.value)
    assert event.platform == Platform.PATREON
    assert event.tier == "1000"


def test_build_test_stream_event_is_marked_test():
    event = build_test_stream_event(EventType.TWITCH_BITS.value)
    assert event.is_test is True
    assert event.source_event_id.startswith(TEST_SOURCE_PREFIX)
    assert event.quantity == 100


def test_build_test_rejects_non_revenue():
    with pytest.raises(ValueError, match="not a revenue"):
        build_test_stream_event(EventType.TWITCH_CHAT_MESSAGE.value)


def test_overrides_from_ui_maps_tier_and_amount():
    from multistream_revenue_tracker.test_events import overrides_from_ui

    assert overrides_from_ui({"tier": "2"})["tier"] == "2000"
    o = overrides_from_ui({"amount": "5.5", "currency": "COP"})
    assert o["amount_micros"] == 5_500_000
    assert o["currency"] == "COP"
    assert o["amount_display"] == "5.50 COP"


def test_delete_all_test_events(tmp_path):
    db = RevenueDatabase(tmp_path / "test.db")
    db.initialize()
    started = datetime(2026, 1, 1, tzinfo=timezone.utc)
    live_event = StreamEvent(
        platform=Platform.TWITCH,
        event_type=EventType.TWITCH_BITS,
        occurred_at=started,
        source_event_id="live-bits-1",
        quantity=1,
        is_test=False,
    )
    test_event = build_test_stream_event(EventType.TWITCH_BITS.value)
    db.add_revenue_event(live_event)
    db.add_revenue_event(test_event)
    assert db.delete_all_test_events() == 1
    remaining = db.list_revenue_events(started)
    assert len(remaining) == 1
    assert remaining[0].is_test is False
