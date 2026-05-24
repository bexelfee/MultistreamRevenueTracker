import json
from unittest.mock import patch

from multistream_revenue_tracker import bundled_credentials
from multistream_revenue_tracker.config_store import (
    is_masked_streamlabs_token,
    mask_streamlabs_token,
    normalize_user_config,
    save_user_config,
    validate_config_patch,
)
from multistream_revenue_tracker.secrets import resolve_patreon_credentials
from multistream_revenue_tracker.ui.external_links import PATREON_CLIENT_REGISTER_HREF


def test_resolve_patreon_prefers_config_over_bundle(monkeypatch):
    monkeypatch.delenv("PATREON_CLIENT_ID", raising=False)
    monkeypatch.delenv("PATREON_CLIENT_SECRET", raising=False)
    with patch.object(bundled_credentials, "PATREON_CLIENT_ID", "bundled-id"), patch.object(
        bundled_credentials, "PATREON_CLIENT_SECRET", "bundled-secret"
    ):
        client_id, client_secret = resolve_patreon_credentials(
            {"patreon": {"client_id": "user-id", "client_secret": "user-secret"}},
        )
    assert client_id == "user-id"
    assert client_secret == "user-secret"


def test_resolve_patreon_falls_back_to_bundle(monkeypatch):
    monkeypatch.delenv("PATREON_CLIENT_ID", raising=False)
    monkeypatch.delenv("PATREON_CLIENT_SECRET", raising=False)
    with patch.object(bundled_credentials, "PATREON_CLIENT_ID", "bundled-id"), patch.object(
        bundled_credentials, "PATREON_CLIENT_SECRET", "bundled-secret"
    ):
        client_id, client_secret = resolve_patreon_credentials({"patreon": {}})
    assert client_id == "bundled-id"
    assert client_secret == "bundled-secret"


def test_clean_config_patch_patreon_secret_masked_sentinel():
    cleaned = validate_config_patch(
        {"patreon": {"client_id": "abc", "client_secret": mask_streamlabs_token("real-secret")}},
    )
    assert "patreon" not in cleaned or "client_secret" not in cleaned.get("patreon", {})


def test_save_user_config_persists_patreon_credentials(tmp_path):
    config_path = tmp_path / "config.json"
    save_user_config(
        config_path,
        {"patreon": {"client_id": "my-id", "client_secret": "my-secret"}},
    )
    normalized = normalize_user_config(json.loads(config_path.read_text(encoding="utf-8")))
    assert normalized["patreon"]["client_id"] == "my-id"
    assert normalized["patreon"]["client_secret"] == "my-secret"


def test_patreon_client_register_href_is_https():
    assert PATREON_CLIENT_REGISTER_HREF.startswith("https://")
    assert "patreon.com" in PATREON_CLIENT_REGISTER_HREF
