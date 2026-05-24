"""Session revenue table UI."""
from __future__ import annotations

from playwright.sync_api import Page, expect

from .ws_helpers import DashboardWs


def test_session_revenue_table_after_inject(
    e2e_ws: DashboardWs,
    dashboard_page: Page,
) -> None:
    e2e_ws.create_goal(name="Session Table", target_points=5000)
    e2e_ws.inject_test_event("twitch_bits", {"quantity": 50})
    e2e_ws.wait_for_session_events(1, timeout=30)

    expect(dashboard_page.locator("#session-revenue-body tr")).not_to_have_count(0, timeout=20_000)
    row = dashboard_page.locator("#session-revenue-body tr").first
    expect(row).to_contain_text("twitch", ignore_case=True)
