from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class Platform(str, Enum):
    TWITCH = "twitch"
    YOUTUBE = "youtube"
    PATREON = "patreon"
    STREAMLABS = "streamlabs"


class EventType(str, Enum):
    TWITCH_BITS = "twitch_bits"
    TWITCH_SUBSCRIPTION = "twitch_subscription"
    TWITCH_SUBSCRIPTION_GIFT = "twitch_subscription_gift"
    TWITCH_RESUBSCRIPTION = "twitch_resubscription"
    TWITCH_RESUBSCRIPTION_SUPPRESSED = "twitch_resubscription_suppressed"  # legacy DB rows only
    REVENUE_INVALID = "revenue_invalid"
    TWITCH_CHAT_MESSAGE = "twitch_chat_message"
    YOUTUBE_SUPER_CHAT = "youtube_super_chat"
    YOUTUBE_SUPER_STICKER = "youtube_super_sticker"
    YOUTUBE_MEMBERSHIP = "youtube_membership"
    YOUTUBE_MEMBERSHIP_GIFT = "youtube_membership_gift"
    YOUTUBE_GIFT = "youtube_gift"
    YOUTUBE_CHAT_MESSAGE = "youtube_chat_message"
    PATREON_PLEDGE_CREATE = "patreon_pledge_create"
    STREAMLABS_DONATION = "streamlabs_donation"


REVENUE_EVENT_TYPES = {
    EventType.TWITCH_BITS,
    EventType.TWITCH_SUBSCRIPTION,
    EventType.TWITCH_SUBSCRIPTION_GIFT,
    EventType.TWITCH_RESUBSCRIPTION,
    EventType.TWITCH_RESUBSCRIPTION_SUPPRESSED,
    EventType.REVENUE_INVALID,
    EventType.YOUTUBE_SUPER_CHAT,
    EventType.YOUTUBE_SUPER_STICKER,
    EventType.YOUTUBE_MEMBERSHIP,
    EventType.YOUTUBE_MEMBERSHIP_GIFT,
    EventType.YOUTUBE_GIFT,
    EventType.PATREON_PLEDGE_CREATE,
    EventType.STREAMLABS_DONATION,
}


@dataclass(frozen=True)
class StreamEvent:
    platform: Platform
    event_type: EventType
    occurred_at: datetime
    source_event_id: str | None = None
    gifter_user_id: str | None = None
    gifter_user_name: str | None = None
    recipient_user_id: str | None = None
    recipient_user_name: str | None = None
    amount_micros: int | None = None
    amount_display: str | None = None
    currency: str | None = None
    quantity: int | None = None
    tier: str | None = None
    message: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)
    is_test: bool = False

    @property
    def is_revenue(self) -> bool:
        return self.event_type in REVENUE_EVENT_TYPES

    def to_json_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["platform"] = self.platform.value
        data["event_type"] = self.event_type.value
        data["occurred_at"] = self.occurred_at.isoformat()
        data["is_test"] = self.is_test
        return data


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def parse_iso_datetime(value: str | None) -> datetime:
    if not value:
        return utc_now()

    normalized = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return utc_now()

    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)
