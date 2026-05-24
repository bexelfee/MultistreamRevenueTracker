from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from typing import Any

from .events import EventType
from .revenue_db import StoredRevenueEvent

INVALID_EVENT_TYPE = EventType.REVENUE_INVALID
LEGACY_SUPPRESSED_TYPE = EventType.TWITCH_RESUBSCRIPTION_SUPPRESSED

REASON_DUPLICATE_SUB_RESUB = "duplicate_sub_resub"
REASON_MANUAL = "manual_adjustment"

ACTION_INVALIDATED = "invalidated"
ACTION_VALIDATED = "validated"

SOURCE_AUTO = "auto"
SOURCE_MANUAL = "manual"


def is_stored_invalid(event: StoredRevenueEvent) -> bool:
    return event.event_type in {INVALID_EVENT_TYPE, LEGACY_SUPPRESSED_TYPE}


def is_scoring_valid(event: StoredRevenueEvent) -> bool:
    return not is_stored_invalid(event)


def effective_event_type_value(event: StoredRevenueEvent) -> str:
    if is_stored_invalid(event):
        valid = event.raw.get("valid_event_type")
        if valid:
            return str(valid)
        if event.event_type == LEGACY_SUPPRESSED_TYPE:
            return EventType.TWITCH_RESUBSCRIPTION.value
        return event.event_type.value
    return event.event_type.value


def status_label(event: StoredRevenueEvent) -> str:
    history = event.raw.get("status_history") or []
    if history:
        last = history[-1]
        action = last.get("action")
        source = last.get("source")
        if action == ACTION_INVALIDATED and source == SOURCE_MANUAL:
            return "Removed (manual)"
        if action == ACTION_VALIDATED and source == SOURCE_MANUAL:
            return "Added (manual)"
    if is_stored_invalid(event):
        if _has_auto_duplicate_reason(event):
            return "Duplicate (auto)"
        return "Invalid"
    return "Valid"


def _has_auto_duplicate_reason(event: StoredRevenueEvent) -> bool:
    history = event.raw.get("status_history") or []
    for entry in history:
        if (
            entry.get("action") == ACTION_INVALIDATED
            and entry.get("source") == SOURCE_AUTO
            and entry.get("reason") == REASON_DUPLICATE_SUB_RESUB
        ):
            return True
    return bool(event.raw.get("suppressed_duplicate_sub"))


def build_auto_invalid_raw(
    valid_event_type: str,
    *,
    base_raw: dict[str, Any] | None = None,
    reason: str = REASON_DUPLICATE_SUB_RESUB,
) -> dict[str, Any]:
    raw = deepcopy(base_raw) if base_raw else {}
    raw["valid_event_type"] = valid_event_type
    raw.pop("suppressed_duplicate_sub", None)
    history = list(raw.get("status_history") or [])
    history.append(_history_entry(ACTION_INVALIDATED, SOURCE_AUTO, reason))
    raw["status_history"] = history
    return raw


def prepare_invalidate(
    event: StoredRevenueEvent,
    *,
    reason: str = REASON_MANUAL,
    source: str = SOURCE_MANUAL,
) -> tuple[EventType, dict[str, Any]] | None:
    if is_stored_invalid(event):
        return None
    raw = deepcopy(event.raw)
    raw["valid_event_type"] = event.event_type.value
    history = list(raw.get("status_history") or [])
    history.append(_history_entry(ACTION_INVALIDATED, source, reason))
    raw["status_history"] = history
    return INVALID_EVENT_TYPE, raw


def prepare_validate(event: StoredRevenueEvent) -> tuple[EventType, dict[str, Any]] | None:
    if not is_stored_invalid(event):
        return None
    valid_type_value = effective_event_type_value(event)
    try:
        restored_type = EventType(valid_type_value)
    except ValueError:
        return None
    raw = deepcopy(event.raw)
    history = list(raw.get("status_history") or [])
    history.append(_history_entry(ACTION_VALIDATED, SOURCE_MANUAL, REASON_MANUAL))
    raw["status_history"] = history
    return restored_type, raw


def _history_entry(action: str, source: str, reason: str) -> dict[str, str]:
    return {
        "action": action,
        "source": source,
        "reason": reason,
        "at": datetime.now(timezone.utc).isoformat(),
    }
