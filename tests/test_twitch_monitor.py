from types import SimpleNamespace

from multistream_revenue_tracker.revenue.events import EventType, Platform
from multistream_revenue_tracker.monitors.twitch_monitor import normalize_bits_use, normalize_chat_message, normalize_subscription_gift


def test_normalizes_twitch_bits_use():
    message = SimpleNamespace(
        event=SimpleNamespace(
            user_id="u1",
            user_login="bitviewer",
            bits=100,
            type="cheer",
            message=SimpleNamespace(text="nice"),
            broadcaster_user_id="b1",
            broadcaster_user_login="streamer",
        ),
        metadata=SimpleNamespace(message_id="event-1", message_timestamp="2026-05-13T18:00:00Z"),
    )

    event = normalize_bits_use(message)

    assert event.platform == Platform.TWITCH
    assert event.event_type == EventType.TWITCH_BITS
    assert event.is_revenue is True
    assert event.gifter_user_name == "bitviewer"
    assert event.quantity == 100
    assert event.amount_display == "100 bits"
    assert event.message == "nice"


def test_normalizes_twitch_subscription_gift():
    message = SimpleNamespace(
        event=SimpleNamespace(
            user_id="u2",
            user_login="giftviewer",
            total=5,
            tier="1000",
            is_anonymous=False,
            cumulative_total=12,
            broadcaster_user_id="b1",
            broadcaster_user_login="streamer",
        ),
        metadata=SimpleNamespace(message_id="event-2", message_timestamp="2026-05-13T18:02:00Z"),
    )

    event = normalize_subscription_gift(message)

    assert event.event_type == EventType.TWITCH_SUBSCRIPTION_GIFT
    assert event.gifter_user_name == "giftviewer"
    assert event.quantity == 5
    assert event.tier == "1000"


def test_normalizes_twitch_chat_message_as_test_event():
    message = SimpleNamespace(
        event=SimpleNamespace(
            chatter_user_id="u3",
            chatter_user_login="chatviewer",
            message_id="chat-1",
            message=SimpleNamespace(text="hello from twitch"),
            message_type="text",
            broadcaster_user_id="b1",
            broadcaster_user_login="streamer",
        ),
        metadata=SimpleNamespace(message_id="event-3", message_timestamp="2026-05-13T18:03:00Z"),
    )

    event = normalize_chat_message(message)

    assert event.platform == Platform.TWITCH
    assert event.event_type == EventType.TWITCH_CHAT_MESSAGE
    assert event.is_revenue is False
    assert event.gifter_user_name == "chatviewer"
    assert event.message == "hello from twitch"
    assert event.source_event_id == "chat-1"
