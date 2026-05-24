from unittest.mock import patch

from multistream_revenue_tracker import bundled_credentials
from multistream_revenue_tracker.secrets import (
    resolve_twitch_credentials,
    resolve_youtube_oauth_client_config,
)


def test_resolve_twitch_prefers_bundled(monkeypatch):
    monkeypatch.delenv("TWITCH_CLIENT_ID", raising=False)
    monkeypatch.delenv("TWITCH_CLIENT_SECRET", raising=False)
    with patch.object(bundled_credentials, "TWITCH_CLIENT_ID", "bundled-id"), patch.object(
        bundled_credentials, "TWITCH_CLIENT_SECRET", "bundled-secret"
    ):
        client_id, client_secret = resolve_twitch_credentials()
    assert client_id == "bundled-id"
    assert client_secret == "bundled-secret"


def test_resolve_youtube_bundled_config(monkeypatch):
    monkeypatch.delenv("YOUTUBE_OAUTH_CLIENT_JSON", raising=False)
    monkeypatch.delenv("YOUTUBE_CLIENT_SECRETS_PATH", raising=False)
    oauth = {"installed": {"client_id": "g", "client_secret": "s"}}
    with patch.object(bundled_credentials, "YOUTUBE_OAUTH_CLIENT_CONFIG", oauth):
        assert resolve_youtube_oauth_client_config() == oauth
