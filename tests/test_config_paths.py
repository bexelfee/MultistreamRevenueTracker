import json
from pathlib import Path

from multistream_revenue_tracker.config import get_data_dir, load_config, resolve_runtime_path


def test_get_data_dir_creates_directory(tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text("{}", encoding="utf-8")
    data_dir = get_data_dir(config_path)
    assert data_dir == tmp_path / "data"
    assert data_dir.is_dir()


def test_resolve_runtime_path_uses_data_dir_for_new_install(tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps({"app": {}, "twitch": {}, "patreon": {}}), encoding="utf-8")
    db_path = resolve_runtime_path(config_path, "revenue_events.db")
    assert db_path == tmp_path / "data" / "revenue_events.db"


def test_resolve_runtime_path_legacy_root_fallback(tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text("{}", encoding="utf-8")
    legacy_db = tmp_path / "revenue_events.db"
    legacy_db.write_text("", encoding="utf-8")
    assert resolve_runtime_path(config_path, "revenue_events.db") == legacy_db


def test_load_config_slim_schema(tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "app": {
                    "enable_twitch": False,
                    "enable_youtube": False,
                    "enable_patreon": False,
                    "base_currency": "USD",
                    "enable_test_events": False,
                    "ui_port": 9090,
                },
                "twitch": {"channel_name": ""},
                "patreon": {"campaign_id": ""},
            }
        ),
        encoding="utf-8",
    )
    cfg = load_config(config_path)
    assert cfg.app.base_currency == "USD"
    assert cfg.app.ui_port == 9090
    assert cfg.app.enable_test_events is False
    assert cfg.app.database_path.parent.name == "data"
