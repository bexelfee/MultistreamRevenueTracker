from multistream_revenue_tracker.revenue.events import EventType, Platform
from multistream_revenue_tracker.monitors.youtube_monitor import (
    MEMBERSHIP_GIFTING_EVENT,
    NEW_SPONSOR_EVENT,
    SUPER_CHAT_EVENT,
    TEXT_MESSAGE_EVENT,
    _active_live_broadcasts,
    _build_stream_list_messages,
    normalize_youtube_message,
)


def test_normalizes_youtube_super_chat():
    _, response_class = _build_stream_list_messages()
    response = response_class()
    item = response.items.add()
    item.id = "chat-1"
    item.author_details.channel_id = "channel-1"
    item.author_details.display_name = "Paid Viewer"
    item.snippet.type = SUPER_CHAT_EVENT
    item.snippet.published_at = "2026-05-13T18:00:00Z"
    item.snippet.super_chat_details.amount_micros = 2_500_000
    item.snippet.super_chat_details.currency = "USD"
    item.snippet.super_chat_details.amount_display_string = "$2.50"
    item.snippet.super_chat_details.user_comment = "great stream"
    item.snippet.super_chat_details.tier = 1

    event = normalize_youtube_message(item)

    assert event.platform == Platform.YOUTUBE
    assert event.event_type == EventType.YOUTUBE_SUPER_CHAT
    assert event.is_revenue is True
    assert event.gifter_user_name == "Paid Viewer"
    assert event.amount_micros == 2_500_000
    assert event.amount_display == "$2.50"
    assert event.message == "great stream"


def test_youtube_chat_message_only_emitted_when_enabled():
    _, response_class = _build_stream_list_messages()
    response = response_class()
    item = response.items.add()
    item.id = "chat-2"
    item.author_details.display_name = "Test Chatter"
    item.snippet.type = TEXT_MESSAGE_EVENT
    item.snippet.published_at = "2026-05-13T18:01:00Z"
    item.snippet.text_message_details.message_text = "hello from chat"

    assert normalize_youtube_message(item, log_chat_messages=False) is None

    event = normalize_youtube_message(item, log_chat_messages=True)

    assert event.event_type == EventType.YOUTUBE_CHAT_MESSAGE
    assert event.is_revenue is False
    assert event.message == "hello from chat"


def test_normalizes_new_sponsor_membership_tier():
    _, response_class = _build_stream_list_messages()
    response = response_class()
    item = response.items.add()
    item.id = "chat-sponsor"
    item.author_details.display_name = "New Member"
    item.snippet.type = NEW_SPONSOR_EVENT
    item.snippet.published_at = "2026-05-13T18:02:00Z"
    item.snippet.new_sponsor_details.member_level_name = "Gold Member"

    event = normalize_youtube_message(item)

    assert event.event_type == EventType.YOUTUBE_MEMBERSHIP
    assert event.tier == "Gold Member"


def test_normalizes_membership_gift_tier_and_quantity():
    _, response_class = _build_stream_list_messages()
    response = response_class()
    item = response.items.add()
    item.id = "chat-gift"
    item.author_details.display_name = "Gifter"
    item.snippet.type = MEMBERSHIP_GIFTING_EVENT
    item.snippet.published_at = "2026-05-13T18:03:00Z"
    item.snippet.membership_gifting_details.gift_memberships_count = 5
    item.snippet.membership_gifting_details.gift_memberships_level_name = "Silver"

    event = normalize_youtube_message(item)

    assert event.event_type == EventType.YOUTUBE_MEMBERSHIP_GIFT
    assert event.tier == "Silver"
    assert event.quantity == 5


def test_active_live_broadcasts_filters_for_live_chat():
    broadcasts = [
        {"snippet": {"liveChatId": "scheduled-chat"}, "status": {"lifeCycleStatus": "ready"}},
        {"snippet": {}, "status": {"lifeCycleStatus": "live"}},
        {"snippet": {"liveChatId": "active-chat"}, "status": {"lifeCycleStatus": "live"}},
    ]

    assert _active_live_broadcasts(broadcasts) == [broadcasts[2]]
