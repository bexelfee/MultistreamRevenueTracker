"""Phase 1 security-hardening tests.

Each test exercises a release-blocker addressed in the refactor plan:
  - goal_id path traversal
  - font whitelist (CSS injection vector)
  - Streamlabs token masking
  - log scrubber gaps (Google ya29.*)
  - WebSocket session token / origin allowlist
  - WS message size cap and validation
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from multistream_revenue_tracker.appearance.bar_appearance import _normalize_font, DEFAULT_BAR_APPEARANCE
from multistream_revenue_tracker.bundled_credentials import (
    PATREON_CLIENT_ID,
    PATREON_CLIENT_SECRET,
    TWITCH_CLIENT_ID,
    TWITCH_CLIENT_SECRET,
    YOUTUBE_OAUTH_CLIENT_CONFIG,
)
from multistream_revenue_tracker.config_store import (
    STREAMLABS_TOKEN_MASK_PREFIX,
    clean_config_patch,
    is_masked_streamlabs_token,
    mask_streamlabs_token,
    normalized_user_config_for_ui,
)
from multistream_revenue_tracker.goals.goal_store import GoalStore
from multistream_revenue_tracker.log_scrubbing import scrub_text
from multistream_revenue_tracker.ui.app import create_app
from multistream_revenue_tracker.ui.routes import MAX_WS_MESSAGE_BYTES
from multistream_revenue_tracker.ui.ws_auth import attach_token_to_url, origin_allowed


# ---------------------------------------------------------------------------
# 1.1 Repository never ships filled OAuth credentials
# ---------------------------------------------------------------------------


def test_bundled_credentials_are_empty_in_repo() -> None:
    """Release builds inject these; the committed file must stay blank."""
    assert TWITCH_CLIENT_ID == ""
    assert TWITCH_CLIENT_SECRET == ""
    assert PATREON_CLIENT_ID == ""
    assert PATREON_CLIENT_SECRET == ""
    assert YOUTUBE_OAUTH_CLIENT_CONFIG is None


# ---------------------------------------------------------------------------
# 1.4 goal_id path traversal
# ---------------------------------------------------------------------------


def test_goal_store_rejects_path_traversal(tmp_path) -> None:
    sensitive = tmp_path / "config.json"
    sensitive.write_text("{}", encoding="utf-8")
    store = GoalStore(tmp_path / "goals")
    store.ensure_initialized()

    with pytest.raises(ValueError):
        store.delete_goal("../config")
    with pytest.raises(ValueError):
        store.set_active_goal_id("../../etc/passwd")
    assert store.get_goal("not-a-uuid") is None
    # Returning None on lookup must not have created the file either.
    assert sensitive.is_file()


def test_goal_store_accepts_valid_uuid(tmp_path) -> None:
    store = GoalStore(tmp_path / "goals")
    goal = store.create_goal("test", 10)
    assert store.get_goal(goal.id) is not None


# ---------------------------------------------------------------------------
# 1.5 Streamlabs token masking
# ---------------------------------------------------------------------------


def test_mask_streamlabs_token_shows_only_last_four() -> None:
    assert mask_streamlabs_token("abcdefghij12") == f"{STREAMLABS_TOKEN_MASK_PREFIX}ij12"
    assert mask_streamlabs_token("") == ""
    assert mask_streamlabs_token(None) == ""


def test_normalized_user_config_for_ui_masks_streamlabs_token() -> None:
    normalized = {
        "app": {},
        "twitch": {},
        "streamlabs": {"socket_api_token": "secrettoken1234"},
    }
    ui_payload = normalized_user_config_for_ui(normalized)
    assert ui_payload["streamlabs"]["socket_api_token"].startswith(STREAMLABS_TOKEN_MASK_PREFIX)
    assert "secrettoken1234" not in ui_payload["streamlabs"]["socket_api_token"]


def test_clean_config_patch_ignores_masked_streamlabs_token() -> None:
    masked = mask_streamlabs_token("realtoken1234")
    cleaned = clean_config_patch({"streamlabs": {"socket_api_token": masked}})
    assert "streamlabs" not in cleaned  # masked sentinel means "no change"
    assert is_masked_streamlabs_token(masked)


def test_clean_config_patch_accepts_new_token() -> None:
    cleaned = clean_config_patch({"streamlabs": {"socket_api_token": "freshtoken"}})
    assert cleaned["streamlabs"]["socket_api_token"] == "freshtoken"


# ---------------------------------------------------------------------------
# 1.7 Font whitelist (CSS-injection defense)
# ---------------------------------------------------------------------------


def test_font_whitelist_rejects_arbitrary_value() -> None:
    out = _normalize_font("evil; background: url(http://x)", DEFAULT_BAR_APPEARANCE["font_family"])
    assert out == DEFAULT_BAR_APPEARANCE["font_family"]


def test_font_whitelist_accepts_known_option() -> None:
    out = _normalize_font(
        "Arial, Helvetica, sans-serif", DEFAULT_BAR_APPEARANCE["font_family"],
    )
    assert out == "Arial, Helvetica, sans-serif"


# ---------------------------------------------------------------------------
# 1.9 Log scrubber covers Google OAuth tokens
# ---------------------------------------------------------------------------


def test_log_scrubber_redacts_google_access_token() -> None:
    payload = "got token ya29.A0AfH6SMBSomeFakeGoogleAccessToken1234567890 from refresh"
    scrubbed = scrub_text(payload)
    assert "ya29." not in scrubbed
    assert "[REDACTED]" in scrubbed


def test_log_scrubber_redacts_google_refresh_token() -> None:
    payload = "refresh=1//0gFakeGoogleRefreshTokenABCDEFGHIJKLMNOP"
    scrubbed = scrub_text(payload)
    assert "FakeGoogleRefreshTokenABCDEFGHIJKLMNOP" not in scrubbed


# ---------------------------------------------------------------------------
# 1.2/1.3 WebSocket session token + Origin allowlist
# ---------------------------------------------------------------------------


def test_create_app_generates_token_when_required() -> None:
    app = create_app(require_ws_token=True)
    token = app.state.ui_token
    assert isinstance(token, str)
    assert len(token) >= 32


def test_create_app_no_token_by_default() -> None:
    app = create_app()
    assert app.state.require_ws_token is False
    assert app.state.ui_token == ""


def test_ws_dashboard_accepts_without_token_when_disabled() -> None:
    app = create_app(require_ws_token=False)
    client = TestClient(app)
    with client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "ping"})
        for _ in range(5):
            msg = ws.receive_json()
            if msg.get("type") == "pong":
                break
        else:
            raise AssertionError("did not receive pong")


def test_index_html_embeds_ui_token() -> None:
    app = create_app(ui_token="testtoken123", require_ws_token=True)
    client = TestClient(app)
    response = client.get("/")
    assert response.status_code == 200
    assert 'name="mrt-ui-token"' in response.text
    assert "testtoken123" in response.text


def test_ws_dashboard_rejects_missing_token() -> None:
    app = create_app(ui_token="correct-token", require_ws_token=True)
    client = TestClient(app)
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/ws") as ws:
            ws.receive_json()


def test_ws_dashboard_rejects_wrong_token() -> None:
    app = create_app(ui_token="correct-token", require_ws_token=True)
    client = TestClient(app)
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/ws?token=bad") as ws:
            ws.receive_json()


def test_ws_dashboard_accepts_valid_token() -> None:
    app = create_app(ui_token="correct-token", require_ws_token=True)
    client = TestClient(app)
    with client.websocket_connect("/ws?token=correct-token") as ws:
        ws.send_json({"type": "ping"})
        for _ in range(5):
            msg = ws.receive_json()
            if msg.get("type") == "pong":
                break
        else:
            raise AssertionError("did not receive pong")


def test_origin_allowed_accepts_localhost_loopback() -> None:
    assert origin_allowed("http://127.0.0.1:8080", 8080)
    assert origin_allowed("http://localhost:8080", 8080)
    assert origin_allowed("null", 8080)  # OBS browser source
    assert not origin_allowed("http://evil.test:8080", 8080)
    assert not origin_allowed("http://127.0.0.1:9999", 8080)


def test_attach_token_to_url_appends_query() -> None:
    assert attach_token_to_url("http://x/overlay?w=400", "abc") == "http://x/overlay?w=400&token=abc"
    assert attach_token_to_url("http://x/overlay", "abc") == "http://x/overlay?token=abc"
    assert attach_token_to_url("http://x/overlay", "") == "http://x/overlay"


# ---------------------------------------------------------------------------
# 1.6 WebSocket validation: invalid JSON, oversize, non-object
# ---------------------------------------------------------------------------


def test_ws_message_size_cap_is_64kb() -> None:
    assert MAX_WS_MESSAGE_BYTES == 64 * 1024


def test_ws_rejects_invalid_json() -> None:
    app = create_app(ui_token="t", require_ws_token=True)
    client = TestClient(app)
    with client.websocket_connect("/ws?token=t") as ws:
        ws.send_text("not json")
        msg = None
        for _ in range(10):
            received = ws.receive_json()
            if received.get("type") == "error":
                msg = received
                break
        assert msg is not None
        assert "JSON" in msg["message"]


def test_ws_rejects_non_object_payload() -> None:
    app = create_app(ui_token="t", require_ws_token=True)
    client = TestClient(app)
    with client.websocket_connect("/ws?token=t") as ws:
        ws.send_text("[1, 2, 3]")
        msg = None
        for _ in range(10):
            received = ws.receive_json()
            if received.get("type") == "error":
                msg = received
                break
        assert msg is not None


def test_ws_rejects_unknown_effect_id() -> None:
    app = create_app(ui_token="t", require_ws_token=True)
    client = TestClient(app)
    with client.websocket_connect("/ws?token=t") as ws:
        ws.send_json({"type": "progress_effects.preview", "channel": "goal", "effect_id": "evil-fx"})
        msg = None
        for _ in range(10):
            received = ws.receive_json()
            if received.get("type") == "error":
                msg = received
                break
        assert msg is not None
        assert "effect_id" in msg["message"]


def test_ws_oversize_message_rejected() -> None:
    """Oversize frames are dropped without disconnecting the socket."""
    app = create_app(ui_token="t", require_ws_token=True)
    client = TestClient(app)
    big = "x" * (MAX_WS_MESSAGE_BYTES + 1024)
    with client.websocket_connect("/ws?token=t") as ws:
        ws.send_text(json.dumps({"type": "ping", "filler": big}))
        msg = None
        for _ in range(20):
            received = ws.receive_json()
            if received.get("type") == "error":
                msg = received
                break
        assert msg is not None
        assert "large" in msg["message"]
