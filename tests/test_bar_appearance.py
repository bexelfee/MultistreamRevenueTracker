import json
from pathlib import Path

import pytest

from multistream_revenue_tracker.appearance.bar_appearance import (
    DEFAULT_BAR_APPEARANCE,
    bar_fill_background,
    clean_bar_appearance_patch,
    extract_bar_appearance,
)
from multistream_revenue_tracker.config_store import normalize_user_config, save_bar_appearance


def test_bar_fill_background_solid():
    assert bar_fill_background({"fill_color": "#FFA8BC", "use_gradient": False}) == "#FFA8BC"


def test_bar_fill_background_gradient():
    bg = bar_fill_background({
        "fill_color": "#FFA8BC",
        "gradient_color": "#22C55E",
        "use_gradient": True,
    })
    assert bg == "linear-gradient(90deg, #FFA8BC, #22C55E)"


def test_clean_bar_appearance_patch_normalizes_hex():
    cleaned = clean_bar_appearance_patch({"fill_color": "#abc", "use_gradient": True})
    assert cleaned["bar_fill_color"] == "#AABBCC"
    assert cleaned["bar_use_gradient"] is True


def test_save_bar_appearance_persists(tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "app": {
                    "enable_twitch": True,
                    "enable_youtube": True,
                    "base_currency": "EUR",
                },
                "twitch": {"channel_name": "ch"},
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    save_bar_appearance(
        config_path,
        {
            "fill_color": "#FF00AA",
            "gradient_color": "#00FF00",
            "use_gradient": False,
            "font_family": "Arial, Helvetica, sans-serif",
        },
    )
    raw = json.loads(config_path.read_text(encoding="utf-8"))
    assert raw["app"]["bar_fill_color"] == "#FF00AA"
    assert raw["app"]["bar_font_family"] == "Arial, Helvetica, sans-serif"
    normalized = normalize_user_config(raw)
    ui = extract_bar_appearance(normalized["app"])
    assert ui["fill_color"] == "#FF00AA"
    assert ui["font_family"] == "Arial, Helvetica, sans-serif"


def test_extract_bar_appearance_show_decimals():
    ui = extract_bar_appearance({"bar_show_decimals": True})
    assert ui["show_decimals"] is True


def test_clean_bar_appearance_patch_show_decimals():
    cleaned = clean_bar_appearance_patch({"show_decimals": True})
    assert cleaned["bar_show_decimals"] is True


def test_normalize_includes_bar_defaults():
    user = normalize_user_config({})
    assert user["app"]["bar_fill_color"] == DEFAULT_BAR_APPEARANCE["fill_color"]
    assert user["app"]["bar_show_decimals"] == DEFAULT_BAR_APPEARANCE["show_decimals"]
