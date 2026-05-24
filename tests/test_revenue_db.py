from datetime import datetime, timedelta, timezone

import pytest

from multistream_revenue_tracker.revenue.events import EventType, Platform, StreamEvent
from multistream_revenue_tracker.revenue.revenue_db import RevenueDatabase


def _revenue_event(event_type: EventType, *, occurred_at: datetime, source_event_id: str, quantity: int | None = None, amount_micros: int | None = None) -> StreamEvent:
    return StreamEvent(
        platform=Platform.TWITCH if event_type.value.startswith("twitch") else Platform.YOUTUBE,
        event_type=event_type,
        occurred_at=occurred_at,
        source_event_id=source_event_id,
        gifter_user_name="viewer",
        quantity=quantity,
        amount_micros=amount_micros,
    )


@pytest.fixture
def database(tmp_path):
    db = RevenueDatabase(tmp_path / "test.db")
    db.initialize()
    return db


def test_add_and_get_revenue_event(database):
    occurred_at = datetime(2026, 5, 14, 12, 0, tzinfo=timezone.utc)
    event = _revenue_event(EventType.TWITCH_BITS, occurred_at=occurred_at, source_event_id="bits-1", quantity=100)
    row_id = database.add_revenue_event(event)
    stored = database.get_revenue_event(row_id)
    assert stored is not None
    assert stored.event_type == EventType.TWITCH_BITS
    assert stored.quantity == 100
    assert stored.source_event_id == "bits-1"


def test_duplicate_source_event_is_ignored(database):
    occurred_at = datetime(2026, 5, 14, 12, 0, tzinfo=timezone.utc)
    event = _revenue_event(EventType.TWITCH_SUBSCRIPTION, occurred_at=occurred_at, source_event_id="sub-1")
    first = database.add_revenue_event(event)
    second = database.add_revenue_event(event)
    assert first is not None
    assert second is None
    assert database.get_revenue_event(first) is not None


def test_rejects_non_revenue_event(database):
    event = StreamEvent(platform=Platform.YOUTUBE, event_type=EventType.YOUTUBE_CHAT_MESSAGE, occurred_at=datetime.now(timezone.utc))
    with pytest.raises(ValueError, match="non-revenue"):
        database.add_revenue_event(event)


def test_remove_revenue_event_by_id(database):
    occurred_at = datetime(2026, 5, 14, 12, 0, tzinfo=timezone.utc)
    event = _revenue_event(EventType.YOUTUBE_SUPER_CHAT, occurred_at=occurred_at, source_event_id="sc-1", amount_micros=2_500_000)
    row_id = database.add_revenue_event(event)
    assert database.remove_revenue_event(row_id) is True
    assert database.get_revenue_event(row_id) is None


def test_update_revenue_event(database):
    occurred_at = datetime(2026, 5, 14, 12, 0, tzinfo=timezone.utc)
    event = _revenue_event(EventType.TWITCH_SUBSCRIPTION, occurred_at=occurred_at, source_event_id="sub-upd-1")
    row_id = database.add_revenue_event(event)
    from multistream_revenue_tracker.revenue.revenue_validity import build_auto_invalid_raw

    raw = build_auto_invalid_raw(EventType.TWITCH_SUBSCRIPTION.value)
    updated = database.update_revenue_event(row_id, event_type=EventType.REVENUE_INVALID, raw=raw)
    assert updated is not None
    assert updated.event_type == EventType.REVENUE_INVALID
    assert updated.raw["valid_event_type"] == "twitch_subscription"


def test_migrate_suppressed_resub_to_revenue_invalid(database):
    occurred_at = datetime(2026, 5, 14, 12, 0, tzinfo=timezone.utc)
    event = StreamEvent(
        platform=Platform.TWITCH,
        event_type=EventType.TWITCH_RESUBSCRIPTION_SUPPRESSED,
        occurred_at=occurred_at,
        source_event_id="legacy-sup-1",
        gifter_user_name="viewer",
        tier="1000",
        raw={"tier": "1000"},
    )
    row_id = database.add_revenue_event(event)
    db2 = RevenueDatabase(database.db_path)
    db2.initialize()
    stored = db2.get_revenue_event(row_id)
    assert stored.event_type == EventType.REVENUE_INVALID
    assert stored.raw.get("valid_event_type") == "twitch_resubscription"


def test_list_revenue_events_respects_until_datetime(database):
    base = datetime(2026, 5, 14, 12, 0, tzinfo=timezone.utc)
    database.add_revenue_event(_revenue_event(EventType.TWITCH_SUBSCRIPTION_GIFT, occurred_at=base, source_event_id="gift-1", quantity=5))
    database.add_revenue_event(_revenue_event(EventType.TWITCH_SUBSCRIPTION_GIFT, occurred_at=base + timedelta(hours=2), source_event_id="gift-2", quantity=3))
    events = database.list_revenue_events(base, until_datetime=base + timedelta(hours=1))
    assert len(events) == 1
    assert events[0].source_event_id == "gift-1"
