"""Goals, progress, and bar appearance."""
from __future__ import annotations

from playwright.sync_api import Page, expect

from .conftest import E2EContext
from .ws_helpers import DashboardWs, OverlayWs


def test_goal_create_visible_in_dashboard_ui(
    e2e_ws: DashboardWs,
    dashboard_page: Page,
) -> None:
    state = e2e_ws.create_goal(name="E2E Goal", target_points=1000)
    goal_id = state.get("active_goal_id")
    assert goal_id, "expected a freshly created goal to be active"

    expect(dashboard_page.locator("#goal-name")).to_contain_text("E2E Goal", timeout=15_000)
    expect(dashboard_page.locator("#goal-points-text")).to_contain_text("pts")


def test_manual_points_change(e2e_ws: DashboardWs) -> None:
    e2e_ws.create_goal(name="Points Goal", target_points=500)
    state = e2e_ws.points_change(50, add=True)
    progress = state.get("progress") or {}
    assert float(progress.get("current_points", 0)) >= 50


def test_goal_delete_via_ui(
    e2e_ws: DashboardWs,
    dashboard_page: Page,
) -> None:
    state = e2e_ws.create_goal(name="Delete Me", target_points=100)
    goal_id = state["active_goal_id"]

    # Wait for the option to be available in the UI before interacting.
    dashboard_page.wait_for_function(
        "id => !!document.querySelector(`#goal-select option[value=\"${id}\"]`)",
        arg=goal_id,
        timeout=15_000,
    )
    dashboard_page.locator("#goal-select").select_option(value=goal_id)
    dashboard_page.once("dialog", lambda d: d.accept())
    dashboard_page.locator("#goal-delete-btn").click()

    e2e_ws.wait_for_state(
        timeout=20,
        predicate=lambda m: goal_id not in {g.get("id") for g in (m.get("goals") or [])},
    )


def test_bar_appearance_overlay_sync(
    e2e_context: E2EContext,
    e2e_ws: DashboardWs,
) -> None:
    e2e_ws.create_goal(name="Bar Goal", target_points=100)
    e2e_ws.save_bar_appearance({
        "fill_color": "#112233",
        "gradient_color": "#AABBCC",
        "use_gradient": True,
        "font_family": "Arial, Helvetica, sans-serif",
        "show_decimals": True,
    })

    overlay = OverlayWs(e2e_context.overlay_ws_url)
    try:
        msg = overlay.wait_for_state()
        appearance = msg.get("bar_appearance") or {}
        assert appearance.get("fill_color", "").upper() == "#112233"
        assert appearance.get("use_gradient") is True
    finally:
        overlay.close()
