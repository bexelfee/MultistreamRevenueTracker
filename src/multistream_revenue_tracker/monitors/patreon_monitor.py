from __future__ import annotations

import asyncio
import logging
from typing import Any

from ..config import AppSettings, PatreonConfig
from ..revenue.events import EventType, Platform, StreamEvent, parse_iso_datetime
from ..platforms.patreon_client import PatreonApiError, PatreonClient, ensure_patreon_token
from ..platforms.patreon_runtime import PatreonRuntime

LOGGER = logging.getLogger(__name__)

PledgeKey = tuple[str, str]


async def await_patreon_events(
    queue: asyncio.Queue,
    shutdown: asyncio.Event,
    patreon_config: PatreonConfig,
    app_settings: AppSettings,
    patreon_runtime: PatreonRuntime,
    registry=None,
) -> None:
    del app_settings
    if patreon_runtime.load_error:
        raise RuntimeError(patreon_runtime.load_error)
    if not patreon_runtime.active_campaign_id:
        raise RuntimeError("Patreon: no active campaign selected")

    token = await ensure_patreon_token(patreon_config)
    client = PatreonClient(patreon_config, token)
    seen: set[PledgeKey] = set()
    try:
        campaign_id = patreon_runtime.active_campaign_id
        LOGGER.info("Patreon monitor using campaign_id=%s", campaign_id)

        await _scan_members(client, campaign_id, seen, queue, emit=False)
        LOGGER.info("Patreon baseline complete (%s known pledge keys)", len(seen))
        if registry is not None:
            await registry.set_status_async("patreon", "active", None)

        while not shutdown.is_set():
            try:
                await asyncio.wait_for(shutdown.wait(), timeout=patreon_config.poll_interval_seconds)
                break
            except asyncio.TimeoutError:
                pass
            if shutdown.is_set():
                break
            if patreon_runtime.campaign_changed.is_set():
                seen.clear()
                campaign_id = patreon_runtime.active_campaign_id
                patreon_runtime.clear_campaign_changed()
                LOGGER.info("Patreon campaign switched; rebaseline campaign_id=%s", campaign_id)
                try:
                    await _scan_members(client, campaign_id, seen, queue, emit=False)
                except PatreonApiError:
                    LOGGER.exception("Patreon baseline failed after campaign switch")
                continue
            try:
                new_count = await _scan_members(client, campaign_id, seen, queue, emit=True)
                if new_count:
                    LOGGER.info("Patreon detected %s new pledge(s)", new_count)
            except PatreonApiError:
                LOGGER.exception("Patreon member poll failed")
    finally:
        await client.aclose()


async def _scan_members(client: PatreonClient, campaign_id: str, seen: set[PledgeKey], queue: asyncio.Queue, emit: bool) -> int:
    new_count = 0
    async for member in client.iter_campaign_members(campaign_id):
        key = pledge_key(member)
        if key is None:
            continue
        if key in seen:
            continue
        if not emit:
            seen.add(key)
            continue
        event = normalize_member_pledge(member)
        if event is None:
            continue
        seen.add(key)
        await queue.put(event)
        new_count += 1
    return new_count


def pledge_key(member: dict[str, Any]) -> PledgeKey | None:
    attrs = member.get("attributes") or {}
    member_id = str(member.get("id") or "")
    pledge_start = attrs.get("pledge_relationship_start")
    if not member_id or not pledge_start:
        return None
    return member_id, str(pledge_start)


def normalize_member_pledge(member: dict[str, Any]) -> StreamEvent | None:
    attrs = member.get("attributes") or {}
    if attrs.get("patron_status") != "active_patron":
        return None
    if attrs.get("last_charge_status") != "Paid":
        return None
    cents = attrs.get("currently_entitled_amount_cents") or 0
    if cents <= 0:
        return None

    member_id = str(member.get("id") or "")
    pledge_start = attrs.get("pledge_relationship_start")
    if not member_id or not pledge_start:
        return None

    occurred_at = parse_iso_datetime(pledge_start or attrs.get("last_charge_date"))
    tier = str(int(cents))
    amount_display = f"${cents / 100:.2f}/mo"

    return StreamEvent(
        platform=Platform.PATREON,
        event_type=EventType.PATREON_PLEDGE_CREATE,
        occurred_at=occurred_at,
        source_event_id=f"patreon:{member_id}:{pledge_start}",
        gifter_user_id=member_id,
        gifter_user_name=attrs.get("full_name"),
        tier=tier,
        amount_display=amount_display,
        currency="USD",
        raw={"member": member},
    )
