"""App restart and shutdown.

These tests are deliberately destructive:

* `test_restart_reloads_dashboard` performs an in-process restart. The session
  app process stays alive, but every WebSocket is briefly torn down and the
  dashboard JS reconnects. Marker: `e2e_restart`.
* `test_shutdown_button_terminates_app` ends the session app. No tests can run
  after it on the same session. Marker: `e2e_shutdown`. Run alone or last.

Both are excluded from the default `pytest -m e2e` run via `scripts/run_e2e.ps1`.
"""
from __future__ import annotations

import pytest
from playwright.sync_api import Page, expect

from .conftest import E2EContext


@pytest.mark.e2e_restart
def test_restart_reloads_dashboard(
    dashboard_page: Page,
    e2e_context: E2EContext,
) -> None:
    expect(dashboard_page.locator("#tab-dashboard")).to_be_visible()

    dashboard_page.locator("#restart-btn").click()

    # The dashboard JS shows the #restart-loading overlay while the in-process
    # restart happens. Once the new state arrives over the reconnected WS the
    # overlay is hidden and the restart button is re-enabled.
    dashboard_page.wait_for_function(
        "() => document.getElementById('restart-loading')?.hidden === true "
        "&& !document.getElementById('restart-btn').disabled",
        timeout=60_000,
    )
    assert e2e_context.is_alive(), "app process must survive an in-process restart"
    expect(dashboard_page.locator("#tab-dashboard")).to_be_visible(timeout=10_000)


@pytest.mark.e2e_shutdown
def test_shutdown_button_terminates_app(
    dashboard_page: Page,
    e2e_context: E2EContext,
) -> None:
    """Stops the session app. Run alone or last (`pytest -m e2e_shutdown`)."""
    dashboard_page.once("dialog", lambda d: d.accept())
    dashboard_page.locator("#shutdown-btn").click()
    e2e_context.process.wait(timeout=30)
    assert e2e_context.process.returncode is not None
