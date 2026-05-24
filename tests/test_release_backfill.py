"""Targeted backfill of high-risk test gaps identified during the release audit.

Covers Phase 8 of the release-readiness refactor:
- WebSocket validation: invalid JSON / oversized / invalid patch / unknown type
- Goal progress capping when current > target
- Subathon paused on start
- Revenue DB WAL mode is enabled
- monitor.restart.request routes through the coordinator
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from multistream_revenue_tracker.config import load_config
from multistream_revenue_tracker.goals.goal_service import build_goal_service
from multistream_revenue_tracker.revenue.revenue_db import RevenueDatabase
from multistream_revenue_tracker.services.subathon_service import SubathonService
from multistream_revenue_tracker.ui.app import create_app


# ---------------------------------------------------------------------------
# Revenue DB / WAL


def test_revenue_db_uses_wal_mode(tmp_path: Path) -> None:
    """The DB must run in WAL mode so concurrent monitor writes do not block
    dashboard reads (or vice versa). A regression to the default rollback
    journal would cause UI freezes under load."""
    db = RevenueDatabase(tmp_path / "rev.db")
    db.initialize()

    with sqlite3.connect(tmp_path / "rev.db") as conn:
        cursor = conn.execute("PRAGMA journal_mode;")
        mode = cursor.fetchone()[0]
    assert mode.lower() == "wal", f"expected WAL mode, got {mode}"


# ---------------------------------------------------------------------------
# Subathon paused on start


def test_subathon_service_starts_paused(tmp_path: Path) -> None:
    """The subathon timer must not start counting down before the user clicks
    Play — otherwise events that arrive during app startup get credited to
    a phantom session."""
    db = RevenueDatabase(tmp_path / "rev.db")
    db.initialize()
    service = SubathonService(
        state_path=tmp_path / "subathon_state.json",
        database=db,
        subathon_points=10,
        subathon_seconds=60,
        show_days=False,
    )
    snapshot = service.snapshot()
    assert snapshot["running"] is False
    assert snapshot["remaining_seconds"] == 0


# ---------------------------------------------------------------------------
# Goal progress 100% cap


def _seed_minimal_config(tmp_path: Path) -> tuple:
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps({
            "app": {"enable_test_events": False, "base_currency": "EUR"},
            "twitch": {"channel_name": ""},
        }),
        encoding="utf-8",
    )
    cfg = load_config(config_path)
    db = RevenueDatabase(cfg.app.database_path)
    db.initialize()
    service = build_goal_service(cfg.app, db)
    return cfg, db, service, config_path


def test_goal_progress_caps_at_one_hundred_percent(tmp_path: Path) -> None:
    """Manually credit more points than the target — the overlay bar should
    not visually go past 100%. The UI bar width is derived from
    ``percent`` so a value over 100 would push the fill outside its
    container."""
    _, _, service, _ = _seed_minimal_config(tmp_path)
    service.create_goal("g", 100, None, select=True)
    service.apply_points_change(250, add=True)

    progress = service.compute_progress()
    assert progress.percent <= 100.0, f"expected percent ≤ 100, got {progress.percent}"
    # Raw points may exceed target — only the *displayed* percent is capped.
    assert progress.current_points >= 100


# ---------------------------------------------------------------------------
# WebSocket validation


@pytest.fixture
def ws_app(tmp_path: Path):
    _, _, service, config_path = _seed_minimal_config(tmp_path)
    app = create_app(
        goal_service=service,
        allow_test_events=False,
        user_config={
            "app": {
                "log_chat_messages_for_testing": False,
                "base_currency": "EUR",
                "enable_test_events": False,
                "ui_port": 8080,
            },
            "twitch": {"channel_name": ""},
        },
        config_path=config_path,
    )
    return app


def _drain_until(ws, predicate, limit: int = 50):
    """Receive frames until ``predicate(message)`` returns True. The dashboard
    eagerly sends ``state`` + ``log`` frames on connect so callers must skip
    past them to assert on a specific reply."""
    for _ in range(limit):
        msg = ws.receive_json()
        if predicate(msg):
            return msg
    raise AssertionError("expected message not received within limit")


def test_ws_invalid_json_returns_error(ws_app) -> None:
    """A malformed text frame must not crash the dispatcher — it should
    surface an ``error`` envelope so the dashboard can show the user."""
    client = TestClient(ws_app)
    with client.websocket_connect(f"/ws?token={ws_app.state.ui_token}") as ws:
        ws.send_text("not json {")
        msg = _drain_until(ws, lambda m: m.get("type") == "error")
        assert "JSON" in msg["message"]


def test_ws_non_object_payload_returns_error(ws_app) -> None:
    """JSON arrays / scalars must be rejected — handlers assume a dict
    envelope. Without this guard a list would crash ``message.get('type')``."""
    client = TestClient(ws_app)
    with client.websocket_connect(f"/ws?token={ws_app.state.ui_token}") as ws:
        ws.send_text(json.dumps([1, 2, 3]))
        msg = _drain_until(ws, lambda m: m.get("type") == "error")
        assert "object" in msg["message"].lower()


def test_ws_invalid_config_patch_returns_error(ws_app) -> None:
    """``config.save`` requires ``config`` to be an object; a string or
    missing field must surface a validation error rather than persisting
    garbage to disk."""
    client = TestClient(ws_app)
    with client.websocket_connect(f"/ws?token={ws_app.state.ui_token}") as ws:
        ws.send_json({"type": "config.save", "config": "not-an-object"})
        msg = _drain_until(ws, lambda m: m.get("type") == "error")
        assert msg["message"]


def test_ws_unknown_message_type_is_silently_ignored(ws_app) -> None:
    """An unknown message type is logged at DEBUG and must NOT echo back an
    error frame (a third-party browser extension probing the socket would
    otherwise spam the dashboard alerts)."""
    client = TestClient(ws_app)
    with client.websocket_connect(f"/ws?token={ws_app.state.ui_token}") as ws:
        ws.send_json({"type": "definitely.not.a.real.type"})
        ws.send_json({"type": "ping"})
        msg = _drain_until(ws, lambda m: m.get("type") == "pong")
        assert msg == {"type": "pong"}


# ---------------------------------------------------------------------------
# monitor.restart.request


def test_ws_monitor_restart_calls_coordinator(ws_app) -> None:
    """The dashboard's "Restart" button under each monitor must reach the
    coordinator. This test installs a fake coordinator and verifies the
    request_restart() call by monitor_id."""

    class _FakeCoord:
        def __init__(self) -> None:
            self.restart_calls: list[str] = []

        def request_restart(self, monitor_id: str) -> None:
            self.restart_calls.append(monitor_id)

        def request_connect(self, monitor_id: str) -> None:  # pragma: no cover
            raise AssertionError("not exercised here")

        def request_disconnect(self, monitor_id: str) -> None:  # pragma: no cover
            raise AssertionError("not exercised here")

    fake = _FakeCoord()
    ws_app.state.monitor_coordinator = fake

    client = TestClient(ws_app)
    with client.websocket_connect(f"/ws?token={ws_app.state.ui_token}") as ws:
        ws.send_json({"type": "monitor.restart.request", "monitor_id": "twitch"})
        # Send a ping so we can synchronously assert the in-flight handler
        # finished before the connection is torn down.
        ws.send_json({"type": "ping"})
        _drain_until(ws, lambda m: m.get("type") == "pong")

    assert fake.restart_calls == ["twitch"]
