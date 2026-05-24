from __future__ import annotations

import json
import re
from copy import deepcopy
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .appearance.appearance_schema import AppearanceSchema

from .appearance.bar_appearance import default_app_bar_fields, extract_bar_appearance
from .appearance.progress_effects import (
    default_app_progress_effect_fields,
    effects_catalog_for_ui,
    extract_progress_effects,
)
from .appearance.timer_appearance import default_app_timer_fields, extract_timer_appearance
from .platforms.supported_currencies import is_supported_currency
from .platforms.twitch_sub_dedupe import DEFAULT_TWITCH_SUB_RESUB_DEDUPE_SECONDS

DEFAULT_SUBATHON_POINTS = 10
DEFAULT_SUBATHON_SECONDS = 60

# Sentinel used in WS payloads so the dashboard can display "a token is set"
# without ever seeing the real secret. Saving this sentinel back is interpreted
# as "leave the existing token unchanged" (handled in clean_config_patch).
STREAMLABS_TOKEN_MASK_PREFIX = "\u2022\u2022\u2022\u2022"
STREAMLABS_TOKEN_MASK_EMPTY = ""


def mask_streamlabs_token(token: str | None) -> str:
    """Return masked form ('••••' + last 4 chars) or '' for empty tokens."""
    text = "" if token is None else str(token).strip()
    if not text:
        return STREAMLABS_TOKEN_MASK_EMPTY
    tail = text[-4:] if len(text) >= 4 else text
    return f"{STREAMLABS_TOKEN_MASK_PREFIX}{tail}"


def is_masked_streamlabs_token(value: str | None) -> bool:
    """True when ``value`` is the masked sentinel (means 'no change')."""
    if value is None:
        return False
    text = str(value)
    return text.startswith(STREAMLABS_TOKEN_MASK_PREFIX)

DEFAULT_USER_CONFIG: dict[str, Any] = {
    "app": {
        "log_chat_messages_for_testing": False,
        "base_currency": "EUR",
        "enable_test_events": False,
        "require_ws_token": False,
        "ui_port": 8080,
        "twitch_sub_resub_dedupe_seconds": DEFAULT_TWITCH_SUB_RESUB_DEDUPE_SECONDS,
        "subathon_points": DEFAULT_SUBATHON_POINTS,
        "subathon_seconds": DEFAULT_SUBATHON_SECONDS,
        **default_app_bar_fields(),
        **default_app_timer_fields(),
        **default_app_progress_effect_fields(),
    },
    "twitch": {
        "channel_name": "",
    },
    "patreon": {
        "client_id": "",
        "client_secret": "",
    },
    "streamlabs": {
        "socket_api_token": "",
    },
}

_CURRENCY_RE = re.compile(r"^[A-Z]{3}$")


def config_exists(path: Path) -> bool:
    return path.is_file()


