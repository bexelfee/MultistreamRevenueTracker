import pytest

from multistream_revenue_tracker.ui.goal_broadcast import GoalBroadcaster
from multistream_revenue_tracker.goals.goal_service import GoalService
from multistream_revenue_tracker.goals.goal_store import GoalStore
from multistream_revenue_tracker.goals.point_rules import PointRulesStore


@pytest.mark.asyncio
async def test_broadcast_progress_includes_bar_appearance(tmp_path):
    rules = PointRulesStore(
        point_rules_path=tmp_path / "point_rules.json",
        exchange_rates_path=tmp_path / "exchange_rates.json",
    )
    rules.load()
    from multistream_revenue_tracker.revenue.revenue_db import RevenueDatabase

    db = RevenueDatabase(tmp_path / "rev.db")
    db.initialize()
    goal_service = GoalService(GoalStore(tmp_path / "goals"), rules, db)
    broadcaster = GoalBroadcaster()
    sent: list[dict] = []

    class FakeWebSocket:
        client_state = 1

        async def send_json(self, payload):
            sent.append(payload)

    from starlette.websockets import WebSocketState

    ws = FakeWebSocket()
    ws.client_state = WebSocketState.CONNECTED
    await broadcaster.register(ws)

    appearance = {
        "fill_color": "#112233",
        "gradient_color": "#445566",
        "use_gradient": True,
        "font_family": "Arial, Helvetica, sans-serif",
    }
    await broadcaster.broadcast_progress(goal_service, bar_appearance=appearance)
    assert len(sent) == 1
    assert sent[0]["type"] == "progress"
    assert sent[0]["bar_appearance"] == appearance


@pytest.mark.asyncio
async def test_broadcast_progress_includes_progress_effects(tmp_path):
    rules = PointRulesStore(
        point_rules_path=tmp_path / "point_rules.json",
        exchange_rates_path=tmp_path / "exchange_rates.json",
    )
    rules.load()
    from multistream_revenue_tracker.revenue.revenue_db import RevenueDatabase

    db = RevenueDatabase(tmp_path / "rev.db")
    db.initialize()
    goal_service = GoalService(GoalStore(tmp_path / "goals"), rules, db)
    broadcaster = GoalBroadcaster()
    sent: list[dict] = []

    class FakeWebSocket:
        client_state = 1

        async def send_json(self, payload):
            sent.append(payload)

    from starlette.websockets import WebSocketState

    ws = FakeWebSocket()
    ws.client_state = WebSocketState.CONNECTED
    await broadcaster.register(ws)

    effects = {"goal_complete": "pulse", "points_added": "bar_flash"}
    await broadcaster.broadcast_progress(goal_service, progress_effects=effects)
    assert len(sent) == 1
    assert sent[0]["type"] == "progress"
    assert sent[0]["progress_effects"] == effects


def test_build_ws_state_includes_progress_effects_from_user_config(tmp_path):
    from multistream_revenue_tracker.revenue.revenue_db import RevenueDatabase
    from multistream_revenue_tracker.ui.goal_broadcast import build_ws_state

    rules = PointRulesStore(
        point_rules_path=tmp_path / "point_rules.json",
        exchange_rates_path=tmp_path / "exchange_rates.json",
    )
    rules.load()
    db = RevenueDatabase(tmp_path / "rev.db")
    db.initialize()
    goal_service = GoalService(GoalStore(tmp_path / "goals"), rules, db)
    user_config = {
        "progress_effects": {"goal_complete": "glow", "points_added": "none"},
    }
    payload = build_ws_state(goal_service, user_config=user_config)
    assert payload["progress_effects"] == user_config["progress_effects"]


@pytest.mark.asyncio
async def test_broadcast_progress_effect_preview_targets_overlay_only(tmp_path):
    rules = PointRulesStore(
        point_rules_path=tmp_path / "point_rules.json",
        exchange_rates_path=tmp_path / "exchange_rates.json",
    )
    rules.load()
    from multistream_revenue_tracker.revenue.revenue_db import RevenueDatabase

    db = RevenueDatabase(tmp_path / "rev.db")
    db.initialize()
    broadcaster = GoalBroadcaster()
    sent: dict[str, list[dict]] = {"dashboard": [], "overlay": []}

    class FakeWebSocket:
        def __init__(self, role: str) -> None:
            self.role = role
            self.client_state = 1

        async def send_json(self, payload):
            sent[self.role].append(payload)

    from starlette.websockets import WebSocketState

    dash = FakeWebSocket("dashboard")
    dash.client_state = WebSocketState.CONNECTED
    overlay = FakeWebSocket("overlay")
    overlay.client_state = WebSocketState.CONNECTED
    await broadcaster.register(dash, role="dashboard")
    await broadcaster.register(overlay, role="overlay")

    await broadcaster.broadcast_progress_effect_preview(channel="goal", effect_id="confetti")
    assert len(sent["dashboard"]) == 0
    assert len(sent["overlay"]) == 1
    assert sent["overlay"][0]["type"] == "progress_effects.preview"
    assert sent["overlay"][0]["channel"] == "goal"
    assert sent["overlay"][0]["effect_id"] == "confetti"
