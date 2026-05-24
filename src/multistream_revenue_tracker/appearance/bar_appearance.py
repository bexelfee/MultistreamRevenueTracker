"""Progress-bar appearance (colors, font, decimals) — schema-driven.

The public surface (``DEFAULT_BAR_APPEARANCE``, ``default_app_bar_fields``,
``extract_bar_appearance``, ``clean_bar_appearance_patch``,
``bar_fill_background``, ``BAR_FONT_OPTIONS``) is preserved; the
implementation is now a thin wrapper around ``AppearanceSchema`` so future
fields cost one ``Field`` row in this module.
"""

from __future__ import annotations

import re
from typing import Any

from .appearance_schema import AppearanceSchema, Field, normalize_bool

_HEX_COLOR_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")

DEFAULT_BAR_APPEARANCE: dict[str, Any] = {
    "fill_color": "#FFA8BC",
    "gradient_color": "#22C55E",
    "use_gradient": False,
    "font_family": "system-ui, Segoe UI, sans-serif",
    "show_decimals": False,
}

BAR_FONT_OPTIONS: list[dict[str, str]] = [
    {"id": "system", "label": "System UI", "value": "system-ui, Segoe UI, sans-serif"},
    {"id": "arial", "label": "Arial", "value": "Arial, Helvetica, sans-serif"},
    {"id": "verdana", "label": "Verdana", "value": "Verdana, Geneva, sans-serif"},
    {"id": "trebuchet", "label": "Trebuchet MS", "value": "'Trebuchet MS', Helvetica, sans-serif"},
    {"id": "georgia", "label": "Georgia", "value": "Georgia, 'Times New Roman', serif"},
    {"id": "courier", "label": "Courier New", "value": "'Courier New', Courier, monospace"},
    {"id": "impact", "label": "Impact", "value": "Impact, Haettenschweiler, sans-serif"},
]

_ALLOWED_FONT_VALUES: frozenset[str] = frozenset(opt["value"] for opt in BAR_FONT_OPTIONS)


def _normalize_hex(value: Any, default: Any) -> str:
    text = str(value or "").strip()
    if not text.startswith("#"):
        text = f"#{text}"
    if _HEX_COLOR_RE.match(text):
        return text.upper()
    if len(text) == 4 and text.startswith("#"):
        # #RGB -> #RRGGBB
        r, g, b = text[1], text[2], text[3]
        expanded = f"#{r}{r}{g}{g}{b}{b}".upper()
        if _HEX_COLOR_RE.match(expanded):
            return expanded
    return str(default).upper()


def _normalize_font(value: Any, default: Any) -> str:
    """Reject any font value not in BAR_FONT_OPTIONS to prevent CSS injection."""
    text = str(value or "").strip()
    if text in _ALLOWED_FONT_VALUES:
        return text
    return str(default)


BAR_APPEARANCE_SCHEMA = AppearanceSchema(
    name="bar_appearance",
    fields=(
        Field("fill_color", "bar_fill_color", DEFAULT_BAR_APPEARANCE["fill_color"], _normalize_hex, _normalize_hex),
        Field("gradient_color", "bar_gradient_color", DEFAULT_BAR_APPEARANCE["gradient_color"], _normalize_hex, _normalize_hex),
        Field("use_gradient", "bar_use_gradient", DEFAULT_BAR_APPEARANCE["use_gradient"], normalize_bool, normalize_bool),
        Field("font_family", "bar_font_family", DEFAULT_BAR_APPEARANCE["font_family"], _normalize_font, _normalize_font),
        Field("show_decimals", "bar_show_decimals", DEFAULT_BAR_APPEARANCE["show_decimals"], normalize_bool, normalize_bool),
    ),
)


def default_app_bar_fields() -> dict[str, Any]:
    return BAR_APPEARANCE_SCHEMA.default_app_fields()


def extract_bar_appearance(app_section: dict[str, Any] | None) -> dict[str, Any]:
    """Map config app.* bar_* keys to UI bar_appearance object."""
    return BAR_APPEARANCE_SCHEMA.extract(app_section)


def clean_bar_appearance_patch(patch: dict[str, Any]) -> dict[str, Any]:
    return BAR_APPEARANCE_SCHEMA.clean_patch(patch)


def bar_fill_background(appearance: dict[str, Any]) -> str:
    fill = _normalize_hex(appearance.get("fill_color"), DEFAULT_BAR_APPEARANCE["fill_color"])
    if appearance.get("use_gradient"):
        end = _normalize_hex(
            appearance.get("gradient_color"), DEFAULT_BAR_APPEARANCE["gradient_color"],
        )
        return f"linear-gradient(90deg, {fill}, {end})"
    return fill
