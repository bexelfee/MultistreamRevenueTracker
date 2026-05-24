"""Point conversion rules save and scoring."""
from __future__ import annotations

from playwright.sync_api import Page, expect

from .ws_helpers import DashboardWs


def test_point_rules_save_and_scoring(
    e2e_ws: DashboardWs,
    dashboard_page: Page,
) -> None:
    e2e_ws.create_goal(name="Rules Goal", target_points=50_000)

    # Edit the rule via the UI; persist via the rules-save button.
    rule_card = dashboard_page.locator('.rule-card[data-event-type="twitch_bits"]')
    expect(rule_card).to_be_visible(timeout=15_000)
    rule_card.locator('input[name="points_per_unit"]').fill("2")
    dashboard_page.locator("#rules-save-btn").click()
    expect(dashboard_page.locator("#rules-save-btn")).to_be_disabled(timeout=10_000)

    # Capture the baseline progress AFTER the save round-trip is reflected in state.
    baseline = e2e_ws.wait_for_state(
        timeout=15,
        predicate=lambda m: bool(m.get("point_rules")),
    )
    before_pts = float((baseline.get("progress") or {}).get("current_points", 0))

    e2e_ws.inject_test_event("twitch_bits", {"quantity": 100})
    e2e_ws.wait_for_progress_points(before_pts + 150, timeout=30)
