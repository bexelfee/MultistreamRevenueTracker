from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Awaitable, Callable

from .goal_store import Goal, GoalStore
from .point_rules import PointRulesStore
from .points_calculator import points_for_events_fractional
from ..revenue.revenue_db import RevenueDatabase, StoredRevenueEvent
from ..revenue.revenue_validity import prepare_invalidate, prepare_validate

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class GoalProgress:
    goal_id: str | None
    name: str | None
    current_points: float
    target_points: int
    percent: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "goal_id": self.goal_id, "name": self.name, "current_points": self.current_points,
            "target_points": self.target_points, "percent": self.percent,
        }


class GoalService:
    def __init__(self, goal_store: GoalStore, rules_store: PointRulesStore, database: RevenueDatabase):
        self.goal_store = goal_store
        self.rules_store = rules_store
        self.database = database
        self._listeners: list[Callable[[], Awaitable[None]]] = []
        self.goal_store.ensure_initialized()
        self.rules_store.load()

    def add_progress_listener(self, callback: Callable[[], Awaitable[None]]) -> None:
        self._listeners.append(callback)

    async def notify_progress_changed(self) -> None:
        for listener in list(self._listeners):
            try:
                await listener()
            except Exception:
                LOGGER.exception("progress listener failed")

    def build_state(self) -> dict[str, Any]:
        return {
            "goals": [goal.to_dict() for goal in self.goal_store.list_goals()],
            "active_goal_id": self.goal_store.get_active_goal_id(),
            "point_rules": self.rules_store.rules_for_ui(),
            "exchange_rates": self.rules_store.rates_for_ui(),
            "progress": self.compute_progress().to_dict(),
        }

    def compute_progress(self, goal: Goal | None = None) -> GoalProgress:
        active = (self.goal_store.get_goal(goal.id) or goal) if goal is not None else self.goal_store.get_active_goal()
        if active is None:
            return GoalProgress(goal_id=None, name=None, current_points=0, target_points=0, percent=0.0)
        events = self.database.list_revenue_events(active.started_at)
        event_points_exact = points_for_events_fractional(events, self.rules_store)
        current = round(active.manual_adjustment + event_points_exact, 2)
        target = max(active.target_points, 1)
        return GoalProgress(
            goal_id=active.id, name=active.name, current_points=current,
            target_points=active.target_points, percent=min(100.0, (current / target) * 100.0),
        )

    def save_rules(self, rules: dict[str, dict]) -> dict[str, dict]:
        return self.rules_store.save_rules(rules)

    def save_rates(self, rates: dict) -> dict:
        return self.rules_store.save_rates(rates)

    def create_goal(self, name: str, target_points: int, started_at: datetime | None = None, *, select: bool = True) -> Goal:
        goal = self.goal_store.create_goal(name, target_points, started_at)
        if select:
            self.goal_store.set_active_goal_id(goal.id)
        return goal

    def select_goal(self, goal_id: str) -> Goal:
        self.goal_store.set_active_goal_id(goal_id)
        goal = self.goal_store.get_goal(goal_id)
        if goal is None:
            raise ValueError(f"unknown goal id: {goal_id}")
        return goal

    def delete_goal(self, goal_id: str) -> bool:
        return self.goal_store.delete_goal(goal_id)

    def invalidate_revenue_event(self, event_id: int) -> StoredRevenueEvent:
        stored = self.database.get_revenue_event(event_id)
        if stored is None:
            raise ValueError(f"unknown revenue event id: {event_id}")
        update = prepare_invalidate(stored)
        if update is None:
            raise ValueError("event is already invalid")
        event_type, raw = update
        updated = self.database.update_revenue_event(event_id, event_type=event_type, raw=raw)
        if updated is None:
            raise ValueError(f"failed to update revenue event id: {event_id}")
        return updated

    def validate_revenue_event(self, event_id: int) -> StoredRevenueEvent:
        stored = self.database.get_revenue_event(event_id)
        if stored is None:
            raise ValueError(f"unknown revenue event id: {event_id}")
        update = prepare_validate(stored)
        if update is None:
            raise ValueError("event is already valid")
        event_type, raw = update
        updated = self.database.update_revenue_event(event_id, event_type=event_type, raw=raw)
        if updated is None:
            raise ValueError(f"failed to update revenue event id: {event_id}")
        return updated

    def apply_points_change(self, amount: float, *, add: bool) -> Goal:
        goal = self.goal_store.get_active_goal()
        if goal is None:
            raise ValueError("no active goal")
        amount = round(max(0.0, float(amount)), 2)
        delta = amount if add else -amount
        progress = self.compute_progress(goal)
        event_points = points_for_events_fractional(
            self.database.list_revenue_events(goal.started_at),
            self.rules_store,
        )
        new_total = max(0.0, round(progress.current_points + delta, 2))
        goal.manual_adjustment = round(new_total - event_points, 2)
        return self.goal_store.save_goal(goal)

    def reset_active_goal_points(self) -> Goal:
        goal = self.goal_store.get_active_goal()
        if goal is None:
            raise ValueError("no active goal")
        event_points = points_for_events_fractional(
            self.database.list_revenue_events(goal.started_at),
            self.rules_store,
        )
        goal.manual_adjustment = round(-event_points, 2)
        return self.goal_store.save_goal(goal)


def build_goal_service(config_app, database: RevenueDatabase) -> GoalService:
    rules_store = PointRulesStore(
        point_rules_path=config_app.point_rules_path,
        exchange_rates_path=config_app.exchange_rates_path,
        base_currency=config_app.base_currency,
    )
    return GoalService(GoalStore(config_app.goals_directory), rules_store, database)
