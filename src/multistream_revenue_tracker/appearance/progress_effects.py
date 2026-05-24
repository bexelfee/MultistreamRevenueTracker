"""Curated CSS progress bar effects (goal complete and points added).

Defined via the shared ``AppearanceSchema`` so the WS save handler and
``config_store.save_progress_effects`` use the same codepath as the bar
and timer appearance modules. The catalog of valid effect IDs and the
legacy-id mapping live in this file because they have UI semantics
(catalog → dashboard dropdown).
"""

from __future__ import annotations

from typing import Any

from .appearance_schema import AppearanceSchema, Field, normalize_bool

EFFECT_NONE = "none"

GOAL_COMPLETE_EFFECTS: list[dict[str, str]] = [
    {"id": EFFECT_NONE, "label": "None", "description": "No animation when the goal is reached."},
    {"id": "glow", "label": "Glow", "description": "Soft pulsing glow around the bar track."},
    {"id": "finish_shine", "label": "Finish shine", "description": "Bright sweep across the completed bar."},
    {"id": "ring_burst", "label": "Ring burst", "description": "Expanding highlight ring on the bar track."},
    {"id": "confetti", "label": "Confetti", "description": "Colorful burst of falling confetti over the bar."},
]

POINTS_ADDED_EFFECTS: list[dict[str, str]] = [
    {"id": EFFECT_NONE, "label": "None", "description": "No animation when points increase."},
    {"id": "bar_flash", "label": "Bar flash", "description": "Brief bright flash on the bar fill."},
    {"id": "number_pop", "label": "Number pop", "description": "Points caption scales up briefly."},
    {"id": "caption_glow", "label": "Caption glow", "description": "Points text glows briefly."},
]

_GOAL_COMPLETE_IDS = {item["id"] for item in GOAL_COMPLETE_EFFECTS}
_POINTS_ADDED_IDS = {item["id"] for item in POINTS_ADDED_EFFECTS}

# Renamed/removed effects from earlier releases; map silently to keep older
# config.json files loading without an error popup.
_LEGACY_GOAL_EFFECTS: dict[str, str] = {
    "pulse": EFFECT_NONE,
    "stripe_finish": "finish_shine",
}

_LEGACY_POINTS_EFFECTS: dict[str, str] = {
    "bar_nudge": EFFECT_NONE,
    "points_ripple": EFFECT_NONE,
}

DEFAULT_GOAL_COMPLETE_EFFECT = "confetti"
DEFAULT_POINTS_ADDED_EFFECT = EFFECT_NONE
DEFAULT_GOAL_COMPLETE_REPEAT = True


def effects_catalog_for_ui() -> dict[str, list[dict[str, str]]]:
    return {
        "goal_complete": list(GOAL_COMPLETE_EFFECTS),
        "points_added": list(POINTS_ADDED_EFFECTS),
    }


def _effect_normalizer(
    field_label: str, allowed: set[str], legacy: dict[str, str], *, strict: bool,
):
    """Build a normalizer that returns ``default`` (loose) or raises (strict).

    Loose mode is used when loading from disk: an unknown id is logged-silent
    and replaced with the default, so a corrupt config still boots. Strict
    mode is used when accepting a UI patch: unknown ids must be a user error
    and surfaced — the error message includes ``field_label`` so the caller
    knows which dropdown was rejected.
    """
    def _normalize(value: Any, default: Any) -> str:
        text = str(value or default).strip()
        if text in allowed:
            return text
        if text in legacy:
            return legacy[text]
        if strict:
            raise ValueError(
                f"{field_label} effect must be one of: {', '.join(sorted(allowed))}",
            )
        return str(default)
    return _normalize


PROGRESS_EFFECTS_SCHEMA = AppearanceSchema(
    name="progress_effects",
    fields=(
        Field(
            "goal_complete", "goal_complete_effect", DEFAULT_GOAL_COMPLETE_EFFECT,
            _effect_normalizer("goal_complete", _GOAL_COMPLETE_IDS, _LEGACY_GOAL_EFFECTS, strict=False),
            _effect_normalizer("goal_complete", _GOAL_COMPLETE_IDS, _LEGACY_GOAL_EFFECTS, strict=True),
        ),
        Field(
            "points_added", "points_added_effect", DEFAULT_POINTS_ADDED_EFFECT,
            _effect_normalizer("points_added", _POINTS_ADDED_IDS, _LEGACY_POINTS_EFFECTS, strict=False),
            _effect_normalizer("points_added", _POINTS_ADDED_IDS, _LEGACY_POINTS_EFFECTS, strict=True),
        ),
        Field(
            "goal_complete_repeat", "goal_complete_repeat", DEFAULT_GOAL_COMPLETE_REPEAT,
            normalize_bool, normalize_bool,
        ),
    ),
)


def default_app_progress_effect_fields() -> dict[str, Any]:
    return PROGRESS_EFFECTS_SCHEMA.default_app_fields()


def extract_progress_effects(app_section: dict[str, Any] | None) -> dict[str, Any]:
    return PROGRESS_EFFECTS_SCHEMA.extract(app_section)


def clean_progress_effects_patch(patch: dict[str, Any]) -> dict[str, Any]:
    return PROGRESS_EFFECTS_SCHEMA.clean_patch(patch)
