"""Synchronous WebSocket helpers for dashboard E2E tests.

Each `DashboardWs` is short-lived (one per test). The persistent dashboard
keepalive is the Playwright `dashboard_page` in `conftest.py`, so closing a
helper WS does not trigger app shutdown.
"""
from __future__ import annotations

import json
import time
from typing import Any, Callable

from websockets.sync.client import connect


class DashboardWs:
    """Short-lived synchronous WebSocket client for the `/ws` dashboard route."""

    def __init__(self, ws_url: str, *, timeout: float = 30.0) -> None:
        self._url = ws_url
        self._timeout = timeout
        self._conn = connect(ws_url, open_timeout=timeout, close_timeout=5)
        # Most-recently-seen state, refreshed by every receive that returns a
        # `state` message. Lets `latest_state()` succeed even if the next state
        # broadcast is consumed by an intervening `wait_for(...)` call.
        self._last_state: dict[str, Any] | None = None
        self._last_session_revenue: list[dict[str, Any]] | None = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def close(self) -> None:
        try:
            self._conn.close()
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Low-level send/receive
    # ------------------------------------------------------------------

    def send(self, message: dict[str, Any]) -> None:
        self._conn.send(json.dumps(message))

    def receive(self, *, timeout: float | None = None) -> dict[str, Any]:
        deadline = time.monotonic() + (timeout if timeout is not None else self._timeout)
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("no WebSocket message within timeout")
            raw = self._conn.recv(timeout=remaining)
            data = json.loads(raw)
            if not isinstance(data, dict):
                continue
            if data.get("type") == "state":
                self._last_state = data
                self._last_session_revenue = list(data.get("session_revenue") or [])
            elif data.get("type") == "session_revenue":
                self._last_session_revenue = list(data.get("events") or [])
            return data

    def wait_for(
        self,
        msg_type: str,
        *,
        timeout: float | None = None,
        predicate: Callable[[dict[str, Any]], bool] | None = None,
    ) -> dict[str, Any]:
        deadline = time.monotonic() + (timeout if timeout is not None else self._timeout)
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(f"timed out waiting for {msg_type!r}")
            msg = self.receive(timeout=remaining)
            if msg.get("type") != msg_type:
                continue
            if predicate is not None and not predicate(msg):
                continue
            return msg

    def wait_for_state(
        self,
        *,
        timeout: float | None = None,
        predicate: Callable[[dict[str, Any]], bool] | None = None,
    ) -> dict[str, Any]:
        """
        Wait for a `state` message matching `predicate` (or any state if no predicate).

        If `predicate` is provided and the most-recently-buffered state already
        matches, return it immediately without waiting. This avoids races where
        the relevant state arrived between two waits and has been "consumed" by
        a different `wait_for(...)` call but cached in `_last_state`.
        """
        if predicate is not None and self._last_state is not None:
            try:
                if predicate(self._last_state):
                    return self._last_state
            except Exception:
                pass
        return self.wait_for("state", timeout=timeout, predicate=predicate)

    def drain_initial_state(self, *, timeout: float = 30.0) -> dict[str, Any]:
        """Return the cached most-recent state, or block for a fresh one."""
        if self._last_state is not None:
            return self.latest_state()
        return self.wait_for("state", timeout=timeout)

    def latest_state(self) -> dict[str, Any]:
        """Return the most-recently-observed `state` message (cached during `receive`)."""
        if self._last_state is None:
            raise RuntimeError("no state observed yet — call drain_initial_state() first")
        if self._last_session_revenue is not None:
            self._last_state["session_revenue"] = list(self._last_session_revenue)
        return self._last_state

    def latest_session_revenue(self) -> list[dict[str, Any]]:
        """Return the most-recently-observed session revenue list."""
        return list(self._last_session_revenue or [])

    # ------------------------------------------------------------------
    # App control
    # ------------------------------------------------------------------

    def request_shutdown(self) -> None:
        self.send({"type": "app.shutdown.request"})
        try:
            self.wait_for("app.shutting_down", timeout=10)
        except TimeoutError:
            pass

    def request_restart(self) -> None:
        self.send({"type": "app.restart.request"})
        try:
            self.wait_for("app.restarting", timeout=10)
        except TimeoutError:
            pass

    # ------------------------------------------------------------------
    # Config / appearance
    # ------------------------------------------------------------------

    def save_config(self, config: dict[str, Any]) -> dict[str, Any]:
        self.send({"type": "config.save", "config": config})
        return self.wait_for("config.saved", timeout=30)

    def save_bar_appearance(self, appearance: dict[str, Any]) -> dict[str, Any]:
        self.send({"type": "bar_appearance.save", "bar_appearance": appearance})
        return self.wait_for("bar_appearance.saved", timeout=15)

    def save_point_rules(self, rules: dict[str, Any]) -> dict[str, Any]:
        self.send({"type": "point_rules.save", "rules": rules})
        return self.wait_for_state(
            timeout=15,
            predicate=lambda m: bool(m.get("point_rules")),
        )

    # ------------------------------------------------------------------
    # Goals
    # ------------------------------------------------------------------

    def create_goal(self, *, name: str, target_points: int, select: bool = True) -> dict[str, Any]:
        self.send({
            "type": "goal.create",
            "name": name,
            "target_points": target_points,
            "select": select,
        })
        return self.wait_for_state(
            predicate=lambda m: any(g.get("name") == name for g in (m.get("goals") or [])),
        )

    def select_goal(self, goal_id: str) -> dict[str, Any]:
        self.send({"type": "goal.select", "goal_id": goal_id})
        return self.wait_for_state(
            predicate=lambda m: m.get("active_goal_id") == goal_id,
        )

    def delete_goal(self, goal_id: str) -> dict[str, Any]:
        self.send({"type": "goal.delete", "goal_id": goal_id})
        return self.wait_for_state(
            predicate=lambda m: goal_id not in {g.get("id") for g in (m.get("goals") or [])},
        )

    def points_change(self, amount: int, *, add: bool = True) -> dict[str, Any]:
        self.send({"type": "goal.points_change", "amount": int(amount), "add": add})
        return self.wait_for_state()

    # ------------------------------------------------------------------
    # Test events / revenue
    # ------------------------------------------------------------------

    def inject_test_event(
        self,
        event_type: str,
        overrides: dict[str, Any] | None = None,
    ) -> None:
        payload: dict[str, Any] = {"type": "test_event.inject", "event_type": event_type}
        if overrides:
            payload["overrides"] = overrides
        self.send(payload)

    def delete_all_test_events(self) -> dict[str, Any]:
        """
        Delete all test events. Returns the `test_event.deleted` ack.

        The server may also broadcast an updated state with empty session_revenue
        before the ack is sent; tests that need to assert that state should call
        `wait_for_state` immediately afterwards (or use `progress.refresh` to
        force a fresh state).
        """
        self.send({"type": "test_event.delete_all"})
        return self.wait_for("test_event.deleted", timeout=15)

    def invalidate_event(self, event_id: int) -> dict[str, Any]:
        """Mark a session revenue row as invalid; wait for `is_valid=False` to land."""
        self.send({"type": "revenue_event.invalidate", "event_id": int(event_id)})
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            for row in self.latest_session_revenue():
                if row.get("id") == event_id and row.get("is_valid") is False:
                    return self.latest_state()
            try:
                self.receive(timeout=max(0.1, deadline - time.monotonic()))
            except TimeoutError:
                break
        raise TimeoutError(f"event {event_id} did not become invalid within 30s")

    def wait_for_session_events(
        self,
        min_count: int = 1,
        *,
        timeout: float = 15.0,
    ) -> dict[str, Any]:
        """
        Wait for the dashboard to report at least `min_count` session revenue rows.

        Test event injection emits `session_revenue` and `progress` messages — NOT
        a fresh `state` — so we accept either signal and re-fetch the full state
        with `progress.refresh` if the row count first appears in a
        `session_revenue` event.
        """
        deadline = time.monotonic() + timeout
        events: list[dict[str, Any]] = []
        last_state: dict[str, Any] | None = None
        while time.monotonic() < deadline:
            remaining = max(0.05, deadline - time.monotonic())
            try:
                msg = self.receive(timeout=remaining)
            except TimeoutError:
                break
            if msg.get("type") == "state":
                last_state = msg
                events = list(msg.get("session_revenue") or [])
            elif msg.get("type") == "session_revenue":
                events = list(msg.get("events") or [])
            else:
                continue
            if len(events) >= min_count:
                if last_state is not None:
                    last_state["session_revenue"] = events
                    return last_state
                return {"type": "state", "session_revenue": events, "progress": {}}
        raise TimeoutError(f"timed out waiting for {min_count} session revenue rows")

    def wait_for_progress_points(
        self,
        min_points: float,
        *,
        timeout: float = 30.0,
    ) -> dict[str, Any]:
        """Wait for goal progress to reach `min_points` via state or progress messages."""
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(f"progress did not reach {min_points} points")
            msg = self.receive(timeout=remaining)
            if msg.get("type") == "state":
                prog = msg.get("progress") or {}
                if float(prog.get("current_points", 0)) >= min_points:
                    return prog
            elif msg.get("type") == "progress":
                if float(msg.get("current_points", 0)) >= min_points:
                    return msg

    # ------------------------------------------------------------------
    # Monitors
    # ------------------------------------------------------------------

    def request_monitor_connect(self, monitor_id: str) -> None:
        self.send({"type": "monitor.connect.request", "monitor_id": monitor_id})

    def request_monitor_disconnect(self, monitor_id: str) -> None:
        self.send({"type": "monitor.disconnect.request", "monitor_id": monitor_id})

    def get_monitor_status(
        self,
        monitor_id: str,
        *,
        state: dict[str, Any] | None = None,
    ) -> str:
        if state is None:
            state = self.wait_for_state(timeout=5)
        for row in (state.get("monitors") or []):
            if row.get("id") == monitor_id:
                return str(row.get("status") or "idle")
        return "idle"

    def wait_for_monitor_status(
        self,
        monitor_id: str,
        statuses: tuple[str, ...],
        *,
        timeout: float = 30.0,
    ) -> str:
        def matcher(msg: dict[str, Any]) -> bool:
            for row in (msg.get("monitors") or []):
                if row.get("id") == monitor_id and str(row.get("status") or "") in statuses:
                    return True
            return False

        state = self.wait_for_state(timeout=timeout, predicate=matcher)
        return self.get_monitor_status(monitor_id, state=state)


class OverlayWs:
    """Synchronous client for the `/ws/overlay` read-only stream."""

    def __init__(self, ws_url: str, *, timeout: float = 15.0) -> None:
        self._timeout = timeout
        self._conn = connect(ws_url, open_timeout=timeout, close_timeout=5)

    def close(self) -> None:
        try:
            self._conn.close()
        except Exception:
            pass

    def wait_for_state(self, *, timeout: float | None = None) -> dict[str, Any]:
        deadline = time.monotonic() + (timeout if timeout is not None else self._timeout)
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("overlay state not received")
            raw = self._conn.recv(timeout=remaining)
            data = json.loads(raw)
            if isinstance(data, dict) and data.get("type") == "state":
                return data
