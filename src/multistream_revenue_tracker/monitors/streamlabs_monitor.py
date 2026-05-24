from __future__ import annotations

import asyncio
import logging
import threading
import time
from decimal import Decimal, InvalidOperation
from typing import Any

import socketio

from ..config import AppSettings, StreamlabsConfig
from ..revenue.events import EventType, Platform, StreamEvent, utc_now

LOGGER = logging.getLogger(__name__)

SOCKET_URL_TEMPLATE = "https://sockets.streamlabs.com?token={token}"

_stop_event: threading.Event | None = None
_stop_lock = threading.Lock()


def request_streamlabs_stop() -> None:
    """Signal the socket worker thread to disconnect (disconnect / shutdown)."""
    with _stop_lock:
        if _stop_event is not None:
            _stop_event.set()


def _amount_to_micros(amount: str | float | int | None) -> int | None:
    if amount is None or amount == "":
        return None
    try:
        value = Decimal(str(amount))
    except (InvalidOperation, ValueError):
        return None
    if value < 0:
        return None
    return int((value * 1_000_000).quantize(Decimal("1")))


def normalize_streamlabs_donation(
    item: dict[str, Any],
    *,
    envelope_event_id: str | None = None,
    envelope_for: str | None = None,
) -> StreamEvent | None:
    """Map one donation object from a Streamlabs socket `message` array item."""
    source_id = item.get("id") or item.get("_id")
    if source_id is None:
        return None
    name = str(item.get("name") or item.get("from") or "Anonymous").strip() or "Anonymous"
    currency = str(item.get("currency") or "USD").strip().upper() or "USD"
    amount_display = (
        str(item.get("formatted_amount") or item.get("formattedAmount") or "").strip()
        or None
    )
    amount_micros = _amount_to_micros(item.get("amount"))
    if amount_display is None and amount_micros is not None:
        amount_display = f"{amount_micros / 1_000_000:.2f} {currency}"
    message = item.get("message")
    msg = str(message).strip() if message is not None else None
    raw = dict(item)
    if envelope_event_id:
        raw["streamlabs_envelope_event_id"] = envelope_event_id
    if envelope_for is not None:
        raw["streamlabs_envelope_for"] = envelope_for
    return StreamEvent(
        platform=Platform.STREAMLABS,
        event_type=EventType.STREAMLABS_DONATION,
        occurred_at=utc_now(),
        source_event_id=str(source_id),
        gifter_user_name=name,
        amount_micros=amount_micros,
        amount_display=amount_display,
        currency=currency,
        message=msg or None,
        raw=raw,
    )


def _recipient_name(item: dict[str, Any]) -> str | None:
    to = item.get("to")
    if isinstance(to, dict):
        name = to.get("name")
        if name is not None:
            text = str(name).strip()
            return text or None
    return None


def _log_ignored_donation_envelope(data: dict[str, Any]) -> None:
    """Donation-shaped socket payloads we deliberately skip (e.g. platform relays)."""
    messages = data.get("message")
    count = len(messages) if isinstance(messages, list) else 0
    LOGGER.info(
        "streamlabs donation envelope skipped for=%r event_id=%s message_count=%s "
        "(native donations only; relays are handled by Twitch/YouTube monitors)",
        data.get("for"),
        data.get("event_id"),
        count,
    )


def _log_donation_envelope(data: dict[str, Any]) -> None:
    messages = data.get("message")
    count = len(messages) if isinstance(messages, list) else 0
    LOGGER.info(
        "streamlabs donation envelope accepted for=%r event_id=%s message_count=%s",
        data.get("for"),
        data.get("event_id"),
        count,
    )


def _is_streamlabs_donation_payload(data: dict[str, Any]) -> bool:
    """Donations: type=donation with no `for` or `for=streamlabs` (not platform relays)."""
    if data.get("type") != "donation":
        return False
    for_target = data.get("for")
    if for_target is None or for_target == "":
        return True
    return for_target == "streamlabs"


