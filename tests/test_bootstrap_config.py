import json
from pathlib import Path

from multistream_revenue_tracker.config import load_app_config, load_bootstrap_config
from multistream_revenue_tracker.config_store import config_exists


def test_config_exists_false_when_missing(tmp_path):
    assert not config_exists(tmp_path / "config.json")


def test_load_bootstrap_config_without_file(tmp_path):
    config_path = tmp_path / "config.json"
    cfg = load_bootstrap_config(config_path)
    assert cfg.app.ui_port == 8080
    assert cfg.app.database_path.parent.name == "data"


def test_bootstrap_resolves_developer_credentials_from_env(monkeypatch, tmp_path):
    monkeypatch.setenv("TWITCH_CLIENT_ID", "tw-id")
    monkeypatch.setenv("TWITCH_CLIENT_SECRET", "tw-secret")
    monkeypatch.setenv("PATREON_CLIENT_ID", "pa-id")
    monkeypatch.setenv("PATREON_CLIENT_SECRET", "pa-secret")
    config_path = tmp_path / "config.json"
    cfg = load_bootstrap_config(config_path)
    assert cfg.twitch.client_id == "tw-id"
    assert cfg.twitch.client_secret == "tw-secret"
    assert cfg.patreon.client_id == "pa-id"
    assert cfg.patreon.client_secret == "pa-secret"


def test_load_app_config_uses_bootstrap_when_missing(monkeypatch, tmp_path):
    monkeypatch.setenv("TWITCH_CLIENT_ID", "x")
    monkeypatch.setenv("TWITCH_CLIENT_SECRET", "y")
    config_path = tmp_path / "config.json"
    cfg = load_app_config(config_path)
    assert cfg.twitch.client_id == "x"
