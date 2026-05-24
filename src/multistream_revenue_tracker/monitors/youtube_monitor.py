import asyncio
import logging
import socket
import threading
import time
import webbrowser
import wsgiref.simple_server
from pathlib import Path
from threading import Event
from typing import Any

from google_auth_oauthlib.flow import _RedirectWSGIApp, _WSGIRequestHandler

from ..config import AppSettings, YoutubeConfig
from ..revenue.events import EventType, Platform, StreamEvent, parse_iso_datetime, utc_now
from .monitor_constants import (
    MONITOR_AUTH_TIMEOUT_SECONDS,
    MONITOR_SHUTDOWN_CANCEL_TIMEOUT_SECONDS,
    MONITOR_SHUTDOWN_OAUTH_DEADLINE_SECONDS,
)
from ..log_scrubbing import register_youtube_credentials
from .monitor_status import MonitorAuthCancelled, format_monitor_auth_error


LOGGER = logging.getLogger(__name__)

_youtube_oauth_lock = threading.Lock()
_youtube_oauth_cancel: Event | None = None
_youtube_oauth_server: wsgiref.simple_server.WSGIServer | None = None

YOUTUBE_READONLY_SCOPE = "https://www.googleapis.com/auth/youtube.readonly"
YOUTUBE_MEMBERSHIPS_CREATOR_SCOPE = "https://www.googleapis.com/auth/youtube.channel-memberships.creator"
YOUTUBE_OAUTH_SCOPES = [YOUTUBE_READONLY_SCOPE, YOUTUBE_MEMBERSHIPS_CREATOR_SCOPE]
YOUTUBE_GRPC_TARGET = "dns:///youtube.googleapis.com:443"
ACTIVE_BROADCAST_STATUSES = {"live"}

TEXT_MESSAGE_EVENT = 1
CHAT_ENDED_EVENT = 4
NEW_SPONSOR_EVENT = 7
SUPER_CHAT_EVENT = 15
SUPER_STICKER_EVENT = 16
MEMBER_MILESTONE_CHAT_EVENT = 17
MEMBERSHIP_GIFTING_EVENT = 18
GIFT_MEMBERSHIP_RECEIVED_EVENT = 19
GIFT_EVENT = 21


async def await_youtube_events(
    queue: asyncio.Queue,
    shutdown: asyncio.Event,
    youtube_config: YoutubeConfig,
    app_settings: AppSettings,
    registry=None,
):
    loop = asyncio.get_running_loop()
    stop_event = threading.Event()
    done: asyncio.Future[None] = loop.create_future()

    def _finish_done(exc: BaseException | None) -> None:
        """Resolve `done` on the loop thread, ignoring if already settled/cancelled.

        `done` may already be cancelled (e.g. by `asyncio.wait_for` in the outer
        finally when the monitor task is cancelled). Calling set_exception on a
        cancelled future raises InvalidStateError; this guard prevents that.
        """
        if done.done():
            return
        if exc is None:
            done.set_result(None)
        else:
            done.set_exception(exc)

    def _run_worker() -> None:
        try:
            _run_youtube_monitor(
                youtube_config,
                app_settings,
                queue,
                loop,
                stop_event,
                registry,
            )
        except BaseException as exc:  # MonitorAuthCancelled or any error
            loop.call_soon_threadsafe(_finish_done, exc)
        else:
            loop.call_soon_threadsafe(_finish_done, None)

    async def watch_shutdown() -> None:
        await shutdown.wait()
        stop_event.set()
        cancel_pending_youtube_oauth()

    shutdown_task = asyncio.create_task(watch_shutdown())
    worker = threading.Thread(target=_run_worker, name="youtube-monitor", daemon=True)
    worker.start()
    try:
        await done
    finally:
        stop_event.set()
        cancel_pending_youtube_oauth()
        shutdown_task.cancel()
        await asyncio.gather(shutdown_task, return_exceptions=True)
        if not done.done():
            try:
                await asyncio.wait_for(done, timeout=MONITOR_SHUTDOWN_CANCEL_TIMEOUT_SECONDS)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                LOGGER.warning(
                    "YouTube monitor worker did not exit within %.1fs after cancel",
                    MONITOR_SHUTDOWN_CANCEL_TIMEOUT_SECONDS,
                )


