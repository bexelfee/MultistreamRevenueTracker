from datetime import datetime, timezone

import pytest

from multistream_revenue_tracker.revenue.events import EventType
from multistream_revenue_tracker.goals.goal_service import GoalService
from multistream_revenue_tracker.goals.goal_store import GoalStore
from multistream_revenue_tracker.goals.point_rules import PointRulesStore
from multistream_revenue_tracker.goals.points_calculator import points_for_event
from multistream_revenue_tracker.revenue.revenue_db import RevenueDatabase
from multistream_revenue_tracker.revenue.revenue_validity import (
    build_auto_invalid_raw,
    prepare_invalidate,
    prepare_validate,
    status_label,
)
from test_points_calculator import _rules_store, _stored


def test_build_auto_invalid_raw_status():
    raw = build_auto_invalid_raw(EventType.TWITCH_RESUBSCRIPTION.value, base_raw={"cumulative_months": 62})
    assert raw["valid_event_type"] == "twitch_resubscription"
    assert raw["status_history"][-1]["reason"] == "duplicate_sub_resub"
    assert raw["status_history"][-1]["source"] == "auto"


def test_status_label_duplicate_auto():
    event = _stored(
        event_type=EventType.REVENUE_INVALID,
        raw=build_auto_invalid_raw(EventType.TWITCH_RESUBSCRIPTION.value),
    )
    assert status_label(event) == "Duplicate (auto)"


def test_status_label_manual_removed_and_added():
    event = _stored(event_type=EventType.TWITCH_SUBSCRIPTION)
    inv = prepare_invalidate(event)
    assert inv is not None
    invalid = _stored(event_type=inv[0], raw=inv[1])
    assert status_label(invalid) == "Removed (manual)"

    val = prepare_validate(invalid)
    assert val is not None
    valid = _stored(event_type=val[0], raw=val[1])
    assert status_label(valid) == "Added (manual)"


def test_legacy_suppressed_effective_type_and_zero_points(tmp_path):
    store = _rules_store(tmp_path)
    event = _stored(
        event_type=EventType.TWITCH_RESUBSCRIPTION_SUPPRESSED,
        tier="1000",
        raw={"valid_event_type": "twitch_resubscription"},
    )
    assert points_for_event(event, store) == 0


@pytest.fixture
def goal_service(tmp_path):
    db = RevenueDatabase(tmp_path / "rev.db")
    db.initialize()
    rules = PointRulesStore(
        point_rules_path=tmp_path / "point_rules.json",
        exchange_rates_path=tmp_path / "exchange_rates.json",
    )
    rules.load()
    gs = GoalService(GoalStore(tmp_path / "goals"), rules, db)
    gs.create_goal("Test", 1000, datetime(2026, 1, 1, tzinfo=timezone.utc))
    return gs


def test_goal_service_invalidate_validate_changes_progress(goal_service):
    from multistream_revenue_tracker.revenue.events import Platform, StreamEvent

    event = StreamEvent(
        platform=Platform.TWITCH,
        event_type=EventType.TWITCH_SUBSCRIPTION,
        occurred_at=datetime(2026, 5, 20, 12, 0, tzinfo=timezone.utc),
        source_event_id="sub-progress-1",
        tier="1000",
    )
    row_id = goal_service.database.add_revenue_event(event)
    assert row_id is not None
    stored = goal_service.database.get_revenue_event(row_id)
    assert stored is not None
    event_pts = points_for_event(stored, goal_service.rules_store)
    assert event_pts > 0

    before = goal_service.compute_progress().current_points
    goal_service.invalidate_revenue_event(row_id)
    assert goal_service.compute_progress().current_points == before - event_pts

    goal_service.validate_revenue_event(row_id)
    assert goal_service.compute_progress().current_points == before
