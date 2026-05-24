import asyncio
import logging

from multistream_revenue_tracker.ui.log_broadcast import LogBroadcastHandler, subscribe


def test_log_broadcast_handler_notifies_subscriber():
    handler = LogBroadcastHandler()
    handler.setFormatter(logging.Formatter("%(message)s"))
    history, queue, unsubscribe = subscribe()
    assert history == []

    async def wait_for_line():
        return await asyncio.wait_for(queue.get(), timeout=1.0)

    handler.emit(logging.LogRecord("test", logging.INFO, "", 0, "hello ui", (), None))
    line = asyncio.run(wait_for_line())
    assert line == "hello ui"
    unsubscribe()