def _run_youtube_monitor(
    youtube_config: YoutubeConfig,
    app_settings: AppSettings,
    queue: asyncio.Queue,
    loop,
    stop_event: threading.Event,
    registry=None,
) -> None:
    credentials = _load_google_credentials(youtube_config, registry, loop, stop_event)
    _set_youtube_status(registry, loop, "connecting", "Resolving live broadcast...")
    live_chat_id = _resolve_live_chat_id(youtube_config, credentials)
    LOGGER.info("resolved youtube live_chat_id=%s", live_chat_id)
    _set_youtube_status(registry, loop, "active", None)
    _stream_live_chat(youtube_config, credentials, live_chat_id, queue, loop, stop_event, app_settings.log_chat_messages_for_testing)


def _set_youtube_status(registry, loop, status: str, detail: str | None) -> None:
    if registry is None or loop is None:
        return
    future = asyncio.run_coroutine_threadsafe(
        registry.set_status_async("youtube", status, detail),
        loop,
    )
    future.result(timeout=10)


from ..platforms.oauth_local_server import force_close_oauth_server as _force_close_oauth_server  # noqa: E402


def cancel_pending_youtube_oauth() -> None:
    """Unblock an in-progress YouTube OAuth flow (same effect as Cancel in the UI).

    Sets the cancel event; the OAuth waiter thread polls it (with a 250ms socket
    timeout) and exits within ~250ms. We deliberately do NOT call server.shutdown()
    here — that call blocks forever because we use handle_request() in a loop,
    not serve_forever(), so the server's internal __is_shut_down event is never set.
    """
    with _youtube_oauth_lock:
        if _youtube_oauth_cancel is not None:
            _youtube_oauth_cancel.set()


def _oauth_wait_deadline_seconds(stop_event: threading.Event | None) -> float:
    if stop_event is not None and stop_event.is_set():
        return MONITOR_SHUTDOWN_OAUTH_DEADLINE_SECONDS
    return float(MONITOR_AUTH_TIMEOUT_SECONDS)


def _run_local_server_cancellable(
    flow,
    *,
    cancel: Event,
    stop_event: threading.Event | None = None,
) -> None:
    """Like InstalledAppFlow.run_local_server, but honour cancel_pending_youtube_oauth()."""
    wsgi_app = _RedirectWSGIApp("The authentication flow has completed.")
    wsgiref.simple_server.WSGIServer.allow_reuse_address = False
    local_server = wsgiref.simple_server.make_server(
        "localhost", 0, wsgi_app, handler_class=_WSGIRequestHandler
    )
    local_server.socket.settimeout(0.25)

    with _youtube_oauth_lock:
        global _youtube_oauth_cancel, _youtube_oauth_server
        _youtube_oauth_cancel = cancel
        _youtube_oauth_server = local_server

    try:
        flow.redirect_uri = f"http://localhost:{local_server.server_port}/"
        auth_url, _ = flow.authorization_url()
        LOGGER.info("Opening YouTube OAuth in browser")
        webbrowser.open(auth_url, new=1, autoraise=True)

        def _wait_for_callback() -> None:
            while not cancel.is_set():
                if stop_event is not None and stop_event.is_set():
                    return
                try:
                    local_server.handle_request()
                except socket.timeout:
                    continue
                except OSError:
                    return
                if getattr(wsgi_app, "last_request_uri", None):
                    return

        waiter = threading.Thread(target=_wait_for_callback, daemon=True)
        waiter.start()
        deadline = time.monotonic() + _oauth_wait_deadline_seconds(stop_event)
        try:
            while waiter.is_alive():
                if cancel.is_set():
                    raise MonitorAuthCancelled()
                if stop_event is not None and stop_event.is_set():
                    raise MonitorAuthCancelled()
                if time.monotonic() >= deadline:
                    raise TimeoutError("YouTube authorisation timed out")
                time.sleep(0.05)
        finally:
            _force_close_oauth_server(local_server)
            waiter.join(timeout=2.0)

        if cancel.is_set():
            raise MonitorAuthCancelled()
        if not getattr(wsgi_app, "last_request_uri", None):
            raise TimeoutError("YouTube authorisation timed out or was denied")

        authorization_response = wsgi_app.last_request_uri.replace("http", "https")
        flow.fetch_token(authorization_response=authorization_response)
    finally:
        _force_close_oauth_server(local_server)
        with _youtube_oauth_lock:
            if _youtube_oauth_cancel is cancel:
                _youtube_oauth_cancel = None
            if _youtube_oauth_server is local_server:
                _youtube_oauth_server = None


