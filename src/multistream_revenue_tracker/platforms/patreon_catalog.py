from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class PatreonCampaignInfo:
    id: str
    name: str


@dataclass(frozen=True)
class PatreonTierInfo:
    tier_id: str
    title: str
    amount_cents: int
    campaign_id: str


@dataclass
class PatreonCatalog:
    campaigns: list[PatreonCampaignInfo] = field(default_factory=list)
    tiers_by_campaign: dict[str, list[PatreonTierInfo]] = field(default_factory=dict)

    def campaign_ids(self) -> list[str]:
        return [c.id for c in self.campaigns]

    def resolve_active_campaign_id(self, preferred: str) -> str | None:
        ids = self.campaign_ids()
        if not ids:
            return None
        if preferred and preferred in ids:
            return preferred
        return ids[0]

    def tiers_for_campaign(self, campaign_id: str) -> list[PatreonTierInfo]:
        return list(self.tiers_by_campaign.get(campaign_id, []))


def parse_campaigns_payload(payload: dict[str, Any]) -> PatreonCatalog:
    included = payload.get("included") or []
    tier_by_id: dict[str, dict[str, Any]] = {}
    for item in included:
        if item.get("type") == "tier":
            tier_by_id[str(item["id"])] = item

    campaigns: list[PatreonCampaignInfo] = []
    tiers_by_campaign: dict[str, list[PatreonTierInfo]] = {}

    for campaign in payload.get("data") or []:
        if campaign.get("type") != "campaign":
            continue
        campaign_id = str(campaign["id"])
        attrs = campaign.get("attributes") or {}
        name = (attrs.get("creation_name") or attrs.get("name") or campaign_id).strip()
        campaigns.append(PatreonCampaignInfo(id=campaign_id, name=name))
        tiers_by_campaign[campaign_id] = []

        rel = (campaign.get("relationships") or {}).get("tiers") or {}
        tier_refs = rel.get("data") or []
        for ref in tier_refs:
            tier = tier_by_id.get(str(ref.get("id")))
            if tier is None:
                continue
            parsed = _parse_tier(tier, campaign_id)
            if parsed is not None:
                tiers_by_campaign[campaign_id].append(parsed)

    for tier in tier_by_id.values():
        attrs = tier.get("attributes") or {}
        if attrs.get("published") is not True:
            continue
        rel = (tier.get("relationships") or {}).get("campaign") or {}
        campaign_ref = rel.get("data") or {}
        campaign_id = str(campaign_ref.get("id") or "")
        if not campaign_id or campaign_id not in tiers_by_campaign:
            continue
        parsed = _parse_tier(tier, campaign_id)
        if parsed is None:
            continue
        existing = {t.tier_id for t in tiers_by_campaign[campaign_id]}
        if parsed.tier_id not in existing:
            tiers_by_campaign[campaign_id].append(parsed)

    for campaign_id in tiers_by_campaign:
        tiers_by_campaign[campaign_id].sort(key=lambda t: t.amount_cents)

    campaigns.sort(key=lambda c: c.name.lower())
    return PatreonCatalog(campaigns=campaigns, tiers_by_campaign=tiers_by_campaign)


def _parse_tier(tier: dict[str, Any], campaign_id: str) -> PatreonTierInfo | None:
    attrs = tier.get("attributes") or {}
    if attrs.get("published") is not True:
        return None
    amount = attrs.get("amount_cents")
    if amount is None:
        return None
    try:
        amount_cents = int(amount)
    except (TypeError, ValueError):
        return None
    title = (attrs.get("title") or "").strip() or f"${amount_cents / 100:.2f}/mo"
    return PatreonTierInfo(
        tier_id=str(tier["id"]),
        title=title,
        amount_cents=amount_cents,
        campaign_id=campaign_id,
    )
