"""WebSocket handlers for subathon timer."""
from __future__ import annotations

import json

import pytest
from starlette.websockets import WebSocketState

from multistream_revenue_tracker.goals.goal_service import GoalService
from multistream_revenue_tracker.goals.goal_store import GoalStore
from multistream_revenue_tracker.goals.point_rules import PointRulesStore
from multistream_revenue_tracker.revenue.revenue_db import RevenueDatabase
from multistream_revenue_tracker.services.subathon_service import SubathonService
from multistream_revenue_tracker.ui.goal_broadcast import GoalBroadcaster
from multistream_revenue_tracker.ui.routes import _handle_client_message


class FakeApp:
    def __init__(self, state) -> None:
        self.state = state


class FakeWebSocket:
    client_state = WebSocketState.CONNECTED

    def __init__(self, app) -> None:
        self.app = app
        self.sent: list[dict] = []

    async def send_json(self, payload: dict) -> None:
        self.sent.append(payload)


@pytest.mark.asyncio
async def test_subathon_play_pause(tmp_path):
    db = RevenueDatabase(tmp_path / "rev.db")
    db.initialize()
    rules = PointRulesStore(
        point_rules_path=tmp_path / "rules.json",
        exchange_rates_path=tmp_path / "rates.json",
    )
    rules.load()
    goal_service = GoalService(GoalStore(tmp_path / "goals"), rules, db)
    subathon = SubathonService(tmp_path / "state.json", db)
    broadcaster = GoalBroadcaster()
    ws = FakeWebSocket(FakeApp(type("S", (), {
        "subathon_service": subathon,
        "goal_broadcaster": broadcaster,
        "config_path": None,
    })()))

    await _handle_client_message(ws, json.dumps({"type": "subathon.play"}), goal_service, broadcaster, ws.app)
    assert subathon.snapshot()["running"] is True

    await _handle_client_message(ws, json.dumps({"type": "subathon.pause"}), goal_service, broadcaster, ws.app)
    assert subathon.snapshot()["running"] is False


@pytest.mark.asyncio
async def test_subathon_set_time(tmp_path):
    db = RevenueDatabase(tmp_path / "rev.db")
    db.initialize()
    rules = PointRulesStore(
        point_rules_path=tmp_path / "rules.json",
        exchange_rates_path=tmp_path / "rates.json",
    )
    rules.load()
    goal_service = GoalService(GoalStore(tmp_path / "goals"), rules, db)
    subathon = SubathonService(tmp_path / "state.json", db)
    broadcaster = GoalBroadcaster()
    ws = FakeWebSocket(FakeApp(type("S", (), {
        "subathon_service": subathon,
        "goal_broadcaster": broadcaster,
        "config_path": None,
    })()))

    await _handle_client_message(
        ws,
        json.dumps({"type": "subathon.set_time", "hours": 0, "minutes": 5, "seconds": 0}),
        goal_service,
        broadcaster,
        ws.app,
    )
    assert subathon.snapshot()["remaining_seconds"] == 300
    assert subathon.snapshot()["display"] == "00:05:00"
