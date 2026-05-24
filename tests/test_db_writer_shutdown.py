import asyncio
from datetime import datetime, timezone

import pytest

from multistream_revenue_tracker.revenue.db_writer import write_to_db
from multistream_revenue_tracker.revenue.events import EventType, Platform, StreamEvent
from multistream_revenue_tracker.revenue.revenue_db import RevenueDatabase


def _revenue_event(source_id: str) -> StreamEvent:
    return StreamEvent(
        platform=Platform.TWITCH,
        event_type=EventType.TWITCH_BITS,
        source_event_id=source_id,
        occurred_at=datetime(2026, 5, 20, 12, 0, 0, tzinfo=timezone.utc),
        quantity=100,
    )


@pytest.mark.asyncio
async def test_db_writer_drains_queue_after_shutdown(tmp_path):
    database = RevenueDatabase(tmp_path / "revenue_events.db")
    database.initialize()
    queue: asyncio.Queue = asyncio.Queue()
    shutdown = asyncio.Event()

    await queue.put(_revenue_event("a"))
    await queue.put(_revenue_event("b"))

    task = asyncio.create_task(write_to_db(queue, shutdown, database))
    await asyncio.sleep(0.05)
    shutdown.set()
    await asyncio.wait_for(task, timeout=3.0)

    assert queue.empty()
    rows = database.list_revenue_events(datetime(2026, 1, 1, tzinfo=timezone.utc))
    assert len(rows) == 2
