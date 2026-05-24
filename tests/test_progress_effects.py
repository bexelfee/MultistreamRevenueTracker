import pytest

from multistream_revenue_tracker.appearance.progress_effects import (
    clean_progress_effects_patch,
    default_app_progress_effect_fields,
    extract_progress_effects,
)


def test_default_app_progress_effect_fields():
    assert default_app_progress_effect_fields() == {
        "goal_complete_effect": "confetti",
        "points_added_effect": "none",
        "goal_complete_repeat": True,
    }


def test_extract_progress_effects_defaults():
    assert extract_progress_effects({}) == {
        "goal_complete": "confetti",
        "points_added": "none",
        "goal_complete_repeat": True,
    }


def test_extract_progress_effects_from_app():
    app = {
        "goal_complete_effect": "glow",
        "points_added_effect": "bar_flash",
        "goal_complete_repeat": False,
    }
    assert extract_progress_effects(app) == {
        "goal_complete": "glow",
        "points_added": "bar_flash",
        "goal_complete_repeat": False,
    }


def test_extract_migrates_legacy_goal_effects():
    assert extract_progress_effects({"goal_complete_effect": "pulse"})["goal_complete"] == "none"
    assert extract_progress_effects({"goal_complete_effect": "stripe_finish"})["goal_complete"] == "finish_shine"


def test_extract_migrates_legacy_points_effects():
    assert extract_progress_effects({"points_added_effect": "bar_nudge"})["points_added"] == "none"
    assert extract_progress_effects({"points_added_effect": "points_ripple"})["points_added"] == "none"


def test_clean_progress_effects_patch_goal_complete():
    cleaned = clean_progress_effects_patch({"goal_complete": "glow"})
    assert cleaned == {"goal_complete_effect": "glow"}


def test_clean_progress_effects_patch_points_added():
    cleaned = clean_progress_effects_patch({"points_added": "number_pop"})
    assert cleaned == {"points_added_effect": "number_pop"}


def test_clean_progress_effects_patch_repeat_toggle():
    cleaned = clean_progress_effects_patch({"goal_complete_repeat": False})
    assert cleaned == {"goal_complete_repeat": False}


def test_clean_progress_effects_patch_accepts_confetti():
    cleaned = clean_progress_effects_patch({"goal_complete": "confetti"})
    assert cleaned == {"goal_complete_effect": "confetti"}


def test_clean_progress_effects_patch_rejects_invalid_goal():
    with pytest.raises(ValueError, match="goal_complete"):
        clean_progress_effects_patch({"goal_complete": "sparkle"})


def test_clean_progress_effects_patch_rejects_invalid_points():
    with pytest.raises(ValueError, match="points_added"):
        clean_progress_effects_patch({"points_added": "sparkle"})


def test_clean_progress_effects_patch_empty():
    with pytest.raises(ValueError, match="empty"):
        clean_progress_effects_patch({})
