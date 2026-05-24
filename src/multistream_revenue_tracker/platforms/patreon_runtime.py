from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

from ..config import update_patreon_campaign_id
from ..revenue.events import EventType
from .patreon_catalog import PatreonCatalog, PatreonTierInfo
from .patreon_client import PatreonApiError, PatreonClient

LOGGER = logging.getLogger(__name__)


class PatreonRuntime:
    def __init__(self, config_path: Path, initial_campaign_id: str = "") -> None:
        self._config_path = config_path
        self.catalog = PatreonCatalog()
        self.active_campaign_id = ""
        self.campaign_changed = asyncio.Event()
        self.load_error: str | None = None
        self._initial_campaign_id = initial_campaign_id.strip()
        self._client: PatreonClient | None = None

    @property
    def enabled(self) -> bool:
        return self.load_error is None and bool(self.catalog.campaigns)

    async def load_catalog(self, client: PatreonClient) -> None:
        self._client = client
        try:
            self.catalog = await client.fetch_campaigns_with_tiers()
            for campaign in self.catalog.campaigns:
                if not self.catalog.tiers_by_campaign.get(campaign.id):
                    tiers = await client.fetch_campaign_tiers(campaign.id)
                    self.catalog.tiers_by_campaign[campaign.id] = tiers
            resolved = self.catalog.resolve_active_campaign_id(self._initial_campaign_id)
            if resolved is None:
                self.load_error = "No Patreon campaigns found on this account."
                LOGGER.error(self.load_error)
                return
            self.active_campaign_id = resolved
            self.load_error = None
            LOGGER.info(
                "Patreon catalog loaded: %s campaign(s), active=%s",
                len(self.catalog.campaigns),
                self.active_campaign_id,
            )
        except PatreonApiError as exc:
            self.load_error = str(exc)
            LOGGER.exception("Failed to load Patreon catalog")

    async def set_active_campaign(self, campaign_id: str) -> None:
        campaign_id = str(campaign_id).strip()
        if campaign_id not in self.catalog.campaign_ids():
            raise ValueError(f"Unknown Patreon campaign_id: {campaign_id}")
        if campaign_id == self.active_campaign_id:
            return
        self.active_campaign_id = campaign_id
        update_patreon_campaign_id(self._config_path, campaign_id)
        self.campaign_changed.set()
        LOGGER.info("Patreon active campaign set to %s", campaign_id)

    def clear_campaign_changed(self) -> None:
        self.campaign_changed.clear()

    def tiers_for_ui(self, point_rules: dict[str, dict]) -> list[dict[str, Any]]:
        rule = point_rules.get(EventType.PATREON_PLEDGE_CREATE.value) or {}
        tier_points = rule.get("tier_points") or {}
        rows: list[dict[str, Any]] = []
        for tier in self.catalog.tiers_for_campaign(self.active_campaign_id):
            key = str(tier.amount_cents)
            rows.append({
                "tier_id": tier.tier_id,
                "title": tier.title,
                "amount_cents": tier.amount_cents,
                "points": int(tier_points.get(key, 0)),
            })
        return rows

    def for_ui(self, point_rules: dict[str, dict], *, feature_enabled: bool = True) -> dict[str, Any]:
        return {
            "feature_enabled": feature_enabled,
            "enabled": feature_enabled and self.enabled,
            "load_error": self.load_error,
            "campaigns": [{"id": c.id, "name": c.name} for c in self.catalog.campaigns],
            "active_campaign_id": self.active_campaign_id,
            "tiers": self.tiers_for_ui(point_rules) if self.active_campaign_id else [],
        }
