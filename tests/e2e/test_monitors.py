"""Monitor connect / cancel flows.

These tests trigger real OAuth attempts but do not complete them — the goal is
to validate that the monitor lifecycle (idle -> authenticating/connecting ->
cancelled/idle) is wired correctly. They run primarily over WebSocket so the
dashboard page is not navigated mid-suite.
"""
from __future__ import annotations

import os

import pytest

from .ws_helpers import DashboardWs


_TRANSIENT = {"authenticating", "connecting", "active", "error"}
_TERMINAL = {"idle", "error", "active"}


def _has_env(*names: str) -> bool:
    return all(os.environ.get(name, "").strip() for name in names)


def test_twitch_connect_attempt_and_cancel(e2e_ws: DashboardWs) -> None:
    if not _has_env("TWITCH_CLIENT_ID"):
        pytest.skip("TWITCH_CLIENT_ID not set")

    state = e2e_ws.drain_initial_state()
    user = state.get("user_config") or {}
    e2e_ws.save_config({
        "app": {
            **(user.get("app") or {}),
            "enable_test_events": True,
            "enable_twitch": True,
        },
        "twitch": {"channel_name": "e2e_connect_test"},
        "streamlabs": user.get("streamlabs") or {},
    })

    e2e_ws.request_monitor_connect("twitch")
    status = e2e_ws.wait_for_monitor_status("twitch", tuple(_TRANSIENT), timeout=45)

    if status in ("active", "error"):
        e2e_ws.request_monitor_disconnect("twitch")
    else:
        e2e_ws.request_monitor_disconnect("twitch")
    e2e_ws.wait_for_monitor_status("twitch", tuple(_TERMINAL), timeout=20)


def test_youtube_connect_attempt(e2e_ws: DashboardWs) -> None:
    has_youtube = bool(
        os.environ.get("YOUTUBE_CLIENT_SECRETS_PATH", "").strip()
        or os.environ.get("YOUTUBE_OAUTH_CLIENT_JSON", "").strip()
    )
    if not has_youtube:
        pytest.skip("YouTube OAuth env not set")

    state = e2e_ws.drain_initial_state()
    user = state.get("user_config") or {}
    e2e_ws.save_config({
        "app": {
            **(user.get("app") or {}),
            "enable_test_events": True,
            "enable_youtube": True,
        },
        "twitch": user.get("twitch") or {"channel_name": "e2e_test_channel"},
        "streamlabs": user.get("streamlabs") or {},
    })

    e2e_ws.request_monitor_connect("youtube")
    e2e_ws.wait_for_monitor_status("youtube", tuple(_TRANSIENT), timeout=45)
    e2e_ws.request_monitor_disconnect("youtube")
    e2e_ws.wait_for_monitor_status("youtube", tuple(_TERMINAL), timeout=20)


def test_patreon_connect_attempt(e2e_ws: DashboardWs) -> None:
    if not _has_env("PATREON_CLIENT_ID"):
        pytest.skip("PATREON_CLIENT_ID not set")

    state = e2e_ws.drain_initial_state()
    user = state.get("user_config") or {}
    e2e_ws.save_config({
        "app": {
            **(user.get("app") or {}),
            "enable_test_events": True,
            "enable_patreon": True,
        },
        "twitch": user.get("twitch") or {"channel_name": "e2e_test_channel"},
        "streamlabs": user.get("streamlabs") or {},
    })

    e2e_ws.request_monitor_connect("patreon")
    e2e_ws.wait_for_monitor_status("patreon", tuple(_TRANSIENT), timeout=45)
    e2e_ws.request_monitor_disconnect("patreon")
    e2e_ws.wait_for_monitor_status("patreon", tuple(_TERMINAL), timeout=20)


def test_streamlabs_connect_with_token(e2e_ws: DashboardWs) -> None:
    token = os.environ.get("STREAMLABS_SOCKET_TOKEN", "").strip()
    if not token:
        pytest.skip("STREAMLABS_SOCKET_TOKEN not set")

    state = e2e_ws.drain_initial_state()
    user = state.get("user_config") or {}
    e2e_ws.save_config({
        "app": {
            **(user.get("app") or {}),
            "enable_test_events": True,
            "enable_streamlabs": True,
        },
        "twitch": user.get("twitch") or {"channel_name": "e2e_test_channel"},
        "streamlabs": {"socket_api_token": token},
    })

    e2e_ws.request_monitor_connect("streamlabs")
    e2e_ws.wait_for_monitor_status(
        "streamlabs", ("connecting", "active", "error", "idle"), timeout=30,
    )
    e2e_ws.request_monitor_disconnect("streamlabs")
