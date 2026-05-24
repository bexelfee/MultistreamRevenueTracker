import threading
from unittest.mock import MagicMock

from multistream_revenue_tracker.monitors import youtube_monitor as ym
from multistream_revenue_tracker.monitors.youtube_monitor import cancel_pending_youtube_oauth


def test_cancel_pending_youtube_oauth_sets_event_only():
    """Cancel must set the cancel event but MUST NOT call server.shutdown().

    server.shutdown() deadlocks because we run handle_request() in a loop, not
    serve_forever(); the WSGIServer's internal __is_shut_down event is never set.
    The waiter thread already polls cancel.is_set() with a 250ms socket timeout.
    """
    cancel = threading.Event()
    mock_server = MagicMock()

    with ym._youtube_oauth_lock:
        ym._youtube_oauth_cancel = cancel
        ym._youtube_oauth_server = mock_server

    try:
        cancel_pending_youtube_oauth()
        assert cancel.is_set()
        mock_server.shutdown.assert_not_called()
    finally:
        with ym._youtube_oauth_lock:
            ym._youtube_oauth_cancel = None
            ym._youtube_oauth_server = None