def load_youtube_credentials(
    youtube_config: YoutubeConfig,
    registry=None,
    loop=None,
    stop_event: threading.Event | None = None,
):
    """Load or refresh Google OAuth credentials (both readonly and memberships scopes)."""
    return _load_google_credentials(
        youtube_config,
        registry=registry,
        loop=loop,
        stop_event=stop_event,
    )


def _load_google_credentials(
    youtube_config: YoutubeConfig,
    registry=None,
    loop=None,
    stop_event: threading.Event | None = None,
):
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError as exc:
        raise RuntimeError(
            "Missing Google OAuth dependencies. Install requirements.txt before running YouTube monitor."
        ) from exc

    token_path = youtube_config.token_path
    credentials = None
    if token_path.is_file():
        credentials = Credentials.from_authorized_user_file(str(token_path), YOUTUBE_OAUTH_SCOPES)

    if credentials and credentials.expired and credentials.refresh_token:
        credentials.refresh(Request())
        _write_token(token_path, credentials)

    if not credentials or not credentials.valid:
        from google_auth_oauthlib.flow import InstalledAppFlow

        _set_youtube_status(registry, loop, "authenticating", None)
        if not youtube_config.oauth_client_config:
            raise RuntimeError(
                "YouTube OAuth client is not configured. Set YOUTUBE_CLIENT_SECRETS_PATH or "
                "YOUTUBE_OAUTH_CLIENT_JSON (see README)."
            )
        flow = InstalledAppFlow.from_client_config(
            youtube_config.oauth_client_config,
            scopes=YOUTUBE_OAUTH_SCOPES,
        )
        cancel = Event()
        if stop_event is not None:

            def _watch_stop() -> None:
                stop_event.wait()
                cancel.set()

            threading.Thread(target=_watch_stop, daemon=True).start()

        try:
            _run_local_server_cancellable(flow, cancel=cancel, stop_event=stop_event)
            credentials = flow.credentials
        except MonitorAuthCancelled:
            raise
        except Exception as exc:
            raise RuntimeError(format_monitor_auth_error("YouTube", exc)) from exc
        _write_token(token_path, credentials)

    return credentials


def _write_token(token_path: Path, credentials) -> None:
    token_path.parent.mkdir(parents=True, exist_ok=True)
    token_path.write_text(credentials.to_json(), encoding="utf-8")
    register_youtube_credentials(credentials)


def _resolve_live_chat_id(youtube_config: YoutubeConfig, credentials) -> str:
    try:
        from googleapiclient.discovery import build
    except ImportError as exc:
        raise RuntimeError(
            "Missing Google API client dependency. Install requirements.txt before running YouTube monitor."
        ) from exc

    service = build("youtube", "v3", credentials=credentials)
    response = service.liveBroadcasts().list(
        part="snippet,status",
        mine=True,
        maxResults=50,
    ).execute()
    broadcasts = response.get("items", [])
    if not broadcasts:
        raise RuntimeError("No live youtube broadcast found")

    live_broadcasts = _active_live_broadcasts(broadcasts)
    if not live_broadcasts:
        raise RuntimeError("No live youtube broadcast found")
    if len(live_broadcasts) > 1:
        LOGGER.warning("multiple active YouTube broadcasts found; using the first one")
    return live_broadcasts[0]["snippet"]["liveChatId"]


