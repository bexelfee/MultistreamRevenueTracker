import asyncio
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from multistream_revenue_tracker.config import load_config
from multistream_revenue_tracker.goals.goal_service import build_goal_service
from multistream_revenue_tracker.revenue.revenue_db import RevenueDatabase
from multistream_revenue_tracker.ui.app import create_app


def _minimal_config():
    return {
        "app": {
            "enable_twitch": False,
            "enable_youtube": False,
            "enable_patreon": False,
            "enable_test_events": False,
        },
        "twitch": {"channel_name": ""},
    }


@pytest.fixture
def config_app(tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(_minimal_config()), encoding="utf-8")
    cfg = load_config(config_path)
    database = RevenueDatabase(cfg.app.database_path)
    database.initialize()
    goal_service = build_goal_service(cfg.app, database)
    app = create_app(
        goal_service=goal_service,
        allow_test_events=cfg.app.enable_test_events,
        user_config={
            "app": {
                "enable_twitch": False,
                "enable_youtube": False,
                "enable_patreon": False,
                "log_chat_messages_for_testing": False,
                "base_currency": "EUR",
                "enable_test_events": False,
                "ui_port": 8080,
            },
            "twitch": {"channel_name": ""},
        },
        config_path=config_path,
    )
    return app, config_path


def test_config_save_updates_file(config_app):
    app, config_path = config_app
    client = TestClient(app)
    patch = {
        "app": {
            "enable_twitch": False,
            "enable_youtube": False,
            "enable_patreon": False,
            "log_chat_messages_for_testing": True,
            "base_currency": "GBP",
            "enable_test_events": True,
            "ui_port": 9001,
        },
        "twitch": {"channel_name": ""},
    }
    with client.websocket_connect(f"/ws?token={app.state.ui_token}") as ws:
        ws.send_json({"type": "config.save", "config": patch})
        saved = None
        for _ in range(30):
            msg = ws.receive_json()
            if msg.get("type") == "config.saved":
                saved = msg
                break
        assert saved is not None
        assert "Saved successfully" in saved["message"]
    raw = json.loads(config_path.read_text(encoding="utf-8"))
    assert raw["app"]["base_currency"] == "GBP"
    assert raw["app"]["enable_test_events"] is True
    assert app.state.allow_test_events is True