def load_raw_config(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(
            f"Missing {path.name}. Save settings from the web UI dashboard or Configuration tab, or create it manually "
            "(see README — config.json shape)."
        )
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("config.json must be a JSON object")
    return data


def normalize_user_config(raw: dict[str, Any]) -> dict[str, Any]:
    """Merge on-disk config with defaults for user-editable fields only."""
    merged = deepcopy(DEFAULT_USER_CONFIG)
    app = raw.get("app")
    if isinstance(app, dict):
        for key in DEFAULT_USER_CONFIG["app"]:
            if key in app:
                merged["app"][key] = app[key]
    tw = raw.get("twitch")
    if isinstance(tw, dict):
        for key in DEFAULT_USER_CONFIG["twitch"]:
            if key in tw:
                merged["twitch"][key] = tw[key]
    pa = raw.get("patreon")
    if isinstance(pa, dict):
        if "campaign_id" in pa:
            merged["patreon"]["campaign_id"] = pa["campaign_id"]
        for key in ("client_id", "client_secret"):
            if key in pa:
                merged["patreon"][key] = str(pa[key] or "").strip()
    sl = raw.get("streamlabs")
    if isinstance(sl, dict):
        for key in DEFAULT_USER_CONFIG["streamlabs"]:
            if key in sl:
                merged["streamlabs"][key] = sl[key]
    return merged


def normalized_user_config_for_ui(normalized: dict[str, Any]) -> dict[str, Any]:
    streamlabs = dict(normalized.get("streamlabs") or {})
    # Replace the real Streamlabs token with a masked sentinel before sending
    # the payload over the WebSocket. The dashboard treats the sentinel as
    # "leave unchanged" when the user saves the form.
    if "socket_api_token" in streamlabs:
        streamlabs["socket_api_token"] = mask_streamlabs_token(streamlabs.get("socket_api_token"))
    patreon = dict(normalized.get("patreon") or DEFAULT_USER_CONFIG["patreon"])
    if patreon.get("client_secret"):
        patreon["client_secret"] = mask_streamlabs_token(patreon.get("client_secret"))
    return {
        "app": dict(normalized["app"]),
        "twitch": dict(normalized["twitch"]),
        "patreon": patreon,
        "streamlabs": streamlabs,
        "bar_appearance": extract_bar_appearance(normalized.get("app")),
        "timer_appearance": extract_timer_appearance(normalized.get("app")),
        "progress_effects": extract_progress_effects(normalized.get("app")),
        "effects_catalog": effects_catalog_for_ui(),
    }


def clean_config_patch(patch: dict[str, Any]) -> dict[str, Any]:
    """Validate types and normalize a config.save payload; returns cleaned partial patch."""
    if not isinstance(patch, dict):
        raise ValueError("config must be an object")

    cleaned: dict[str, Any] = {}
    app = patch.get("app")
    if app is not None:
        if not isinstance(app, dict):
            raise ValueError("app must be an object")
        cleaned_app: dict[str, Any] = {}
        for key in ("log_chat_messages_for_testing", "enable_test_events", "require_ws_token"):
            if key in app:
                cleaned_app[key] = bool(app[key])
        if "base_currency" in app:
            currency = str(app["base_currency"] or "").strip().upper()
            if not _CURRENCY_RE.match(currency):
                raise ValueError("base_currency must be a 3-letter code (e.g. EUR)")
            if not is_supported_currency(currency):
                raise ValueError(f"base_currency {currency!r} is not in the supported currency list")
            cleaned_app["base_currency"] = currency
        if "ui_port" in app:
            port = int(app["ui_port"])
            if port < 1024 or port > 65535:
                raise ValueError("ui_port must be between 1024 and 65535")
            cleaned_app["ui_port"] = port
        if "twitch_sub_resub_dedupe_seconds" in app:
            seconds = int(app["twitch_sub_resub_dedupe_seconds"])
            if seconds < 0 or seconds > 3600:
                raise ValueError("twitch_sub_resub_dedupe_seconds must be between 0 and 3600")
            cleaned_app["twitch_sub_resub_dedupe_seconds"] = seconds
        for key in ("subathon_points", "subathon_seconds"):
            if key in app:
                value = int(app[key])
                if value < 1:
                    raise ValueError(f"{key} must be at least 1")
                cleaned_app[key] = value
        cleaned["app"] = cleaned_app

    bar_appearance = patch.get("bar_appearance")
    if bar_appearance is not None:
        from .appearance.bar_appearance import clean_bar_appearance_patch

        bar_patch = clean_bar_appearance_patch(bar_appearance)
        cleaned.setdefault("app", {}).update(bar_patch)

    tw = patch.get("twitch")
    if tw is not None:
        if not isinstance(tw, dict):
            raise ValueError("twitch must be an object")
        cleaned_tw: dict[str, Any] = {}
        if "channel_name" in tw:
            cleaned_tw["channel_name"] = str(tw["channel_name"]).strip().lstrip("#")
        if cleaned_tw:
            cleaned["twitch"] = cleaned_tw

    sl = patch.get("streamlabs")
    if sl is not None:
        if not isinstance(sl, dict):
            raise ValueError("streamlabs must be an object")
        cleaned_sl: dict[str, Any] = {}
        if "socket_api_token" in sl:
            raw_token = str(sl["socket_api_token"]).strip()
            # Receiving the masked sentinel back from the dashboard means the
            # user didn't edit the field — skip it so the real token is kept.
            if not is_masked_streamlabs_token(raw_token):
                cleaned_sl["socket_api_token"] = raw_token
        if cleaned_sl:
            cleaned["streamlabs"] = cleaned_sl

    pa = patch.get("patreon")
    if pa is not None:
        if not isinstance(pa, dict):
            raise ValueError("patreon must be an object")
        cleaned_pa: dict[str, Any] = {}
        if "client_id" in pa:
            cleaned_pa["client_id"] = str(pa["client_id"]).strip()
        if "client_secret" in pa:
            raw_secret = str(pa["client_secret"]).strip()
            if not is_masked_streamlabs_token(raw_secret):
                cleaned_pa["client_secret"] = raw_secret
        if cleaned_pa:
            cleaned["patreon"] = cleaned_pa

    return cleaned


def validate_config_patch(patch: dict[str, Any]) -> dict[str, Any]:
    """Validate a full config payload (e.g. from UI) including enable/requirement rules."""
    cleaned = clean_config_patch(patch)
    merged = deepcopy(DEFAULT_USER_CONFIG)
    _deep_merge(merged, cleaned)
    _validate_user_config_requirements(merged)
    return cleaned


def _validate_user_config_requirements(merged: dict[str, Any]) -> None:
    currency = str(merged["app"].get("base_currency") or "").strip().upper()
    if not currency or not _CURRENCY_RE.match(currency):
        raise ValueError("Base currency is required (3-letter code, e.g. EUR)")
    if not is_supported_currency(currency):
        raise ValueError(f"base_currency {currency!r} is not in the supported currency list")
    port = merged["app"].get("ui_port")
    if port is not None:
        port_int = int(port)
        if port_int < 1024 or port_int > 65535:
            raise ValueError("ui_port must be between 1024 and 65535")


def _save_appearance_via_schema(
    path: Path, schema: "AppearanceSchema", patch: dict[str, Any],
) -> dict[str, Any]:
    """Shared body for bar/timer/progress-effects saves.

    Each was a near-identical "clean patch → merge into app section → normalize
    → atomic-write" sequence; this collapses the three to a single function
    parameterised by schema. ``AppearanceSchema.clean_patch`` raises
    ValueError on bad input, matching the previous behaviour exactly.
    """
    cleaned_app = schema.clean_patch(patch)
    if path.is_file():
        raw = load_raw_config(path)
    else:
        raw = deepcopy(DEFAULT_USER_CONFIG)
    target = raw.setdefault("app", {})
    if not isinstance(target, dict):
        target = {}
        raw["app"] = target
    target.update(cleaned_app)
    normalized = normalize_user_config(raw)
    _validate_user_config_requirements(normalized)
    _write_json_atomic(path, raw)
    return normalized


def save_timer_appearance(path: Path, appearance: dict[str, Any]) -> dict[str, Any]:
    """Persist timer appearance fields under app in config.json."""
    from .appearance.timer_appearance import TIMER_APPEARANCE_SCHEMA

    return _save_appearance_via_schema(path, TIMER_APPEARANCE_SCHEMA, appearance)


def save_progress_effects(path: Path, effects: dict[str, Any]) -> dict[str, Any]:
    """Persist progress effect selections under app in config.json."""
    from .appearance.progress_effects import PROGRESS_EFFECTS_SCHEMA

    return _save_appearance_via_schema(path, PROGRESS_EFFECTS_SCHEMA, effects)


def save_bar_appearance(path: Path, appearance: dict[str, Any]) -> dict[str, Any]:
    """Persist bar appearance fields under app in config.json."""
    from .appearance.bar_appearance import BAR_APPEARANCE_SCHEMA

    return _save_appearance_via_schema(path, BAR_APPEARANCE_SCHEMA, appearance)


def save_user_config(path: Path, patch: dict[str, Any]) -> dict[str, Any]:
    cleaned = clean_config_patch(patch)
    if path.is_file():
        raw = load_raw_config(path)
    else:
        raw = deepcopy(DEFAULT_USER_CONFIG)
    _deep_merge_user_fields(raw, cleaned)
    normalized = normalize_user_config(raw)
    _validate_user_config_requirements(normalized)
    _write_json_atomic(path, raw)
    return normalized


def merge_user_into_raw(raw: dict[str, Any], patch: dict[str, Any]) -> None:
    _deep_merge_user_fields(raw, patch)


def _deep_merge_user_fields(raw: dict[str, Any], patch: dict[str, Any]) -> None:
    if "app" in patch:
        target = raw.setdefault("app", {})
        if not isinstance(target, dict):
            target = {}
            raw["app"] = target
        for key in DEFAULT_USER_CONFIG["app"]:
            if key in patch["app"]:
                target[key] = patch["app"][key]
    if "twitch" in patch:
        target = raw.setdefault("twitch", {})
        if not isinstance(target, dict):
            target = {}
            raw["twitch"] = target
        for key in DEFAULT_USER_CONFIG["twitch"]:
            if key in patch["twitch"]:
                target[key] = patch["twitch"][key]
    if "streamlabs" in patch:
        target = raw.setdefault("streamlabs", {})
        if not isinstance(target, dict):
            target = {}
            raw["streamlabs"] = target
        for key in DEFAULT_USER_CONFIG["streamlabs"]:
            if key in patch["streamlabs"]:
                target[key] = patch["streamlabs"][key]
    if "patreon" in patch:
        target = raw.setdefault("patreon", {})
        if not isinstance(target, dict):
            target = {}
            raw["patreon"] = target
        for key in ("client_id", "client_secret"):
            if key in patch["patreon"]:
                target[key] = patch["patreon"][key]
        if "campaign_id" in patch["patreon"]:
            target["campaign_id"] = patch["patreon"]["campaign_id"]


def _deep_merge(base: dict[str, Any], patch: dict[str, Any]) -> None:
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value


def _write_json_atomic(path: Path, data: dict[str, Any]) -> None:
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    temp.replace(path)
