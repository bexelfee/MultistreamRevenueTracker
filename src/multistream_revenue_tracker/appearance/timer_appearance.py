"""Subathon timer overlay appearance (font, colour, display mode).

Implemented via the shared ``AppearanceSchema``; the historical public API
(``DEFAULT_TIMER_APPEARANCE`` / ``default_app_timer_fields`` /
``extract_timer_appearance`` / ``clean_timer_appearance_patch``) is
preserved.
"""

from __future__ import annotations

from typing import Any

from .appearance_schema import AppearanceSchema, Field, normalize_bool
from .bar_appearance import _normalize_font, _normalize_hex  # reused validators

DEFAULT_TIMER_APPEARANCE: dict[str, Any] = {
    "font_family": "system-ui, Segoe UI, sans-serif",
    "font_color": "#FFFFFF",
    "show_days": False,
}


TIMER_APPEARANCE_SCHEMA = AppearanceSchema(
    name="timer_appearance",
    fields=(
        Field("font_family", "subathon_font_family", DEFAULT_TIMER_APPEARANCE["font_family"], _normalize_font, _normalize_font),
        Field("font_color", "subathon_font_color", DEFAULT_TIMER_APPEARANCE["font_color"], _normalize_hex, _normalize_hex),
        Field("show_days", "subathon_show_days", DEFAULT_TIMER_APPEARANCE["show_days"], normalize_bool, normalize_bool),
    ),
)


def default_app_timer_fields() -> dict[str, Any]:
    return TIMER_APPEARANCE_SCHEMA.default_app_fields()


def extract_timer_appearance(app_section: dict[str, Any] | None) -> dict[str, Any]:
    return TIMER_APPEARANCE_SCHEMA.extract(app_section)


def clean_timer_appearance_patch(patch: dict[str, Any]) -> dict[str, Any]:
    return TIMER_APPEARANCE_SCHEMA.clean_patch(patch)