def _active_live_broadcasts(broadcasts):
    return [
        item for item in broadcasts
        if ((item.get("status") or {}).get("lifeCycleStatus") in ACTIVE_BROADCAST_STATUSES)
        and (item.get("snippet") or {}).get("liveChatId")
    ]


def _stream_live_chat(youtube_config: YoutubeConfig, credentials, live_chat_id: str, queue: asyncio.Queue, loop, stop_event: threading.Event, log_chat_messages: bool) -> None:
    try:
        import grpc
    except ImportError as exc:
        raise RuntimeError("Missing grpc dependency. Install requirements.txt before running YouTube monitor.") from exc

    request_class, response_class = _build_stream_list_messages()
    channel = grpc.secure_channel(YOUTUBE_GRPC_TARGET, grpc.ssl_channel_credentials())
    stream_list = channel.unary_stream(
        "/youtube.api.v3.V3DataLiveChatMessageService/StreamList",
        request_serializer=request_class.SerializeToString,
        response_deserializer=response_class.FromString,
    )
    next_page_token = None

    try:
        while not stop_event.is_set():
            request = request_class(
                live_chat_id=live_chat_id,
                part=["snippet", "authorDetails"],
                max_results=200,
                page_token=next_page_token or "",
            )
            try:
                metadata = _authorization_metadata(youtube_config, credentials)
                for response in stream_list(request, metadata=metadata, timeout=30):
                    if stop_event.is_set():
                        return
                    for item in response.items:
                        event = normalize_youtube_message(
                            item,
                            log_chat_messages=log_chat_messages,
                        )
                        if event:
                            asyncio.run_coroutine_threadsafe(queue.put(event), loop).result(timeout=10)
                    next_page_token = response.next_page_token or next_page_token
                    if response.offline_at:
                        LOGGER.info("youtube live chat went offline at %s; monitor will idle", response.offline_at)
                        return
            except grpc.RpcError as exc:
                if stop_event.is_set():
                    return
                if exc.code() == grpc.StatusCode.DEADLINE_EXCEEDED:
                    continue
                LOGGER.exception("youtube live chat stream failed; retrying shortly")
                time.sleep(5)
    finally:
        channel.close()


def _authorization_metadata(youtube_config: YoutubeConfig, credentials):
    from google.auth.transport.requests import Request

    if credentials.expired and credentials.refresh_token:
        credentials.refresh(Request())
        _write_token(youtube_config.token_path, credentials)
    return (("authorization", f"Bearer {credentials.token}"),)


