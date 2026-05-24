"""Shared monitor timing constants (no imports from monitor modules)."""

MONITOR_AUTH_TIMEOUT_SECONDS = 120
# Max time to wait for a monitor task when the user clicks Cancel / Disconnect.
MONITOR_DISCONNECT_CANCEL_TIMEOUT_SECONDS = 5.0
# Max time to wait for a monitor asyncio task during app shutdown (OAuth may outlive this in a daemon thread).
MONITOR_SHUTDOWN_CANCEL_TIMEOUT_SECONDS = 5.0
# OAuth loop deadline once shutdown/stop has been requested.
MONITOR_SHUTDOWN_OAUTH_DEADLINE_SECONDS = 5.0
