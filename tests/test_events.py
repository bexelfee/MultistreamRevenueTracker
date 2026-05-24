from datetime import datetime, timezone

from multistream_revenue_tracker.revenue.events import REVENUE_EVENT_TYPES, EventType, Platform, StreamEvent


def test_stream_event_serializes_for_json():
    event = StreamEvent(
        platform=Platform.YOUTUBE,
        event_type=EventType.YOUTUBE_SUPER_CHAT,
        occurred_at=datetime(2026, 5, 13, 18, 0, tzinfo=timezone.utc),
        source_event_id="abc",
        gifter_user_name="viewer",
        amount_micros=1_500_000,
        currency="USD",
    )

    data = event.to_json_dict()

    assert data["platform"] == "youtube"
    assert data["event_type"] == "youtube_super_chat"
    assert data["occurred_at"] == "2026-05-13T18:00:00+00:00"
    assert event.is_revenue is True


def test_youtube_chat_message_is_not_revenue():
    event = StreamEvent(
        platform=Platform.YOUTUBE,
        event_type=EventType.YOUTUBE_CHAT_MESSAGE,
        occurred_at=datetime.now(timezone.utc),
    )

    assert event.is_revenue is False


def test_patreon_pledge_create_is_revenue():
    event = StreamEvent(
        platform=Platform.PATREON,
        event_type=EventType.PATREON_PLEDGE_CREATE,
        occurred_at=datetime.now(timezone.utc),
    )
    assert event.is_revenue is True
    assert EventType.PATREON_PLEDGE_CREATE in REVENUE_EVENT_TYPES


def test_twitch_chat_message_is_not_revenue():
    event = StreamEvent(
        platform=Platform.TWITCH,
        event_type=EventType.TWITCH_CHAT_MESSAGE,
        occurred_at=datetime.now(timezone.utc),
    )

    assert event.is_revenue is False
