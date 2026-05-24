"""E2E fixtures: spawn app, persistent dashboard page, per-test helpers.

Reliability constraints (read carefully before changing fixtures):

1. The dashboard JS sends `app.shutdown.request` on `pagehide`. Closing or
   navigating away from `/` therefore terminates the app process. The session
   keeps ONE Playwright page on `/` (`dashboard_page`) for the whole run.
2. The server shuts down when the LAST dashboard WebSocket disconnects. The
   `dashboard_page` keepalive WebSocket prevents this, so per-test helper
   WebSockets (`e2e_ws`) can open and close freely.
3. Tests must be order-independent. The autouse `_reset_state` fixture deletes
   any goals and test revenue between tests so each starts from a clean slate.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path

import pytest
from playwright.sync_api import BrowserContext, Page

from .ws_helpers import DashboardWs

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DIST_DIR = REPO_ROOT / "dist" / "MultistreamRevenueTracker"
BUILD_SCRIPT = REPO_ROOT / "scripts" / "build_release.ps1"
RUN_APP = Path(__file__).resolve().parent / "run_app.py"


# ---------------------------------------------------------------------------
# Marker auto-application
# ---------------------------------------------------------------------------


def pytest_collection_modifyitems(config, items):
    """
    Tag every E2E test with `e2e`; restart/shutdown tests with their own markers.

    Destructive lifecycle tests (`e2e_restart`/`e2e_shutdown`) are auto-deselected
    unless the user explicitly opts in with `-m e2e_restart`, `-m e2e_shutdown`,
    or selects them by path. They terminate or churn the shared app process and
    will break any test that runs after them in the same session.
    """
    raw_markexpr = (config.getoption("-m") or "").lower()
    explicit_lifecycle = (
        "e2e_restart" in raw_markexpr
        or "e2e_shutdown" in raw_markexpr
    )

    deselected: list = []
    keep: list = []
    for item in items:
        path = str(item.path).replace("\\", "/")
        if "/tests/e2e/" in path:
            item.add_marker(pytest.mark.e2e)
            if "test_restart" in item.name:
                item.add_marker(pytest.mark.e2e_restart)
            if "test_shutdown" in item.name:
                item.add_marker(pytest.mark.e2e_shutdown)

        is_lifecycle = bool(
            item.get_closest_marker("e2e_restart")
            or item.get_closest_marker("e2e_shutdown")
        )
        if is_lifecycle and not explicit_lifecycle:
            deselected.append(item)
        else:
            keep.append(item)

    if deselected:
        config.hook.pytest_deselected(items=deselected)
        items[:] = keep


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _env_flag(name: str, default: str = "0") -> bool:
    return os.environ.get(name, default).strip().lower() in ("1", "true", "yes")


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    return int(raw) if raw else default


def _seed_config(port: int) -> dict:
    return {
        "app": {
            "log_chat_messages_for_testing": False,
            "base_currency": "USD",
            "enable_test_events": True,
            "ui_port": port,
            "twitch_sub_resub_dedupe_seconds": 300,
            "bar_fill_color": "#FFA8BC",
            "bar_gradient_color": "#22C55E",
            "bar_use_gradient": False,
            "bar_font_family": "system-ui, Segoe UI, sans-serif",
            "bar_show_decimals": False,
        },
        "twitch": {"channel_name": "e2e_test_channel"},
        "patreon": {},
        "streamlabs": {"socket_api_token": ""},
    }


def _wait_for_http(url: str, *, timeout: float = 90.0) -> None:
    deadline = time.monotonic() + timeout
    last: Exception | None = None
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as resp:
                if resp.status == 200:
                    return
        except Exception as exc:
            last = exc
        time.sleep(0.5)
    raise RuntimeError(f"server not ready at {url}: {last}")


def _run_build() -> None:
    if sys.platform != "win32":
        raise RuntimeError("E2E_BUILD=1 requires Windows + scripts/build_release.ps1")
    subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(BUILD_SCRIPT)],
        cwd=REPO_ROOT,
        check=True,
    )


def _copy_dist_to(workdir: Path, dist_dir: Path) -> None:
    for item in dist_dir.iterdir():
        dest = workdir / item.name
        if item.is_dir():
            if dest.exists():
                shutil.rmtree(dest)
            shutil.copytree(item, dest)
        else:
            shutil.copy2(item, dest)


# ---------------------------------------------------------------------------
# Session: app process
# ---------------------------------------------------------------------------


@dataclass
class E2EContext:
    base_url: str
    ws_url: str
    overlay_ws_url: str
    workdir: Path
    port: int
    process: subprocess.Popen
    target: str

    def is_alive(self) -> bool:
        return self.process.poll() is None

    def shutdown(self) -> None:
        if not self.is_alive():
            return
        try:
            ws = DashboardWs(self.ws_url, timeout=10)
            ws.request_shutdown()
            ws.close()
        except Exception:
            pass
        try:
            self.process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait(timeout=5)


@pytest.fixture(scope="session")
def e2e_context() -> E2EContext:
    if _env_flag("E2E_BUILD"):
        _run_build()

    explicit_target = os.environ.get("E2E_TARGET", "").strip().lower()
    if explicit_target:
        target = explicit_target
    elif DEFAULT_DIST_DIR.is_dir():
        target = "dist"
    else:
        target = "source"

    if target == "dist" and not DEFAULT_DIST_DIR.is_dir():
        raise FileNotFoundError(
            f"Release build missing at {DEFAULT_DIST_DIR}. "
            "Run scripts/build_release.ps1, set E2E_BUILD=1, or use E2E_TARGET=source."
        )
    port = _env_int("E2E_PORT", 19080)

    user_workdir = os.environ.get("E2E_WORKDIR", "").strip()
    if user_workdir:
        workdir = Path(user_workdir).resolve()
        workdir.mkdir(parents=True, exist_ok=True)
    else:
        prefix = "mrt_e2e_dist_" if target == "dist" else "mrt_e2e_src_"
        workdir = Path(tempfile.mkdtemp(prefix=prefix))

    if target == "dist":
        if not (workdir / "MultistreamRevenueTracker.exe").is_file():
            _copy_dist_to(workdir, DEFAULT_DIST_DIR)
        cmd = [str(workdir / "MultistreamRevenueTracker.exe")]
        cwd = str(workdir)
    else:
        cmd = [sys.executable, str(RUN_APP), str(workdir / "config.json")]
        cwd = str(REPO_ROOT)

    config_path = workdir / "config.json"
    config_path.write_text(json.dumps(_seed_config(port), indent=2) + "\n", encoding="utf-8")

    creationflags = subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0
    child_env = os.environ.copy()
    # Suppress the auto-opened browser tab so the developer doesn't accidentally
    # interact with the test's app instance.
    child_env["MRT_NO_BROWSER"] = "1"
    log_path = workdir / "app.log"
    log_handle = log_path.open("w", encoding="utf-8")
    process = subprocess.Popen(
        cmd,
        cwd=cwd,
        env=child_env,
        stdout=log_handle,
        stderr=subprocess.STDOUT,
        creationflags=creationflags,
    )

    base_url = f"http://127.0.0.1:{port}"
    try:
        _wait_for_http(f"{base_url}/", timeout=90)
    except Exception:
        process.kill()
        process.wait(timeout=5)
        raise

    ctx = E2EContext(
        base_url=base_url,
        ws_url=f"ws://127.0.0.1:{port}/ws",
        overlay_ws_url=f"ws://127.0.0.1:{port}/ws/overlay",
        workdir=workdir,
        port=port,
        process=process,
        target=target,
    )
    yield ctx
    ctx.shutdown()
    if not user_workdir:
        shutil.rmtree(workdir, ignore_errors=True)


@pytest.fixture(scope="session")
def base_url(e2e_context: E2EContext) -> str:
    return e2e_context.base_url


# ---------------------------------------------------------------------------
# Session: Playwright + persistent dashboard page (KEEPALIVE)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def browser_type_launch_args() -> dict:
    return {"headless": not _env_flag("E2E_HEADED")}


@pytest.fixture(scope="session")
def browser_context_args(base_url: str) -> dict:
    return {"base_url": base_url}


@pytest.fixture(scope="session")
def e2e_browser_context(browser, browser_context_args) -> BrowserContext:  # noqa: ANN001
    """One BrowserContext shared across the session."""
    ctx = browser.new_context(**browser_context_args)
    yield ctx
    try:
        ctx.close()
    except Exception:
        pass


@pytest.fixture(scope="session")
def dashboard_page(e2e_browser_context: BrowserContext, e2e_context: E2EContext) -> Page:
    """
    Persistent dashboard tab. Stays on `/` for the entire test session.

    Tests MUST NOT call `dashboard_page.close()` or `dashboard_page.goto(...)` to
    a non-`/` URL — pagehide on `/` terminates the app process.
    """
    page = e2e_browser_context.new_page()
    page.set_default_timeout(_env_int("E2E_TIMEOUT_MS", 60_000))
    page.goto(e2e_context.base_url + "/", wait_until="domcontentloaded")
    page.wait_for_selector("#tab-dashboard", state="visible", timeout=30_000)
    yield page
    try:
        page.close()
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Function-scoped helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def scratch_page(e2e_browser_context: BrowserContext) -> Page:
    """Fresh page for non-dashboard URLs (e.g. /overlay). Safe to close."""
    page = e2e_browser_context.new_page()
    page.set_default_timeout(_env_int("E2E_TIMEOUT_MS", 60_000))
    yield page
    try:
        page.close()
    except Exception:
        pass


@pytest.fixture
def e2e_ws(e2e_context: E2EContext, dashboard_page: Page) -> DashboardWs:  # noqa: ARG001
    """Fresh helper WebSocket per test; safe because dashboard_page keeps count >= 1."""
    ws = DashboardWs(e2e_context.ws_url, timeout=30)
    try:
        ws.drain_initial_state()
        yield ws
    finally:
        try:
            ws.close()
        except Exception:
            pass


@pytest.fixture(autouse=True)
def _reset_state(request, e2e_context: E2EContext, dashboard_page: Page) -> None:
    """
    Reset DB-backed and UI state between tests so order doesn't matter.

    Skipped for tests that opt out via the `no_state_reset` mark, and for
    lifecycle tests (`e2e_restart` / `e2e_shutdown`) which manage their own
    state.
    """
    if (
        "no_state_reset" in request.keywords
        or "e2e_restart" in request.keywords
        or "e2e_shutdown" in request.keywords
    ):
        yield
        return

    ws = DashboardWs(e2e_context.ws_url, timeout=15)
    try:
        state = ws.drain_initial_state()
        for goal in list(state.get("goals") or []):
            try:
                ws.delete_goal(goal["id"])
            except Exception:
                pass
        if state.get("allow_test_events"):
            try:
                ws.delete_all_test_events()
            except Exception:
                pass
    finally:
        try:
            ws.close()
        except Exception:
            pass

    try:
        dashboard_page.evaluate(
            """
            () => {
              const dashTab = document.querySelector('button[data-tab="dashboard"]');
              const dashPanel = document.getElementById('tab-dashboard');
              if (dashTab && dashPanel && !dashPanel.classList.contains('active')) {
                dashTab.click();
              }
              const testPanel = document.getElementById('test-panel');
              if (testPanel && !testPanel.classList.contains('collapsed')) {
                document.getElementById('test-toggle-btn').click();
              }
              const logPanel = document.getElementById('log-panel');
              if (logPanel && !logPanel.classList.contains('collapsed')) {
                document.getElementById('log-toggle-btn').click();
              }
            }
            """
        )
    except Exception:
        pass
    yield