def normalize_youtube_message(message: Any, log_chat_messages: bool = False) -> StreamEvent | None:
    snippet = message.snippet
    author = message.author_details
    occurred_at = parse_iso_datetime(_field(snippet, "published_at"))
    message_type = _field(snippet, "type")

    if message_type == TEXT_MESSAGE_EVENT:
        if not log_chat_messages:
            return None
        details = snippet.text_message_details
        return _base_event(
            message,
            EventType.YOUTUBE_CHAT_MESSAGE,
            occurred_at,
            message_text=_field(details, "message_text") or _field(snippet, "display_message"),
            author=author,
            raw={"youtube_type": "textMessageEvent"},
        )

    if message_type == SUPER_CHAT_EVENT:
        details = snippet.super_chat_details
        return _base_event(
            message,
            EventType.YOUTUBE_SUPER_CHAT,
            occurred_at,
            message_text=_field(details, "user_comment") or _field(snippet, "display_message"),
            author=author,
            amount_micros=_field(details, "amount_micros"),
            amount_display=_field(details, "amount_display_string"),
            currency=_field(details, "currency"),
            tier=str(_field(details, "tier") or ""),
            raw={"youtube_type": "superChatEvent"},
        )

    if message_type == SUPER_STICKER_EVENT:
        details = snippet.super_sticker_details
        sticker = details.super_sticker_metadata
        return _base_event(
            message,
            EventType.YOUTUBE_SUPER_STICKER,
            occurred_at,
            message_text=_field(sticker, "alt_text") or _field(snippet, "display_message"),
            author=author,
            amount_micros=_field(details, "amount_micros"),
            amount_display=_field(details, "amount_display_string"),
            currency=_field(details, "currency"),
            tier=str(_field(details, "tier") or ""),
            raw={
                "youtube_type": "superStickerEvent",
                "sticker_id": _field(sticker, "sticker_id"),
            },
        )

    if message_type == NEW_SPONSOR_EVENT:
        details = snippet.new_sponsor_details
        return _base_event(
            message,
            EventType.YOUTUBE_MEMBERSHIP,
            occurred_at,
            message_text=_field(snippet, "display_message"),
            author=author,
            tier=_field(details, "member_level_name"),
            raw={
                "youtube_type": "newSponsorEvent",
                "is_upgrade": _field(details, "is_upgrade"),
            },
        )

    if message_type == MEMBERSHIP_GIFTING_EVENT:
        details = snippet.membership_gifting_details
        return _base_event(
            message,
            EventType.YOUTUBE_MEMBERSHIP_GIFT,
            occurred_at,
            message_text=_field(snippet, "display_message"),
            author=author,
            quantity=_field(details, "gift_memberships_count"),
            tier=_field(details, "gift_memberships_level_name"),
            raw={"youtube_type": "membershipGiftingEvent"},
        )

    if message_type == GIFT_MEMBERSHIP_RECEIVED_EVENT:
        # Recipient-side "X received a gift membership" notifications. The bulk
        # gifting itself is already covered by membershipGiftingEvent above
        # (consistent with how Twitch sub_gift suppresses the per-recipient
        # subscribe events). Skip here to avoid double-counting.
        return None

    if message_type == GIFT_EVENT:
        details = snippet.gift_details
        return _base_event(
            message,
            EventType.YOUTUBE_GIFT,
            occurred_at,
            message_text=_field(snippet, "display_message"),
            author=author,
            quantity=_field(details, "jewels_amount"),
            amount_display=f"{_field(details, 'jewels_amount')} jewels",
            raw={
                "youtube_type": "giftEvent",
                "gift_name": _field(details, "gift_name"),
                "combo_count": _field(details, "combo_count"),
            },
        )

    if message_type == CHAT_ENDED_EVENT:
        LOGGER.info("youtube live chat ended")
    elif message_type == MEMBER_MILESTONE_CHAT_EVENT:
        LOGGER.debug("youtube member milestone chat ignored as non-revenue")
    return None


def _base_event(
    message: Any,
    event_type: EventType,
    occurred_at,
    message_text: str | None,
    author: Any,
    amount_micros: int | None = None,
    amount_display: str | None = None,
    currency: str | None = None,
    quantity: int | None = None,
    tier: str | None = None,
    recipient_user_id: str | None = None,
    recipient_user_name: str | None = None,
    raw: dict[str, Any] | None = None,
) -> StreamEvent:
    return StreamEvent(
        platform=Platform.YOUTUBE,
        event_type=event_type,
        occurred_at=occurred_at or utc_now(),
        source_event_id=_field(message, "id"),
        gifter_user_id=_field(author, "channel_id"),
        gifter_user_name=_field(author, "display_name"),
        recipient_user_id=recipient_user_id,
        recipient_user_name=recipient_user_name,
        amount_micros=amount_micros,
        amount_display=amount_display,
        currency=currency,
        quantity=quantity,
        tier=tier,
        message=message_text,
        raw=raw or {},
    )


def _field(obj: Any, name: str):
    if obj is None:
        return None
    try:
        return getattr(obj, name)
    except AttributeError:
        return None


