import json
from pathlib import Path

from multistream_revenue_tracker.config import get_data_dir
from multistream_revenue_tracker.services.runtime_cleanup import clean_transient_data, collect_transient_paths


def test_collect_transient_paths_includes_oauth_db_and_goals(tmp_path: Path):
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps({
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
            "patreon": {"campaign_id": ""},
        }),
        encoding="utf-8",
    )
    data_dir = get_data_dir(config_path, create=True)
    token = data_dir / "yt_token.json"
    token.write_text("{}", encoding="utf-8")
    db = data_dir / "revenue_events.db"
    db.write_bytes(b"")
    goals = data_dir / "goals"
    goals.mkdir()
    (goals / "active_goal.json").write_text("{}", encoding="utf-8")

    paths = collect_transient_paths(config_path)
    resolved = {p.resolve() for p in paths}
    assert token.resolve() in resolved
    assert db.resolve() in resolved
    assert goals.resolve() in resolved


def test_clean_transient_data_removes_config_and_tokens(tmp_path: Path):
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps({
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
            "patreon": {"campaign_id": ""},
        }),
        encoding="utf-8",
    )
    data_dir = get_data_dir(config_path, create=True)
    (data_dir / "patreon_token.json").write_text("{}", encoding="utf-8")
    (data_dir / "yt_token.json").write_text("{}", encoding="utf-8")

    removed = clean_transient_data(config_path)
    assert removed
    assert not config_path.exists()
    assert not (data_dir / "patreon_token.json").exists()
    assert not (data_dir / "yt_token.json").exists()
