"""Configuration tab and persistence (WebSocket-driven where possible)."""
from __future__ import annotations

import json
import os

from playwright.sync_api import Page, expect

from .conftest import E2EContext
from .ws_helpers import DashboardWs


def test_enable_test_events_via_ws(
    e2e_ws: DashboardWs,
    e2e_context: E2EContext,
    dashboard_page: Page,
) -> None:
    state = e2e_ws.drain_initial_state()
    user = state.get("user_config") or {}
    app = dict(user.get("app") or {})
    app["enable_test_events"] = True
    e2e_ws.save_config({
        "app": app,
        "twitch": user.get("twitch") or {"channel_name": "e2e_test_channel"},
        "streamlabs": user.get("streamlabs") or {},
    })

    raw = json.loads((e2e_context.workdir / "config.json").read_text(encoding="utf-8"))
    assert raw["app"]["enable_test_events"] is True

    dashboard_page.locator("#test-toggle-btn").click()
    expect(dashboard_page.locator("#test-delete-all-btn")).to_be_visible()


def test_base_currency_save_reflected_in_state(e2e_ws: DashboardWs) -> None:
    state = e2e_ws.drain_initial_state()
    user = state.get("user_config") or {}
    e2e_ws.save_config({
        "app": {
            **(user.get("app") or {}),
            "enable_test_events": True,
            "base_currency": "GBP",
        },
        "twitch": user.get("twitch") or {"channel_name": "e2e_test_channel"},
        "streamlabs": user.get("streamlabs") or {},
    })
    state = e2e_ws.wait_for_state(
        timeout=15,
        predicate=lambda m: (m.get("user_config") or {}).get("app", {}).get("base_currency") == "GBP",
    )
    assert state["user_config"]["app"]["base_currency"] == "GBP"


def test_configuration_tab_ui(dashboard_page: Page) -> None:
    dashboard_page.locator("button[data-tab='configuration']").click()
    expect(dashboard_page.locator("#cfg-enable-test-events")).to_be_visible()
    expect(dashboard_page.locator("#cfg-streamlabs-token")).to_be_visible()


def test_streamlabs_token_persisted_to_disk(
    e2e_context: E2EContext,
    e2e_ws: DashboardWs,
) -> None:
    """Optional integration-like check: requires STREAMLABS_SOCKET_TOKEN."""
    import pytest

    token = os.environ.get("STREAMLABS_SOCKET_TOKEN", "").strip()
    if not token:
        pytest.skip("STREAMLABS_SOCKET_TOKEN not set; live Streamlabs round-trip test skipped")

    state = e2e_ws.drain_initial_state()
    user = state.get("user_config") or {}
    e2e_ws.save_config({
        "app": {
            **(user.get("app") or {}),
            "enable_test_events": True,
            "ui_port": e2e_context.port,
        },
        "twitch": user.get("twitch") or {"channel_name": "e2e_test_channel"},
        "streamlabs": {"socket_api_token": token},
    })
    raw = json.loads((e2e_context.workdir / "config.json").read_text(encoding="utf-8"))
    assert raw["streamlabs"]["socket_api_token"] == token
