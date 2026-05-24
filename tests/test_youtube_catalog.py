from multistream_revenue_tracker.platforms.youtube_catalog import (
    YoutubeLevelInfo,
    parse_membership_levels_response,
    resolve_level_id,
)


SAMPLE_LEVELS_RESPONSE = {
    "items": [
        {
            "id": "LEVEL_GOLD",
            "snippet": {"levelDetails": {"displayName": "Gold Member"}},
        },
        {
            "id": "LEVEL_SILVER",
            "snippet": {"levelDetails": {"displayName": "Silver"}},
        },
    ],
}


def test_parse_membership_levels_response():
    levels = parse_membership_levels_response(SAMPLE_LEVELS_RESPONSE)
    assert levels == [
        YoutubeLevelInfo(id="LEVEL_GOLD", name="Gold Member"),
        YoutubeLevelInfo(id="LEVEL_SILVER", name="Silver"),
    ]


def test_parse_membership_levels_empty():
    assert parse_membership_levels_response({}) == []
    assert parse_membership_levels_response({"items": []}) == []


def test_resolve_level_id_case_insensitive():
    levels = [
        YoutubeLevelInfo(id="LEVEL_GOLD", name="Gold Member"),
        YoutubeLevelInfo(id="LEVEL_SILVER", name="Silver"),
    ]
    assert resolve_level_id(levels, "gold member") == "LEVEL_GOLD"
    assert resolve_level_id(levels, "Silver") == "LEVEL_SILVER"
    assert resolve_level_id(levels, "Unknown") is None
    assert resolve_level_id(levels, None) is None
