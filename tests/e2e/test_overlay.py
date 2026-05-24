"""OBS overlay page and progress sync."""
from __future__ import annotations

from playwright.sync_api import Page, expect

from .conftest import E2EContext
from .ws_helpers import DashboardWs, OverlayWs


def test_overlay_progress_after_inject(
    e2e_context: E2EContext,
    e2e_ws: DashboardWs,
    scratch_page: Page,
    base_url: str,
) -> None:
    e2e_ws.create_goal(name="Overlay Goal", target_points=5000)
    e2e_ws.inject_test_event("twitch_bits", {"quantity": 1000})
    e2e_ws.wait_for_progress_points(1, timeout=30)

    scratch_page.goto(base_url + "/overlay?w=800&h=80&name=1")
    expect(scratch_page.locator("#goal-points-text")).not_to_contain_text(
        "0 / 0", timeout=15_000,
    )

    overlay = OverlayWs(e2e_context.overlay_ws_url)
    try:
        state = overlay.wait_for_state()
        pts = float((state.get("progress") or {}).get("current_points", 0))
        assert pts > 0
    finally:
        overlay.close()
