from __future__ import annotations

import asyncio
import logging
from dataclasses import replace
from typing import Any

from twitchAPI.eventsub.websocket import EventSubWebsocket
from twitchAPI.helper import first
from twitchAPI.oauth import UserAuthenticator
from twitchAPI.object.eventsub import ChannelBitsUseEvent, ChannelChatMessageEvent, ChannelSubscriptionGiftEvent, ChannelSubscriptionMessageEvent, ChannelSubscribeEvent
from twitchAPI.twitch import Twitch
from twitchAPI.type import AuthScope

from ..config import AppSettings, TwitchConfig
from ..revenue.events import EventType, Platform, StreamEvent, parse_iso_datetime
from ..revenue.revenue_validity import build_auto_invalid_raw
from ..platforms.twitch_sub_dedupe import RecentSubTracker

LOGGER = logging.getLogger(__name__)
BASE_TARGET_SCOPES = [AuthScope.BITS_READ, AuthScope.CHANNEL_READ_SUBSCRIPTIONS]


def make_on_bits_use(queue: asyncio.Queue):
    async def on_bits_use(message: ChannelBitsUseEvent):
        event = normalize_bits_use(message)
        LOGGER.info(
            "bits event received user=%s bits=%s type=%s",
            event.gifter_user_name,
            event.quantity,
            event.raw.get("bits_type"),
        )
        await queue.put(event)
    return on_bits_use


def make_on_subscription_gift(queue: asyncio.Queue):
    async def on_subscription_gift(message: ChannelSubscriptionGiftEvent):
        event = normalize_subscription_gift(message)
        LOGGER.info(
            "subscription gift received user=%s total=%s tier=%s anonymous=%s",
            event.gifter_user_name,
            event.quantity,
            event.tier,
            event.raw.get("is_anonymous"),
        )
        await queue.put(event)
    return on_subscription_gift


def make_on_subscription_message(queue: asyncio.Queue, sub_tracker: RecentSubTracker | None = None):
    async def on_subscription_message(message: ChannelSubscriptionMessageEvent):
        event = normalize_subscription_message(message, sub_tracker)
        LOGGER.info(
            "resub received user=%s tier=%s duration_months=%s cumulative_months=%s",
            event.gifter_user_name,
            event.tier,
            event.raw.get("duration_months"),
            event.raw.get("cumulative_months"),
        )
        await queue.put(event)
    return on_subscription_message


def make_on_subscribe(queue: asyncio.Queue, sub_tracker: RecentSubTracker | None = None):
    async def on_subscribe(message: ChannelSubscribeEvent):
        if message.event.is_gift:
            LOGGER.info("skipping gifted subscribe event because channel.subscription.gift covers it")
            return
        event = normalize_subscribe(message)
        if sub_tracker is not None:
            sub_tracker.record_subscribe(event.gifter_user_id, event.occurred_at)
        LOGGER.info(
            "subscribe received user=%s tier=%s",
            event.gifter_user_name,
            event.tier,
        )
        await queue.put(event)
    return on_subscribe


def make_on_chat_message(queue: asyncio.Queue):
    """Chat messages are diagnostic only — never enter the revenue queue."""
    del queue
    async def on_chat_message(message: ChannelChatMessageEvent):
        event = normalize_chat_message(message)
        # Logged at DEBUG so it never reaches end-user log files at INFO. Used
        # by developers to verify EventSub wiring without flooding the bounded
        # revenue queue with non-revenue chat events.
        LOGGER.debug(
            "twitch chat message user=%s message=%r",
            event.gifter_user_name,
            event.message,
        )
    return on_chat_message


def normalize_bits_use(message: ChannelBitsUseEvent) -> StreamEvent:
    event = message.event
    bits = event.bits
    return StreamEvent(
        platform=Platform.TWITCH,
        event_type=EventType.TWITCH_BITS,
        occurred_at=_timestamp(message),
        source_event_id=_source_id(message),
        gifter_user_id=event.user_id,
        gifter_user_name=event.user_login,
        quantity=bits,
        amount_display=f"{bits} bits" if bits is not None else None,
        message=_event_text(event),
        raw={
            "bits": bits,
            "bits_type": event.type,
            "broadcaster_user_id": event.broadcaster_user_id,
            "broadcaster_user_login": event.broadcaster_user_login,
        },
    )


def normalize_subscribe(message: ChannelSubscribeEvent) -> StreamEvent:
    event = message.event
    return StreamEvent(
        platform=Platform.TWITCH,
        event_type=EventType.TWITCH_SUBSCRIPTION,
        occurred_at=_timestamp(message),
        source_event_id=_source_id(message),
        gifter_user_id=event.user_id,
        gifter_user_name=event.user_login,
        tier=str(event.tier or ""),
        raw={
            "tier": event.tier,
            "is_gift": event.is_gift,
            "broadcaster_user_id": event.broadcaster_user_id,
            "broadcaster_user_login": event.broadcaster_user_login,
        },
    )


def normalize_subscription_gift(message: ChannelSubscriptionGiftEvent) -> StreamEvent:
    event = message.event
    total = event.total
    return StreamEvent(
        platform=Platform.TWITCH,
        event_type=EventType.TWITCH_SUBSCRIPTION_GIFT,
        occurred_at=_timestamp(message),
        source_event_id=_source_id(message),
        gifter_user_id=event.user_id,
        gifter_user_name=event.user_login,
        quantity=total,
        tier=str(event.tier or ""),
        raw={
            "total": total,
            "tier": event.tier,
            "is_anonymous": event.is_anonymous,
            "cumulative_total": event.cumulative_total,
            "broadcaster_user_id": event.broadcaster_user_id,
            "broadcaster_user_login": event.broadcaster_user_login,
        },
    )


