"""Test event injection and revenue pipeline."""
from __future__ import annotations

import time

from playwright.sync_api import Page, expect

from .ws_helpers import DashboardWs


def _ensure_active_goal(ws: DashboardWs) -> None:
    ws.create_goal(name="Revenue E2E", target_points=10_000)


def test_inject_twitch_bits_updates_progress(e2e_ws: DashboardWs) -> None:
    _ensure_active_goal(e2e_ws)
    e2e_ws.inject_test_event("twitch_bits", {"quantity": 500})
    progress = e2e_ws.wait_for_progress_points(1, timeout=30)
    assert float(progress.get("current_points", 0)) > 0


def test_inject_via_ui_session_table(
    e2e_ws: DashboardWs,
    dashboard_page: Page,
) -> None:
    _ensure_active_goal(e2e_ws)

    dashboard_page.locator("#test-toggle-btn").click()
    expect(dashboard_page.locator("#test-events-grid .test-card").first).to_be_visible(timeout=10_000)

    card = (
        dashboard_page.locator(".test-grid .test-card")
        .filter(has_text="Bits (Twitch)")
        .first
    )
    card.locator('input[name="quantity"]').fill("250")
    card.get_by_role("button", name="Send test").click()

    e2e_ws.wait_for_session_events(1, timeout=20)
    expect(dashboard_page.locator("#session-revenue-body tr")).not_to_have_count(0, timeout=20_000)


def test_delete_all_test_transactions(e2e_ws: DashboardWs) -> None:
    _ensure_active_goal(e2e_ws)
    e2e_ws.inject_test_event("twitch_bits", {"quantity": 100})
    e2e_ws.wait_for_session_events(1, timeout=20)

    deleted = e2e_ws.delete_all_test_events()
    assert deleted.get("count", 0) >= 1

    # The state broadcast with empty session_revenue arrives BEFORE the
    # `test_event.deleted` ack, so it has been buffered in `latest_session_revenue`.
    assert e2e_ws.latest_session_revenue() == []


def test_second_platform_event(e2e_ws: DashboardWs) -> None:
    _ensure_active_goal(e2e_ws)
    e2e_ws.inject_test_event("youtube_super_chat", {"amount": "5", "currency": "USD"})
    state = e2e_ws.wait_for_session_events(1, timeout=45)
    rows = state.get("session_revenue") or []
    # Session rows expose the human-friendly label (`Super Chat`) and platform
    # (`youtube`) — not the raw event_type id.
    assert any(
        r.get("platform") == "youtube" and r.get("type") == "Super Chat"
        for r in rows
    ), f"expected a youtube super_chat row, saw {rows!r}"


def test_invalidate_session_row(e2e_ws: DashboardWs) -> None:
    _ensure_active_goal(e2e_ws)
    e2e_ws.inject_test_event("twitch_bits", {"quantity": 200})
    e2e_ws.wait_for_session_events(1, timeout=45)
    before = e2e_ws.wait_for_progress_points(1, timeout=30)
    before_pts = float(before.get("current_points", 0))

    rows = e2e_ws.latest_session_revenue()
    assert rows, "expected at least one session revenue row"
    event_id = rows[-1]["id"]

    e2e_ws.invalidate_event(event_id)

    deadline = time.monotonic() + 30
    after_pts = before_pts
    while time.monotonic() < deadline:
        try:
            msg = e2e_ws.receive(timeout=max(0.1, deadline - time.monotonic()))
        except TimeoutError:
            break
        if msg.get("type") == "progress":
            after_pts = float(msg.get("current_points", 0))
            if after_pts < before_pts:
                break
        elif msg.get("type") == "state":
            after_pts = float((msg.get("progress") or {}).get("current_points", 0))
            if after_pts < before_pts:
                break
    assert after_pts < before_pts, (
        f"expected progress to decrease after invalidate (before={before_pts}, after={after_pts})"
    )
