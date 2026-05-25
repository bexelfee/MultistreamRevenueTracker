from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from fastapi import WebSocket
from starlette.websockets import WebSocketState

if TYPE_CHECKING:
    from ..goals.goal_service import GoalService
    from ..monitors.monitor_status import MonitorStatusRegistry
    from ..platforms.patreon_runtime import PatreonRuntime
    from ..revenue.session_revenue import SessionRevenueStore
    from ..services.subathon_service import SubathonService

LOGGER = logging.getLogger(__name__)


class GoalBroadcaster:
    def __init__(self) -> None:
        self._connections: dict[WebSocket, str] = {}
        self._lock = asyncio.Lock()

    async def register(self, websocket: WebSocket, *, role: str = "dashboard") -> None:
        async with self._lock:
            self._connections[websocket] = role

    async def unregister(self, websocket: WebSocket) -> None:
        async with self._lock:
            self._connections.pop(websocket, None)

    async def dashboard_connection_count(self) -> int:
        async with self._lock:
            return sum(1 for role in self._connections.values() if role == "dashboard")

    async def send_state(
        self, websocket: WebSocket, goal_service: GoalService, patreon_runtime: PatreonRuntime | None = None,
        *, monitor_registry: MonitorStatusRegistry | None = None,
        session_revenue: SessionRevenueStore | None = None,
        user_config: dict | None = None, allow_test_events: bool = False,
        supported_currencies: list[str] | None = None,
        bar_appearance: dict | None = None,
        timer_appearance: dict | None = None,
        progress_effects: dict | None = None,
        subathon_service: SubathonService | None = None,
    ) -> None:
        await websocket.send_json(
            build_ws_state(
                goal_service, patreon_runtime,
                monitor_registry=monitor_registry,
                session_revenue=session_revenue,
                user_config=user_config,
                allow_test_events=allow_test_events,
                supported_currencies=supported_currencies,
                bar_appearance=bar_appearance,
                timer_appearance=timer_appearance,
                progress_effects=progress_effects,
                subathon_service=subathon_service,
            )
        )

    async def broadcast_progress(
        self,
        goal_service: GoalService,
        *,
        bar_appearance: dict | None = None,
        progress_effects: dict | None = None,
    ) -> None:
        progress = goal_service.compute_progress()
        message: dict = {"type": "progress", **progress.to_dict()}
        if bar_appearance is not None:
            message["bar_appearance"] = bar_appearance
        if progress_effects is not None:
            message["progress_effects"] = progress_effects
        await self._broadcast(message)

    async def broadcast_state(
        self, goal_service: GoalService, patreon_runtime: PatreonRuntime | None = None,
        *, monitor_registry: MonitorStatusRegistry | None = None,
        session_revenue: SessionRevenueStore | None = None,
        user_config: dict | None = None, allow_test_events: bool = False,
        supported_currencies: list[str] | None = None,
        bar_appearance: dict | None = None,
        timer_appearance: dict | None = None,
        progress_effects: dict | None = None,
        subathon_service: SubathonService | None = None,
    ) -> None:
        await self._broadcast(
            build_ws_state(
                goal_service, patreon_runtime,
                monitor_registry=monitor_registry,
                session_revenue=session_revenue,
                user_config=user_config,
                allow_test_events=allow_test_events,
                supported_currencies=supported_currencies,
                bar_appearance=bar_appearance,
                timer_appearance=timer_appearance,
                progress_effects=progress_effects,
                subathon_service=subathon_service,
            )
        )

    async def broadcast_bar_appearance(self, bar_appearance: dict) -> None:
        await self._broadcast({"type": "bar_appearance", **bar_appearance})

    async def broadcast_progress_effects(self, progress_effects: dict) -> None:
        await self._broadcast({"type": "progress_effects", **progress_effects})

    async def broadcast_progress_effect_preview(self, *, channel: str, effect_id: str) -> None:
        await self._broadcast_to_roles(
            {
                "type": "progress_effects.preview",
                "channel": channel,
                "effect_id": effect_id,
            },
            roles={"overlay"},
        )

    async def broadcast_session_revenue(self, session_revenue: SessionRevenueStore) -> None:
        await self._broadcast({"type": "session_revenue", "events": session_revenue.snapshot()})

    async def broadcast_subathon(self, subathon_service: SubathonService) -> None:
        await self._broadcast({"type": "subathon", **subathon_service.snapshot()})

    async def broadcast_timer_appearance(self, timer_appearance: dict) -> None:
        await self._broadcast({"type": "timer_appearance", **timer_appearance})

    async def broadcast_shutdown_complete(self) -> None:
        await self._broadcast({"type": "app.shutdown.complete"})

    async def _broadcast(self, message: dict) -> None:
        await self._broadcast_to_roles(message, roles=None)

    async def _broadcast_to_roles(self, message: dict, *, roles: set[str] | None) -> None:
        async with self._lock:
            targets = [
                (websocket, role)
                for websocket, role in self._connections.items()
                if roles is None or role in roles
            ]
        for websocket, _role in targets:
            if websocket.client_state != WebSocketState.CONNECTED:
                await self.unregister(websocket)
                continue
            try:
                await websocket.send_json(message)
            except Exception:
                LOGGER.debug("dropping websocket after send failure", exc_info=True)
                await self.unregister(websocket)


def build_ws_state(
    goal_service: GoalService, patreon_runtime: PatreonRuntime | None = None,
    *, monitor_registry: MonitorStatusRegistry | None = None,
    session_revenue: SessionRevenueStore | None = None,
    user_config: dict | None = None, allow_test_events: bool = False,
    supported_currencies: list[str] | None = None,
    bar_appearance: dict | None = None,
    timer_appearance: dict | None = None,
    progress_effects: dict | None = None,
    subathon_service: SubathonService | None = None,
) -> dict:
    # Runtime presence is the source of truth: if the caller wired a runtime,
    # the platform is active for this session. The "feature_enabled" boolean
    # we used to thread alongside was always True in production.
    payload = {"type": "state", **goal_service.build_state()}
    if subathon_service is not None:
        payload["subathon"] = subathon_service.snapshot()
    if patreon_runtime is not None:
        payload["patreon"] = patreon_runtime.for_ui(goal_service.rules_store.rules, feature_enabled=True)
    if monitor_registry is not None:
        payload["monitors"] = monitor_registry.snapshot()
    if session_revenue is not None:
        payload["session_revenue"] = session_revenue.snapshot()
    if user_config is not None:
        payload["user_config"] = user_config
    payload["allow_test_events"] = allow_test_events
    if supported_currencies is not None:
        payload["supported_currencies"] = supported_currencies
    if bar_appearance is not None:
        payload["bar_appearance"] = bar_appearance
    elif user_config is not None and user_config.get("bar_appearance"):
        payload["bar_appearance"] = user_config["bar_appearance"]
    if timer_appearance is not None:
        payload["timer_appearance"] = timer_appearance
    elif user_config is not None and user_config.get("timer_appearance"):
        payload["timer_appearance"] = user_config["timer_appearance"]
    if progress_effects is not None:
        payload["progress_effects"] = progress_effects
    elif user_config is not None and user_config.get("progress_effects"):
        payload["progress_effects"] = user_config["progress_effects"]
    return payload
