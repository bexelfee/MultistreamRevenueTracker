import json
from pathlib import Path

import pytest

from multistream_revenue_tracker.revenue.events import EventType
from multistream_revenue_tracker.platforms.patreon_catalog import PatreonCampaignInfo, PatreonCatalog, PatreonTierInfo
from multistream_revenue_tracker.platforms.patreon_runtime import PatreonRuntime, update_patreon_campaign_id


def _runtime_with_catalog() -> PatreonRuntime:
    runtime = PatreonRuntime(Path("config.json"), "camp-1")
    runtime.catalog = PatreonCatalog(
        campaigns=[
            PatreonCampaignInfo(id="camp-1", name="Main"),
            PatreonCampaignInfo(id="camp-2", name="Other"),
        ],
        tiers_by_campaign={
            "camp-1": [PatreonTierInfo(tier_id="t1", title="Supporter", amount_cents=1000, campaign_id="camp-1")],
            "camp-2": [PatreonTierInfo(tier_id="t2", title="Basic", amount_cents=500, campaign_id="camp-2")],
        },
    )
    runtime.active_campaign_id = "camp-1"
    runtime.load_error = None
    return runtime


def test_tiers_for_ui_defaults_missing_points_to_zero():
    runtime = _runtime_with_catalog()
    rows = runtime.tiers_for_ui({EventType.PATREON_PLEDGE_CREATE.value: {"mode": "per_event_tier", "tier_points": {}}})
    assert rows == [{"tier_id": "t1", "title": "Supporter", "amount_cents": 1000, "points": 0}]


def test_tiers_for_ui_uses_saved_points():
    runtime = _runtime_with_catalog()
    rules = {EventType.PATREON_PLEDGE_CREATE.value: {"mode": "per_event_tier", "tier_points": {"1000": 42}}}
    rows = runtime.tiers_for_ui(rules)
    assert rows[0]["points"] == 42


def test_update_patreon_campaign_id_writes_config(tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps({"patreon": {"campaign_id": ""}}), encoding="utf-8")
    update_patreon_campaign_id(config_path, "camp-99")
    saved = json.loads(config_path.read_text(encoding="utf-8"))
    assert saved["patreon"]["campaign_id"] == "camp-99"


@pytest.mark.asyncio
async def test_set_active_campaign_updates_config(tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps({"patreon": {"campaign_id": "camp-1"}}), encoding="utf-8")
    runtime = _runtime_with_catalog()
    runtime._config_path = config_path
    await runtime.set_active_campaign("camp-2")
    assert runtime.active_campaign_id == "camp-2"
    assert runtime.campaign_changed.is_set()
    saved = json.loads(config_path.read_text(encoding="utf-8"))
    assert saved["patreon"]["campaign_id"] == "camp-2"
