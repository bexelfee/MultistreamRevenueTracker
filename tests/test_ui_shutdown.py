import asyncio

import pytest
from fastapi.testclient import TestClient

from multistream_revenue_tracker.monitors.monitor_status import MonitorStatusRegistry, build_initial_status
from multistream_revenue_tracker.ui.app import create_app
from multistream_revenue_tracker.ui.goal_broadcast import GoalBroadcaster, build_ws_state
from multistream_revenue_tracker.ui.routes import (
    _cancel_dashboard_shutdown_grace,
    _request_shutdown_if_last_dashboard_client,
)

from test_monitor_status import _app_config


def test_shutdown_request_sets_stop_requested():
    stop_requested = asyncio.Event()
    registry = MonitorStatusRegistry(build_initial_status(_app_config(), None))
    app = create_app(monitor_registry=registry, stop_requested=stop_requested)
    client = TestClient(app)

    with client.websocket_connect(f"/ws?token={app.state.ui_token}") as ws:
        ws.send_json({"type": "app.shutdown.request"})
        reply = None
        for _ in range(20):
            message = ws.receive_json()
            if message.get("type") == "app.shutting_down":
                reply = message
                break

    assert reply == {"type": "app.shutting_down"}
    assert stop_requested.is_set()


@pytest.mark.asyncio
async def test_dashboard_disconnect_waits_before_shutdown(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        "multistream_revenue_tracker.ui.routes.DASHBOARD_DISCONNECT_GRACE_SECONDS",
        0.2,
    )
    stop_requested = asyncio.Event()
    registry = MonitorStatusRegistry(build_initial_status(_app_config(), None))
    app = create_app(monitor_registry=registry, stop_requested=stop_requested)

    class _FakeWebSocket:
        client_state = None

        async def send_json(self, message):
            del message

    broadcaster: GoalBroadcaster = app.state.goal_broadcaster
    ws = _FakeWebSocket()
    await broadcaster.register(ws, role="dashboard")
    await broadcaster.unregister(ws)
    await _request_shutdown_if_last_dashboard_client(app)

    assert not stop_requested.is_set()
    await asyncio.sleep(0.05)
    assert not stop_requested.is_set()

    await asyncio.sleep(0.35)
    assert stop_requested.is_set()


@pytest.mark.asyncio
async def test_dashboard_reconnect_cancels_pending_shutdown(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        "multistream_revenue_tracker.ui.routes.DASHBOARD_DISCONNECT_GRACE_SECONDS",
        0.2,
    )
    stop_requested = asyncio.Event()
    registry = MonitorStatusRegistry(build_initial_status(_app_config(), None))
    app = create_app(monitor_registry=registry, stop_requested=stop_requested)
    broadcaster: GoalBroadcaster = app.state.goal_broadcaster

    class _FakeWebSocket:
        client_state = None

        async def send_json(self, message):
            del message

    first = _FakeWebSocket()
    await broadcaster.register(first, role="dashboard")
    await broadcaster.unregister(first)
    await _request_shutdown_if_last_dashboard_client(app)
    await asyncio.sleep(0.05)
    assert not stop_requested.is_set()

    second = _FakeWebSocket()
    await broadcaster.register(second, role="dashboard")
    await _cancel_dashboard_shutdown_grace(app)
    await asyncio.sleep(0.35)
    assert not stop_requested.is_set()


@pytest.mark.asyncio
async def test_broadcast_shutdown_complete_message():
    from starlette.websockets import WebSocketState

    broadcaster = GoalBroadcaster()
    received = []

    class _FakeWebSocket:
        client_state = WebSocketState.CONNECTED

        async def send_json(self, message):
            received.append(message)

    await broadcaster.register(_FakeWebSocket())
    await broadcaster.broadcast_shutdown_complete()
    assert received == [{"type": "app.shutdown.complete"}]


def test_build_ws_state_includes_monitors():
    registry = MonitorStatusRegistry(build_initial_status(_app_config(), None))
    registry.set_status("twitch", "active", None)

    class _StubGoalService:
        def build_state(self):
            return {"goals": [], "active_goal_id": None, "point_rules": {}, "exchange_rates": {}, "progress": {}}

    payload = build_ws_state(
        _StubGoalService(), monitor_registry=registry, user_config={"app": {}}, allow_test_events=False,
    )
    assert payload["type"] == "state"
    assert payload["monitors"][0]["id"] == "twitch"
    assert payload["monitors"][0]["status"] == "active"
    assert payload["allow_test_events"] is False
