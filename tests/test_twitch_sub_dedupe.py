from datetime import datetime, timedelta, timezone

from multistream_revenue_tracker.revenue.events import EventType
from multistream_revenue_tracker.goals.points_calculator import points_for_event
from multistream_revenue_tracker.monitors.twitch_monitor import normalize_subscription_message
from multistream_revenue_tracker.platforms.twitch_sub_dedupe import RecentSubTracker
from test_points_calculator import _rules_store, _stored


def test_recent_sub_tracker_suppresses_within_window():
    tracker = RecentSubTracker(60)
    t0 = datetime(2026, 5, 20, 16, 46, 59, tzinfo=timezone.utc)
    tracker.record_subscribe("user-1", t0)
    t1 = t0 + timedelta(seconds=33)
    assert tracker.should_suppress_resub("user-1", t1) is True


def test_recent_sub_tracker_does_not_suppress_after_window():
    tracker = RecentSubTracker(60)
    t0 = datetime(2026, 5, 20, 16, 46, 59, tzinfo=timezone.utc)
    tracker.record_subscribe("user-1", t0)
    t1 = t0 + timedelta(seconds=61)
    assert tracker.should_suppress_resub("user-1", t1) is False


def test_normalize_resub_suppressed_when_recent_sub():
    from types import SimpleNamespace

    tracker = RecentSubTracker(60)
    sub_at = datetime(2026, 5, 20, 16, 46, 59, tzinfo=timezone.utc)
    tracker.record_subscribe("uid-1", sub_at)

    message = SimpleNamespace(
        event=SimpleNamespace(
            user_id="uid-1",
            user_login="viewer",
            tier="1000",
            duration_months=1,
            cumulative_months=62,
            message=SimpleNamespace(text="resub msg"),
            broadcaster_user_id="b1",
            broadcaster_user_login="streamer",
        ),
        metadata=SimpleNamespace(
            message_id="resub-msg-1",
            message_timestamp=(sub_at + timedelta(seconds=33)).isoformat().replace("+00:00", "Z"),
        ),
    )
    event = normalize_subscription_message(message, tracker)
    assert event.event_type == EventType.REVENUE_INVALID
    assert event.raw.get("valid_event_type") == "twitch_resubscription"
    assert event.raw.get("cumulative_months") == 62
    assert event.is_revenue is True


def test_invalid_resub_scores_zero_points(tmp_path):
    store = _rules_store(tmp_path)
    from multistream_revenue_tracker.revenue.revenue_validity import build_auto_invalid_raw

    event = _stored(
        event_type=EventType.REVENUE_INVALID,
        tier="1000",
        raw=build_auto_invalid_raw(EventType.TWITCH_RESUBSCRIPTION.value),
    )
    assert points_for_event(event, store) == 0
