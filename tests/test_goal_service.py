from datetime import datetime, timezone

from multistream_revenue_tracker.revenue.events import EventType, Platform, StreamEvent
from multistream_revenue_tracker.goals.goal_service import GoalService, build_goal_service
from multistream_revenue_tracker.goals.goal_store import GoalStore
from multistream_revenue_tracker.goals.point_rules import PointRulesStore
from multistream_revenue_tracker.revenue.revenue_db import RevenueDatabase


def _service(tmp_path) -> GoalService:
    database = RevenueDatabase(tmp_path / "revenue.db")
    database.initialize()
    goal_store = GoalStore(tmp_path / "goals")
    rules_store = PointRulesStore(
        point_rules_path=tmp_path / "point_rules.json",
        exchange_rates_path=tmp_path / "exchange_rates.json",
    )
    return GoalService(goal_store, rules_store, database)


def test_compute_progress_includes_manual_adjustment_and_events(tmp_path):
    service = _service(tmp_path)
    started = datetime(2026, 5, 18, 10, 0, tzinfo=timezone.utc)
    goal = service.create_goal("May", 1000, started)
    service.apply_points_change(50, add=True)

    before = datetime(2026, 5, 18, 9, 0, tzinfo=timezone.utc)
    after = datetime(2026, 5, 18, 11, 0, tzinfo=timezone.utc)

    service.database.add_revenue_event(
        StreamEvent(
            platform=Platform.TWITCH,
            event_type=EventType.TWITCH_BITS,
            occurred_at=before,
            source_event_id="old",
            quantity=999,
        )
    )
    service.database.add_revenue_event(
        StreamEvent(
            platform=Platform.TWITCH,
            event_type=EventType.TWITCH_BITS,
            occurred_at=after,
            source_event_id="new",
            quantity=10,
        )
    )

    progress = service.compute_progress(goal)
    assert progress.current_points == 60
    assert progress.target_points == 1000
    assert progress.percent == 6.0


def test_apply_points_change_fractional_clamps_at_zero(tmp_path):
    service = _service(tmp_path)
    started = datetime(2026, 5, 18, 10, 0, tzinfo=timezone.utc)
    goal = service.create_goal("Fractional", 100, started)
    goal.manual_adjustment = 0.5
    service.goal_store.save_goal(goal)
    assert service.compute_progress(goal).current_points == 0.5
    service.apply_points_change(1, add=False)
    assert service.compute_progress(goal).current_points == 0


def test_reset_active_goal_points(tmp_path):
    service = _service(tmp_path)
    started = datetime(2026, 5, 18, 10, 0, tzinfo=timezone.utc)
    service.create_goal("Reset me", 100, started)
    service.apply_points_change(25.5, add=True)
    assert service.compute_progress().current_points == 25.5
    service.reset_active_goal_points()
    assert service.compute_progress().current_points == 0


def test_build_goal_service_from_app_settings(tmp_path):
    from multistream_revenue_tracker.config import AppSettings

    app = AppSettings(
        log_level="INFO",
        log_chat_messages_for_testing=False,
        database_path=tmp_path / "revenue.db",
        ui_host="127.0.0.1",
        ui_port=8080,
        goals_directory=tmp_path / "goals",
        point_rules_path=tmp_path / "point_rules.json",
        exchange_rates_path=tmp_path / "exchange_rates.json",
        base_currency="EUR",
        enable_test_events=True,
        twitch_sub_resub_dedupe_seconds=60,
    )
    database = RevenueDatabase(app.database_path)
    database.initialize()
    service = build_goal_service(app, database)
    assert service.goal_store.goals_directory.exists()
