from datetime import datetime, timezone

from multistream_revenue_tracker.goals.goal_store import GoalStore


def test_goal_store_round_trip(tmp_path):
    store = GoalStore(tmp_path / "goals")
    goal = store.create_goal("Subathon", 5000, datetime(2026, 5, 18, 20, 0, tzinfo=timezone.utc))
    store.set_active_goal_id(goal.id)

    loaded = store.get_goal(goal.id)
    assert loaded is not None
    assert loaded.name == "Subathon"
    assert loaded.target_points == 5000
    assert store.get_active_goal_id() == goal.id
    assert len(store.list_goals()) == 1


def test_delete_goal_clears_active(tmp_path):
    store = GoalStore(tmp_path / "goals")
    goal = store.create_goal("Temp", 100)
    store.set_active_goal_id(goal.id)
    assert store.delete_goal(goal.id) is True
    assert store.get_active_goal_id() is None
