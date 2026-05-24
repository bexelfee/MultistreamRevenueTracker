"""Smoke tests: pages load and overlay WebSocket receives state."""
from __future__ import annotations

from playwright.sync_api import Page, expect

from .conftest import E2EContext
from .ws_helpers import OverlayWs


def test_dashboard_loads(dashboard_page: Page) -> None:
    expect(dashboard_page.locator("#tab-dashboard")).to_be_visible()
    expect(dashboard_page.locator("#restart-btn")).to_be_visible()
    expect(dashboard_page.locator("#shutdown-btn")).to_be_visible()


def test_configuration_tab(dashboard_page: Page) -> None:
    dashboard_page.locator("button[data-tab='configuration']").click()
    expect(dashboard_page.locator("#tab-configuration")).to_be_visible()
    expect(dashboard_page.locator("#cfg-enable-test-events")).to_be_visible()


def test_overlay_page_loads(scratch_page: Page, base_url: str) -> None:
    scratch_page.goto(base_url + "/overlay?w=800&h=80")
    expect(scratch_page.locator(".bar-track")).to_be_visible()


def test_overlay_websocket_state(e2e_context: E2EContext) -> None:
    overlay = OverlayWs(e2e_context.overlay_ws_url)
    try:
        state = overlay.wait_for_state()
        assert state.get("type") == "state"
        assert "progress" in state
    finally:
        overlay.close()
