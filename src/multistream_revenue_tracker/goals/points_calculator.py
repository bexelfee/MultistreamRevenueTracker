from __future__ import annotations

import logging
import math

from .point_rules import PointRulesStore
from ..revenue.revenue_db import StoredRevenueEvent
from ..revenue.revenue_validity import effective_event_type_value, is_scoring_valid

LOGGER = logging.getLogger(__name__)


def points_for_event_fractional(event: StoredRevenueEvent, rules_store: PointRulesStore) -> float:
    if not is_scoring_valid(event):
        return 0.0
    rule = rules_store.rules.get(effective_event_type_value(event))
    if not rule:
        return 0.0
    mode = rule.get("mode")
    if mode == "per_quantity":
        quantity = event.quantity or 0
        return quantity * float(rule.get("points_per_unit", 0))
    if mode == "per_event":
        return float(rule.get("points_per_event", 0))
    if mode == "per_event_tier":
        tier_points = rule.get("tier_points") or {}
        tier_key = _tier_key_for_event(event, rules_store)
        return float(tier_points.get(tier_key, 0))
    if mode == "per_quantity_tier":
        tier_points = rule.get("tier_points") or {}
        tier_key = _tier_key_for_event(event, rules_store)
        per_tier = float(tier_points.get(tier_key, 0))
        quantity = event.quantity or 1
        return per_tier * quantity
    if mode == "per_eur":
        amount_eur = _amount_in_eur(event, rules_store)
        return amount_eur * float(rule.get("points_per_eur", 0))
    LOGGER.warning("unknown point rule mode %r for event_type=%s", mode, effective_event_type_value(event))
    return 0.0


def points_for_events_fractional(events: list[StoredRevenueEvent], rules_store: PointRulesStore) -> float:
    total = sum(points_for_event_fractional(event, rules_store) for event in events)
    return round(total, 2)


def points_for_event(event: StoredRevenueEvent, rules_store: PointRulesStore) -> int:
    return _round_points(points_for_event_fractional(event, rules_store))


def points_for_events(events: list[StoredRevenueEvent], rules_store: PointRulesStore) -> int:
    return _round_points(points_for_events_fractional(events, rules_store))


def _round_points(value: float) -> int:
    return int(math.floor(value + 0.5))


def _tier_key_for_event(event: StoredRevenueEvent, rules_store: PointRulesStore) -> str:
    del rules_store
    return _normalize_tier(event.tier)


def _normalize_tier(tier: str | None) -> str:
    if not tier:
        return ""
    text = str(tier).strip()
    if text in {"1", "2", "3"}:
        return {"1": "1000", "2": "2000", "3": "3000"}[text]
    return text


def _amount_in_eur(event: StoredRevenueEvent, rules_store: PointRulesStore) -> float:
    if event.amount_micros is None:
        return 0.0
    currency = (event.currency or rules_store.base_currency).upper()
    rates = rules_store.rates.get("rates_to_eur", {})
    rate = rates.get(currency)
    if rate is None:
        LOGGER.warning("no exchange rate for currency %s on event id=%s", currency, event.id)
        return 0.0
    amount = event.amount_micros / 1_000_000
    return amount * float(rate)
