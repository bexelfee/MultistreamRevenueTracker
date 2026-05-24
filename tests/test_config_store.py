import json

from pathlib import Path



import pytest



from multistream_revenue_tracker.config import load_config, user_config_for_ui

from multistream_revenue_tracker.config_store import normalize_user_config, save_user_config, validate_config_patch





def _write_config(path: Path, data: dict) -> None:

    path.write_text(json.dumps(data, indent=2), encoding="utf-8")





def test_normalize_user_config_defaults():

    user = normalize_user_config({})

    assert "enable_twitch" not in user["app"]
    assert user["app"]["enable_test_events"] is False

    assert user["app"]["log_chat_messages_for_testing"] is False

    assert user["app"]["ui_port"] == 8080
    assert user["streamlabs"]["socket_api_token"] == ""


def test_clean_config_patch_streamlabs_token():
    cleaned = validate_config_patch(
        {"streamlabs": {"socket_api_token": "  my-token  "}}
    )
    assert cleaned["streamlabs"]["socket_api_token"] == "my-token"





def test_save_user_config_merge(tmp_path):

    config_path = tmp_path / "config.json"

    _write_config(

        config_path,

        {

            "app": {"enable_twitch": True, "enable_youtube": True, "enable_patreon": False},

            "twitch": {"channel_name": "ch"},

            "patreon": {"campaign_id": "camp1"},

        },

    )

    save_user_config(

        config_path,

        {

            "app": {"enable_test_events": True, "base_currency": "GBP"},

            "twitch": {"channel_name": "newch"},

        },

    )

    raw = json.loads(config_path.read_text(encoding="utf-8"))

    assert raw["app"]["enable_test_events"] is True

    assert raw["app"]["base_currency"] == "GBP"

    assert raw["twitch"]["channel_name"] == "newch"

    assert raw["patreon"]["campaign_id"] == "camp1"





def test_validate_allows_empty_twitch_channel():

    """Channel name is required at connect time, not when saving configuration."""

    cleaned = validate_config_patch({"twitch": {"channel_name": ""}})

    assert cleaned["twitch"]["channel_name"] == ""





def test_validate_base_currency_supported():

    with pytest.raises(ValueError, match="supported currency"):

        validate_config_patch({"app": {"base_currency": "ZZZ"}})





def test_validate_ui_port_range():

    with pytest.raises(ValueError, match="ui_port"):

        validate_config_patch({"app": {"ui_port": 80}})





def test_user_config_for_ui_shape(tmp_path):

    config_path = tmp_path / "config.json"

    _write_config(

        config_path,

        {

            "app": {

                "enable_twitch": False,

                "enable_youtube": False,

                "enable_patreon": False,

                "enable_test_events": False,

            },

            "twitch": {"channel_name": "me"},

        },

    )

    cfg = load_config(config_path)

    ui = user_config_for_ui(cfg)

    assert "app" in ui and "twitch" in ui

    assert ui["twitch"]["channel_name"] == "me"

    assert "client_id" not in ui["twitch"]