def _handle_socket_event(
    data: dict[str, Any],
    *,
    loop: asyncio.AbstractEventLoop,
    queue: asyncio.Queue,
    seen_source_ids: set[str],
) -> None:
    if data.get("type") == "donation" and not _is_streamlabs_donation_payload(data):
        _log_ignored_donation_envelope(data)
        return
    if not _is_streamlabs_donation_payload(data):
        LOGGER.debug(
            "streamlabs socket event ignored type=%s for=%r event_id=%s",
            data.get("type"),
            data.get("for"),
            data.get("event_id"),
        )
        return
    _log_donation_envelope(data)
    envelope_event_id = data.get("event_id")
    envelope_for = data.get("for")
    envelope_event_id_str = str(envelope_event_id) if envelope_event_id is not None else None
    envelope_for_str = str(envelope_for) if envelope_for is not None else None

    messages = data.get("message")
    if not isinstance(messages, list):
        LOGGER.warning(
            "streamlabs donation envelope missing message list event_id=%s",
            envelope_event_id_str,
        )
        return
    for index, item in enumerate(messages):
        if not isinstance(item, dict):
            LOGGER.warning(
                "streamlabs donation message[%s] is not an object event_id=%s",
                index,
                envelope_event_id_str,
            )
            continue
        event = normalize_streamlabs_donation(
            item,
            envelope_event_id=envelope_event_id_str,
            envelope_for=envelope_for_str,
        )
        if event is None:
            LOGGER.warning(
                "streamlabs donation message[%s] skipped (no id/_id) event_id=%s keys=%s",
                index,
                envelope_event_id_str,
                sorted(item.keys()),
            )
            continue
        source_id = event.source_event_id or ""
        if source_id in seen_source_ids:
            LOGGER.warning(
                "streamlabs donation repeat socket delivery source_event_id=%s "
                "envelope_event_id=%s for=%r donor=%s amount=%s "
                "(DB dedupes identical platform+source_event_id; different ids may double-count)",
                source_id,
                envelope_event_id_str,
                envelope_for_str,
                event.gifter_user_name,
                event.amount_display or event.amount_micros,
            )
        else:
            seen_source_ids.add(source_id)
        LOGGER.info(
            "streamlabs donation queued source_event_id=%s item_id=%s item__id=%s "
            "envelope_event_id=%s envelope_for=%r donor=%s amount=%s currency=%s "
            "recipient=%s message_count=%s",
            source_id,
            item.get("id"),
            item.get("_id"),
            envelope_event_id_str,
            envelope_for_str,
            event.gifter_user_name,
            event.amount_display or event.amount_micros,
            event.currency,
            _recipient_name(item),
            len(messages),
        )
        asyncio.run_coroutine_threadsafe(queue.put(event), loop)


def _run_socket_worker(
    token: str,
    *,
    loop: asyncio.AbstractEventLoop,
    queue: asyncio.Queue,
    stop_event: threading.Event,
    connected: threading.Event,
    error_holder: list[BaseException],
) -> None:
    global _stop_event
    with _stop_lock:
        _stop_event = stop_event

    sio = socketio.Client()
    url = SOCKET_URL_TEMPLATE.format(token=token)
    seen_source_ids: set[str] = set()

    @sio.on("connect")
    def _on_connect() -> None:
        seen_source_ids.clear()
        LOGGER.info("Streamlabs socket connected")
        connected.set()

    @sio.on("event")
    def _on_event(data: dict) -> None:
        if isinstance(data, dict):
            _handle_socket_event(data, loop=loop, queue=queue, seen_source_ids=seen_source_ids)

    @sio.on("disconnect")
    def _on_disconnect() -> None:
        LOGGER.info("Streamlabs socket disconnected")

    try:
        sio.connect(url, transports=["websocket"])
        while not stop_event.is_set():
            time.sleep(0.2)
    except Exception as exc:
        error_holder.append(exc)
        LOGGER.exception("Streamlabs socket worker failed")
    finally:
        try:
            sio.disconnect()
        except Exception:
            pass
        with _stop_lock:
            if _stop_event is stop_event:
                _stop_event = None


async def await_streamlabs_events(
    queue: asyncio.Queue,
    shutdown: asyncio.Event,
    streamlabs_config: StreamlabsConfig,
    app_settings: AppSettings,
    registry=None,
) -> None:
    del app_settings
    token = streamlabs_config.socket_api_token.strip()
    if not token:
        raise RuntimeError(
            "Streamlabs Socket API token is not configured. "
            "Add it on the Configuration tab (Streamlabs → Settings → API → API Tokens)."
        )

    loop = asyncio.get_running_loop()
    stop_event = threading.Event()
    connected = threading.Event()
    error_holder: list[BaseException] = []

    if registry is not None:
        await registry.set_status_async("streamlabs", "connecting", None)

    worker = threading.Thread(
        target=_run_socket_worker,
        kwargs={
            "token": token,
            "loop": loop,
            "queue": queue,
            "stop_event": stop_event,
            "connected": connected,
            "error_holder": error_holder,
        },
        name="streamlabs-socket",
        daemon=True,
    )
    worker.start()

    try:
        if not connected.wait(timeout=15.0):
            if error_holder:
                raise error_holder[0]
            raise RuntimeError(
                "Timed out connecting to Streamlabs. Check your Socket API token on the Configuration tab."
            )
        if error_holder:
            raise error_holder[0]
        if registry is not None:
            await registry.set_status_async("streamlabs", "active", None)

        await shutdown.wait()
    finally:
        stop_event.set()
        request_streamlabs_stop()
        worker.join(timeout=5.0)
        if worker.is_alive():
            LOGGER.warning("Streamlabs socket worker did not exit within 5s")
