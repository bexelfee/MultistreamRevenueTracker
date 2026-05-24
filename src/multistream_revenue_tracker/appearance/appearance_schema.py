"""Shared schema-driven helper for the three appearance domains.

Bar / timer / progress-effects each used to define their own
``default_*_fields()`` + ``extract_*()`` + ``clean_*_patch()`` + ``save_*()``
triple. This module collapses all of that into one ``AppearanceSchema``
dataclass and three ``Field`` records per domain, so adding a new field is
one line in the schema and every code path (defaults, UI projection, patch
cleaning, save) picks it up automatically.

The same schemas are imported by ``ui/ws/handlers_appearance.py`` which
drives all three save handlers from a single parametric implementation.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


# A normalizer takes (raw_value, default) and returns the cleaned value.
# For bar/timer the same normalizer is used during both extract (forgiving)
# and clean (forgiving by default), but progress_effects passes a stricter
# function for clean so an unknown effect id is rejected with ValueError.
Normalizer = Callable[[Any, Any], Any]


@dataclass(frozen=True)
class Field:
    """One stored field in an appearance schema.

    ``ui_key`` is the name seen by frontend (e.g. ``"fill_color"``).
    ``app_key`` is the underlying config.json ``app.*`` key
    (e.g. ``"bar_fill_color"``) — flat because the file format was decided
    pre-redesign and changing it costs upgrade churn for zero behaviour.
    ``extract`` normalizes when reading from disk (must not raise).
    ``clean`` normalizes when accepting a UI patch (may raise ValueError).
    """

    ui_key: str
    app_key: str
    default: Any
    extract: Normalizer
    clean: Normalizer


@dataclass(frozen=True)
class AppearanceSchema:
    name: str  # "bar_appearance" — used in error messages
    fields: tuple[Field, ...]

    def default_app_fields(self) -> dict[str, Any]:
        """Defaults keyed by ``app_key`` — embedded in config.json."""
        return {f.app_key: f.default for f in self.fields}

    def extract(self, app_section: dict[str, Any] | None) -> dict[str, Any]:
        """Project ``app.*`` fields to the UI shape (forgiving)."""
        app = app_section if isinstance(app_section, dict) else {}
        return {
            f.ui_key: f.extract(app.get(f.app_key), f.default) for f in self.fields
        }

    def clean_patch(self, patch: Any) -> dict[str, Any]:
        """Validate a UI patch and return the corresponding ``app.*`` keys.

        Raises ValueError if the patch shape is wrong or empty; otherwise
        unknown keys are silently dropped so a stale dashboard cannot prevent
        a save.
        """
        if not isinstance(patch, dict):
            raise ValueError(f"{self.name} must be an object")
        keys_by_ui = {f.ui_key: f for f in self.fields}
        cleaned: dict[str, Any] = {}
        for ui_key, value in patch.items():
            spec = keys_by_ui.get(ui_key)
            if spec is None:
                continue
            cleaned[spec.app_key] = spec.clean(value, spec.default)
        if not cleaned:
            raise ValueError(f"{self.name} patch is empty")
        return cleaned

    def ui_defaults(self) -> dict[str, Any]:
        """Defaults projected into UI shape — used for fallback rendering."""
        return {f.ui_key: f.default for f in self.fields}


# --- Common normalizers ------------------------------------------------------


def normalize_bool(value: Any, default: Any) -> bool:
    if value is None:
        return bool(default)
    return bool(value)
