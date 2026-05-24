import json
from pathlib import Path

from multistream_revenue_tracker.platforms.patreon_catalog import parse_campaigns_payload


def test_parse_campaigns_groups_published_tiers():
    payload = json.loads((Path(__file__).parent / "fixtures" / "patreon_campaigns.json").read_text(encoding="utf-8"))
    catalog = parse_campaigns_payload(payload)
    assert [c.id for c in catalog.campaigns] == ["camp-1", "camp-2"]
    assert len(catalog.tiers_by_campaign["camp-1"]) == 1
    assert catalog.tiers_by_campaign["camp-1"][0].title == "Supporter"
    assert catalog.tiers_by_campaign["camp-1"][0].amount_cents == 1000
    assert catalog.resolve_active_campaign_id("camp-2") == "camp-2"
    assert catalog.resolve_active_campaign_id("") == "camp-1"