def normalize_subscription_message(
    message: ChannelSubscriptionMessageEvent,
    sub_tracker: RecentSubTracker | None = None,
) -> StreamEvent:
    event = message.event
    occurred_at = _timestamp(message)
    stream_event = StreamEvent(
        platform=Platform.TWITCH,
        event_type=EventType.TWITCH_RESUBSCRIPTION,
        occurred_at=occurred_at,
        source_event_id=_source_id(message),
        gifter_user_id=event.user_id,
        gifter_user_name=event.user_login,
        tier=str(event.tier or ""),
        message=_event_text(event),
        raw={
            "tier": event.tier,
            "duration_months": event.duration_months,
            "cumulative_months": event.cumulative_months,
            "broadcaster_user_id": event.broadcaster_user_id,
            "broadcaster_user_login": event.broadcaster_user_login,
        },
    )
    cumulative_months = event.cumulative_months
    if sub_tracker is not None and sub_tracker.should_suppress_resub(
        event.user_id, occurred_at, cumulative_months=cumulative_months,
    ):
        LOGGER.info(
            "resub matched recent subscribe within %ss — recording as invalid duplicate user=%s cumulative_months=%s",
            sub_tracker.window_seconds,
            event.user_login,
            cumulative_months,
        )
        invalid_raw = build_auto_invalid_raw(
            EventType.TWITCH_RESUBSCRIPTION.value,
            base_raw=stream_event.raw,
        )
        return replace(stream_event, event_type=EventType.REVENUE_INVALID, raw=invalid_raw)
    return stream_event


def normalize_chat_message(message: ChannelChatMessageEvent) -> StreamEvent:
    event = message.event
    return StreamEvent(
        platform=Platform.TWITCH,
        event_type=EventType.TWITCH_CHAT_MESSAGE,
        occurred_at=_timestamp(message),
        source_event_id=event.message_id,
        gifter_user_id=event.chatter_user_id,
        gifter_user_name=event.chatter_user_login,
        message=event.message.text,
        raw={
            "message_type": event.message_type,
            "broadcaster_user_id": event.broadcaster_user_id,
            "broadcaster_user_login": event.broadcaster_user_login,
        },
    )


async def await_twitch_events(
    queue: asyncio.Queue,
    shutdown: asyncio.Event,
    twitch_config: TwitchConfig,
    app_settings: AppSettings,
    registry=None,
):
    target_scopes = _target_scopes(app_settings)
    twitch = None
    auth = None
    event_sub = None

    try:
        LOGGER.info(f"initializing twitch client")
        twitch = await Twitch(twitch_config.client_id, twitch_config.client_secret)
        auth = UserAuthenticator(twitch, target_scopes)
        auth.document = """<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><title>Twitch</title></head>
<body><p>Twitch authentication complete. You may now close this tab.</p></body>
</html>"""

        LOGGER.info(f"authenticating twitch user for scopes={[scope.value for scope in target_scopes]}")
        try:
            token, refresh_token = await auth.authenticate()
        except Exception as exc:
            from .monitor_status import format_monitor_auth_error

            raise RuntimeError(format_monitor_auth_error("Twitch", exc)) from exc
        await twitch.set_user_authentication(token, target_scopes, refresh_token)
        user = await first(twitch.get_users(logins=[twitch_config.channel_name.lower()]))
        LOGGER.info(f"resolved channel login={twitch_config.channel_name!r} user_id={user.id}")

        event_sub = EventSubWebsocket(twitch)
        event_sub.start()

        sub_tracker = RecentSubTracker(app_settings.twitch_sub_resub_dedupe_seconds)
        if sub_tracker.enabled:
            LOGGER.info("twitch sub/resub dedupe window: %ss", sub_tracker.window_seconds)

        await event_sub.listen_channel_bits_use(user.id, make_on_bits_use(queue))
        await event_sub.listen_channel_subscribe(user.id, make_on_subscribe(queue, sub_tracker))
        await event_sub.listen_channel_subscription_gift(user.id, make_on_subscription_gift(queue))
        await event_sub.listen_channel_subscription_message(user.id, make_on_subscription_message(queue, sub_tracker))
        subscribed = ["bits use", "subscribe", "subscription gift", "subscription message"]
        if app_settings.log_chat_messages_for_testing:
            await event_sub.listen_channel_chat_message(user.id, user.id, make_on_chat_message(queue))
            subscribed.append("chat message")
        LOGGER.info(f"subscribed to: {', '.join(subscribed)}")
        if registry is not None:
            await registry.set_status_async("twitch", "active", None)

        LOGGER.info(f"twitch monitor running; waiting for shutdown")
        await shutdown.wait()
    finally:
        LOGGER.info(f"Closing twitch...")
        if event_sub is not None and getattr(event_sub, "_running", False):
            try:
                await asyncio.shield(event_sub.stop())
            except Exception:
                LOGGER.exception("event_sub stop failed")
        if auth is not None:
            auth.stop()
        if twitch is not None:
            try:
                await asyncio.shield(twitch.close())
            except Exception:
                LOGGER.exception("twitch close failed")


def _target_scopes(app_settings: AppSettings):
    scopes = list(BASE_TARGET_SCOPES)
    if app_settings.log_chat_messages_for_testing:
        scopes.append(AuthScope.USER_READ_CHAT)
    return scopes


def _source_id(message: Any) -> str | None:
    return message.metadata.message_id


def _timestamp(message: Any):
    raw = message.metadata.message_timestamp
    if isinstance(raw, str):
        return parse_iso_datetime(raw)
    return raw


def _event_text(event: Any) -> str | None:
    if event.message is None:
        return None
    return event.message.text
