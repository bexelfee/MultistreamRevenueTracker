from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from .events import Platform, StreamEvent
from .revenue_db import RevenueDatabase

if TYPE_CHECKING:
    from ..goals.goal_service import GoalService
    from .session_revenue import SessionRevenueStore
    from ..services.subathon_service import SubathonService

LOGGER = logging.getLogger(__name__)


async def _process_queue_item(
    queue: asyncio.Queue,
    database: RevenueDatabase,
    goal_service: GoalService | None,
    session_revenue: SessionRevenueStore | None,
    event: StreamEvent,
    subathon_service: SubathonService | None = None,
) -> None:
    try:
        row_id = await asyncio.to_thread(persist_event, database, event)
        if row_id is not None:
            stored = await asyncio.to_thread(database.get_revenue_event, row_id)
            if stored is not None:
                if session_revenue is not None:
                    await session_revenue.append_stored(stored)
                if subathon_service is not None and goal_service is not None:
                    changed = await asyncio.to_thread(
                        subathon_service.on_revenue_event,
                        stored,
                        goal_service.rules_store,
                    )
                    if changed:
                        await subathon_service.notify_changed()
            if goal_service is not None:
                await goal_service.notify_progress_changed()
    finally:
        queue.task_done()


async def write_to_db(
    queue: asyncio.Queue,
    shutdown: asyncio.Event,
    database: RevenueDatabase,
    goal_service: GoalService | None = None,
    session_revenue: SessionRevenueStore | None = None,
    subathon_service: SubathonService | None = None,
):
    LOGGER.info(f"db writer init (path={database.db_path})")
    while not shutdown.is_set():
        try:
            event = await asyncio.wait_for(queue.get(), timeout=0.2)
        except asyncio.TimeoutError:
            continue
        await _process_queue_item(
            queue, database, goal_service, session_revenue, event, subathon_service,
        )

    LOGGER.info("db writer draining queue after shutdown requested")
    while True:
        try:
            event = queue.get_nowait()
        except asyncio.QueueEmpty:
            break
        await _process_queue_item(
            queue, database, goal_service, session_revenue, event, subathon_service,
        )

    LOGGER.info("db writer shutdown complete")


def persist_event(database: RevenueDatabase, event: StreamEvent):
    if not isinstance(event, StreamEvent):
        LOGGER.warning("received non-normalized queue item: %r", event)
        return

    if not event.is_revenue:
        return
    kind = "TEST-REVENUE" if event.is_test else "REVENUE"
    # Log only non-PII fields at INFO. Full donor/gifter details are at DEBUG
    # so they only land in dev/debug builds, not the user's session log.
    LOGGER.info(
        f"{kind} platform={event.platform.value} "
        f"type={event.event_type.value} "
        f"amount={event.amount_display or _amount_from_micros(event)} "
        f"quantity={event.quantity} "
        f"tier={event.tier} "
        f"source_id={event.source_event_id}"
    )
    LOGGER.debug(
        "revenue detail platform=%s type=%s user=%s message=%r",
        event.platform.value,
        event.event_type.value,
        event.gifter_user_name,
        event.message,
    )

    row_id = database.add_revenue_event(event)
    if row_id is None:
        envelope_event_id = event.raw.get("streamlabs_envelope_event_id")
        log = LOGGER.info if event.platform == Platform.STREAMLABS else LOGGER.debug
        log(
            "skipped duplicate revenue event platform=%s source_id=%s "
            "envelope_event_id=%s envelope_for=%r donor=%s amount=%s",
            event.platform.value,
            event.source_event_id,
            envelope_event_id,
            event.raw.get("streamlabs_envelope_for"),
            event.gifter_user_name,
            event.amount_display or _amount_from_micros(event),
        )
        return None
    LOGGER.debug("stored revenue event id=%s", row_id)
    return row_id


def _amount_from_micros(event: StreamEvent) -> str | None:
    if event.amount_micros is None:
        return None
    amount = event.amount_micros / 1_000_000
    if event.currency:
        return f"{amount:.2f} {event.currency}"
    return f"{amount:.2f}"