def _build_stream_list_messages():
    try:
        from google.protobuf import descriptor_pb2, descriptor_pool, message_factory
    except ImportError as exc:
        raise RuntimeError("Missing protobuf dependency. Install requirements.txt before running YouTube monitor.") from exc

    file_proto = descriptor_pb2.FileDescriptorProto()
    file_proto.name = "stream_list_dynamic.proto"
    file_proto.package = "youtube.api.v3"
    file_proto.syntax = "proto2"

    def add_message(name: str):
        message = file_proto.message_type.add()
        message.name = name
        return message

    def add_field(message, name: str, number: int, field_type: int, repeated: bool = False, type_name: str | None = None):
        field = message.field.add()
        field.name = name
        field.number = number
        field.label = (
            descriptor_pb2.FieldDescriptorProto.LABEL_REPEATED
            if repeated
            else descriptor_pb2.FieldDescriptorProto.LABEL_OPTIONAL
        )
        field.type = field_type
        if type_name:
            field.type_name = type_name

    request = add_message("LiveChatMessageListRequest")
    add_field(request, "live_chat_id", 1, descriptor_pb2.FieldDescriptorProto.TYPE_STRING)
    add_field(request, "hl", 2, descriptor_pb2.FieldDescriptorProto.TYPE_STRING)
    add_field(request, "profile_image_size", 3, descriptor_pb2.FieldDescriptorProto.TYPE_UINT32)
    add_field(request, "max_results", 98, descriptor_pb2.FieldDescriptorProto.TYPE_UINT32)
    add_field(request, "page_token", 99, descriptor_pb2.FieldDescriptorProto.TYPE_STRING)
    add_field(request, "part", 100, descriptor_pb2.FieldDescriptorProto.TYPE_STRING, repeated=True)

    response = add_message("LiveChatMessageListResponse")
    add_field(response, "kind", 200, descriptor_pb2.FieldDescriptorProto.TYPE_STRING)
    add_field(response, "etag", 201, descriptor_pb2.FieldDescriptorProto.TYPE_STRING)
    add_field(response, "offline_at", 2, descriptor_pb2.FieldDescriptorProto.TYPE_STRING)
    add_field(response, "next_page_token", 100602, descriptor_pb2.FieldDescriptorProto.TYPE_STRING)
    add_field(response, "items", 1007, descriptor_pb2.FieldDescriptorProto.TYPE_MESSAGE, repeated=True, type_name=".youtube.api.v3.LiveChatMessage")

    live_message = add_message("LiveChatMessage")
    add_field(live_message, "kind", 200, descriptor_pb2.FieldDescriptorProto.TYPE_STRING)
    add_field(live_message, "etag", 201, descriptor_pb2.FieldDescriptorProto.TYPE_STRING)
    add_field(live_message, "id", 101, descriptor_pb2.FieldDescriptorProto.TYPE_STRING)
    add_field(live_message, "snippet", 2, descriptor_pb2.FieldDescriptorProto.TYPE_MESSAGE, type_name=".youtube.api.v3.LiveChatMessageSnippet")
    add_field(live_message, "author_details", 3, descriptor_pb2.FieldDescriptorProto.TYPE_MESSAGE, type_name=".youtube.api.v3.LiveChatMessageAuthorDetails")

    author = add_message("LiveChatMessageAuthorDetails")
    add_field(author, "channel_id", 10101, descriptor_pb2.FieldDescriptorProto.TYPE_STRING)
    add_field(author, "channel_url", 102, descriptor_pb2.FieldDescriptorProto.TYPE_STRING)
    add_field(author, "display_name", 103, descriptor_pb2.FieldDescriptorProto.TYPE_STRING)
    add_field(author, "profile_image_url", 104, descriptor_pb2.FieldDescriptorProto.TYPE_STRING)
    add_field(author, "is_verified", 4, descriptor_pb2.FieldDescriptorProto.TYPE_BOOL)
    add_field(author, "is_chat_owner", 5, descriptor_pb2.FieldDescriptorProto.TYPE_BOOL)
    add_field(author, "is_chat_sponsor", 6, descriptor_pb2.FieldDescriptorProto.TYPE_BOOL)
    add_field(author, "is_chat_moderator", 7, descriptor_pb2.FieldDescriptorProto.TYPE_BOOL)

    snippet = add_message("LiveChatMessageSnippet")
    enum = snippet.enum_type.add()
    enum.name = "Type"
    for name, number in {
        "INVALID_TYPE": 0,
        "TEXT_MESSAGE_EVENT": 1,
        "TOMBSTONE": 2,
        "FAN_FUNDING_EVENT": 3,
        "CHAT_ENDED_EVENT": 4,
        "SPONSOR_ONLY_MODE_STARTED_EVENT": 5,
        "SPONSOR_ONLY_MODE_ENDED_EVENT": 6,
        "NEW_SPONSOR_EVENT": 7,
        "MESSAGE_DELETED_EVENT": 8,
        "MESSAGE_RETRACTED_EVENT": 9,
        "USER_BANNED_EVENT": 10,
        "SUPER_CHAT_EVENT": 15,
        "SUPER_STICKER_EVENT": 16,
        "MEMBER_MILESTONE_CHAT_EVENT": 17,
        "MEMBERSHIP_GIFTING_EVENT": 18,
        "GIFT_MEMBERSHIP_RECEIVED_EVENT": 19,
        "POLL_EVENT": 20,
        "GIFT_EVENT": 21,
    }.items():
        value = enum.value.add()
        value.name = name
        value.number = number

    add_field(snippet, "type", 1, descriptor_pb2.FieldDescriptorProto.TYPE_ENUM, type_name=".youtube.api.v3.LiveChatMessageSnippet.Type")
    add_field(snippet, "live_chat_id", 201, descriptor_pb2.FieldDescriptorProto.TYPE_STRING)
    add_field(snippet, "author_channel_id", 301, descriptor_pb2.FieldDescriptorProto.TYPE_STRING)
    add_field(snippet, "published_at", 4, descriptor_pb2.FieldDescriptorProto.TYPE_STRING)
    add_field(snippet, "has_display_content", 17, descriptor_pb2.FieldDescriptorProto.TYPE_BOOL)
    add_field(snippet, "display_message", 16, descriptor_pb2.FieldDescriptorProto.TYPE_STRING)
    add_field(snippet, "text_message_details", 19, descriptor_pb2.FieldDescriptorProto.TYPE_MESSAGE, type_name=".youtube.api.v3.LiveChatTextMessageDetails")
    add_field(snippet, "super_chat_details", 27, descriptor_pb2.FieldDescriptorProto.TYPE_MESSAGE, type_name=".youtube.api.v3.LiveChatSuperChatDetails")
    add_field(snippet, "super_sticker_details", 28, descriptor_pb2.FieldDescriptorProto.TYPE_MESSAGE, type_name=".youtube.api.v3.LiveChatSuperStickerDetails")
    add_field(snippet, "new_sponsor_details", 29, descriptor_pb2.FieldDescriptorProto.TYPE_MESSAGE, type_name=".youtube.api.v3.LiveChatNewSponsorDetails")
    add_field(snippet, "member_milestone_chat_details", 30, descriptor_pb2.FieldDescriptorProto.TYPE_MESSAGE, type_name=".youtube.api.v3.LiveChatMemberMilestoneChatDetails")
    add_field(snippet, "membership_gifting_details", 31, descriptor_pb2.FieldDescriptorProto.TYPE_MESSAGE, type_name=".youtube.api.v3.LiveChatMembershipGiftingDetails")
    add_field(snippet, "gift_membership_received_details", 32, descriptor_pb2.FieldDescriptorProto.TYPE_MESSAGE, type_name=".youtube.api.v3.LiveChatGiftMembershipReceivedDetails")
    add_field(snippet, "gift_details", 34, descriptor_pb2.FieldDescriptorProto.TYPE_MESSAGE, type_name=".youtube.api.v3.LiveChatGiftDetails")

    text = add_message("LiveChatTextMessageDetails")
    add_field(text, "message_text", 1, descriptor_pb2.FieldDescriptorProto.TYPE_STRING)

    super_chat = add_message("LiveChatSuperChatDetails")
    add_field(super_chat, "amount_micros", 1, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64)
    add_field(super_chat, "currency", 2, descriptor_pb2.FieldDescriptorProto.TYPE_STRING)
    add_field(super_chat, "amount_display_string", 3, descriptor_pb2.FieldDescriptorProto.TYPE_STRING)
    add_field(super_chat, "user_comment", 4, descriptor_pb2.FieldDescriptorProto.TYPE_STRING)
    add_field(super_chat, "tier", 5, descriptor_pb2.FieldDescriptorProto.TYPE_UINT32)

    super_sticker = add_message("LiveChatSuperStickerDetails")
    add_field(super_sticker, "amount_micros", 1, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64)
    add_field(super_sticker, "currency", 2, descriptor_pb2.FieldDescriptorProto.TYPE_STRING)
    add_field(super_sticker, "amount_display_string", 3, descriptor_pb2.FieldDescriptorProto.TYPE_STRING)
    add_field(super_sticker, "tier", 4, descriptor_pb2.FieldDescriptorProto.TYPE_UINT32)
    add_field(super_sticker, "super_sticker_metadata", 5, descriptor_pb2.FieldDescriptorProto.TYPE_MESSAGE, type_name=".youtube.api.v3.SuperStickerMetadata")

    new_sponsor = add_message("LiveChatNewSponsorDetails")
    add_field(new_sponsor, "member_level_name", 1, descriptor_pb2.FieldDescriptorProto.TYPE_STRING)
    add_field(new_sponsor, "is_upgrade", 2, descriptor_pb2.FieldDescriptorProto.TYPE_BOOL)

    milestone = add_message("LiveChatMemberMilestoneChatDetails")
    add_field(milestone, "member_level_name", 1, descriptor_pb2.FieldDescriptorProto.TYPE_STRING)
    add_field(milestone, "member_month", 2, descriptor_pb2.FieldDescriptorProto.TYPE_UINT32)
    add_field(milestone, "user_comment", 3, descriptor_pb2.FieldDescriptorProto.TYPE_STRING)

    gifting = add_message("LiveChatMembershipGiftingDetails")
    add_field(gifting, "gift_memberships_count", 1, descriptor_pb2.FieldDescriptorProto.TYPE_INT32)
    add_field(gifting, "gift_memberships_level_name", 2, descriptor_pb2.FieldDescriptorProto.TYPE_STRING)

    received = add_message("LiveChatGiftMembershipReceivedDetails")
    add_field(received, "member_level_name", 1, descriptor_pb2.FieldDescriptorProto.TYPE_STRING)
    add_field(received, "gifter_channel_id", 2, descriptor_pb2.FieldDescriptorProto.TYPE_STRING)
    add_field(received, "associated_membership_gifting_message_id", 3, descriptor_pb2.FieldDescriptorProto.TYPE_STRING)

    gift = add_message("LiveChatGiftDetails")
    add_field(gift, "gift_name", 1, descriptor_pb2.FieldDescriptorProto.TYPE_STRING)
    add_field(gift, "jewels_amount", 3, descriptor_pb2.FieldDescriptorProto.TYPE_INT32)
    add_field(gift, "gift_url", 4, descriptor_pb2.FieldDescriptorProto.TYPE_STRING)
    add_field(gift, "alt_text", 5, descriptor_pb2.FieldDescriptorProto.TYPE_STRING)
    add_field(gift, "language", 6, descriptor_pb2.FieldDescriptorProto.TYPE_STRING)
    add_field(gift, "has_visual_effect", 7, descriptor_pb2.FieldDescriptorProto.TYPE_BOOL)
    add_field(gift, "combo_count", 8, descriptor_pb2.FieldDescriptorProto.TYPE_INT32)

    sticker = add_message("SuperStickerMetadata")
    add_field(sticker, "sticker_id", 1, descriptor_pb2.FieldDescriptorProto.TYPE_STRING)
    add_field(sticker, "alt_text", 2, descriptor_pb2.FieldDescriptorProto.TYPE_STRING)
    add_field(sticker, "alt_text_language", 3, descriptor_pb2.FieldDescriptorProto.TYPE_STRING)

    pool = descriptor_pool.DescriptorPool()
    pool.Add(file_proto)
    request_class = message_factory.GetMessageClass(
        pool.FindMessageTypeByName("youtube.api.v3.LiveChatMessageListRequest")
    )
    response_class = message_factory.GetMessageClass(
        pool.FindMessageTypeByName("youtube.api.v3.LiveChatMessageListResponse")
    )
    return request_class, response_class
