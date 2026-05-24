import json

import pytest

from multistream_revenue_tracker.secrets import (
    resolve_twitch_credentials,
    resolve_youtube_oauth_client_config,
)


def test_resolve_twitch_from_env(monkeypatch):
    monkeypatch.setenv("TWITCH_CLIENT_ID", "from-env")
    monkeypatch.setenv("TWITCH_CLIENT_SECRET", "sec")
    client_id, client_secret = resolve_twitch_credentials()
    assert client_id == "from-env"
    assert client_secret == "sec"


def test_resolve_youtube_from_json_env(monkeypatch):
    oauth = {"installed": {"client_id": "g", "client_secret": "s"}}
    monkeypatch.setenv("YOUTUBE_OAUTH_CLIENT_JSON", json.dumps(oauth))
    assert resolve_youtube_oauth_client_config() == oauth


def test_resolve_youtube_from_secrets_path_env(monkeypatch, tmp_path):
    path = tmp_path / "google.json"
    oauth = {"installed": {"client_id": "g", "client_secret": "s"}}
    path.write_text(json.dumps(oauth), encoding="utf-8")
    monkeypatch.setenv("YOUTUBE_CLIENT_SECRETS_PATH", str(path))
    assert resolve_youtube_oauth_client_config() == oauth


def test_resolve_youtube_missing_path_raises(monkeypatch):
    monkeypatch.setenv("YOUTUBE_CLIENT_SECRETS_PATH", "/nonexistent/google.json")
    with pytest.raises(FileNotFoundError):
        resolve_youtube_oauth_client_config()
