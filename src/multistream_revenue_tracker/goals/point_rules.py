from __future__ import annotations

import json
import logging
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path

from ..revenue.events import REVENUE_EVENT_TYPES, EventType

LOGGER = logging.getLogger(__name__)

DEFAULT_TIER_POINTS = {"1000": 500, "2000": 1000, "3000": 2500}


def default_point_rules() -> dict[str, dict]:
    return {
        EventType.TWITCH_BITS.value: {"mode": "per_quantity", "points_per_unit": 1},
        EventType.TWITCH_SUBSCRIPTION.value: {"mode": "per_event_tier", "tier_points": dict(DEFAULT_TIER_POINTS)},
        EventType.TWITCH_SUBSCRIPTION_GIFT.value: {"mode": "per_quantity_tier", "tier_points": dict(DEFAULT_TIER_POINTS)},
        EventType.TWITCH_RESUBSCRIPTION.value: {"mode": "per_event_tier", "tier_points": dict(DEFAULT_TIER_POINTS)},
        EventType.YOUTUBE_SUPER_CHAT.value: {"mode": "per_eur", "points_per_eur": 100},
        EventType.YOUTUBE_SUPER_STICKER.value: {"mode": "per_eur", "points_per_eur": 100},
        EventType.YOUTUBE_MEMBERSHIP.value: {"mode": "per_event", "points_per_event": 0},
        EventType.YOUTUBE_MEMBERSHIP_GIFT.value: {"mode": "per_quantity", "points_per_unit": 0},
        EventType.YOUTUBE_GIFT.value: {"mode": "per_quantity", "points_per_unit": 1},
        EventType.PATREON_PLEDGE_CREATE.value: {"mode": "per_event_tier", "tier_points": {}},
        EventType.STREAMLABS_DONATION.value: {"mode": "per_eur", "points_per_eur": 100},
    }


def default_exchange_rates(base_currency: str = "EUR") -> dict:
    return {
        "base_currency": base_currency,
        "rates_to_eur": {"EUR": 1.0, "USD": 0.92, "GBP": 1.17},
    }


@dataclass
class PointRulesStore:
    point_rules_path: Path
    exchange_rates_path: Path
    base_currency: str = "EUR"
    _rules: dict[str, dict] = field(default_factory=dict)
    _rates: dict = field(default_factory=dict)

    def load(self) -> None:
        self._rules = self._load_rules_file()
        self._rates = self._load_rates_file()

    def save_rules(self, rules: dict[str, dict]) -> dict[str, dict]:
        self._rules = self._normalize_rules(rules)
        self.point_rules_path.parent.mkdir(parents=True, exist_ok=True)
        self.point_rules_path.write_text(json.dumps(self._rules, indent=2), encoding="utf-8")
        return deepcopy(self._rules)

    def save_rates(self, rates: dict) -> dict:
        self._rates = self._normalize_rates(rates)
        self.exchange_rates_path.parent.mkdir(parents=True, exist_ok=True)
        self.exchange_rates_path.write_text(json.dumps(self._rates, indent=2), encoding="utf-8")
        return deepcopy(self._rates)

    @property
    def rules(self) -> dict[str, dict]:
        if not self._rules:
            self.load()
        return self._rules

    @property
    def rates(self) -> dict:
        if not self._rates:
            self.load()
        return self._rates

    def rules_for_ui(self) -> dict[str, dict]:
        return deepcopy(self.rules)

    def rates_for_ui(self) -> dict:
        return deepcopy(self.rates)

    def _load_rules_file(self) -> dict[str, dict]:
        if not self.point_rules_path.is_file():
            defaults = default_point_rules()
            self.point_rules_path.parent.mkdir(parents=True, exist_ok=True)
            self.point_rules_path.write_text(json.dumps(defaults, indent=2), encoding="utf-8")
            return defaults
        data = json.loads(self.point_rules_path.read_text(encoding="utf-8"))
        return self._normalize_rules(data)

    def _load_rates_file(self) -> dict:
        if not self.exchange_rates_path.is_file():
            defaults = default_exchange_rates(self.base_currency)
            self.exchange_rates_path.parent.mkdir(parents=True, exist_ok=True)
            self.exchange_rates_path.write_text(json.dumps(defaults, indent=2), encoding="utf-8")
            return defaults
        data = json.loads(self.exchange_rates_path.read_text(encoding="utf-8"))
        return self._normalize_rates(data)

    def _normalize_rules(self, raw: dict) -> dict[str, dict]:
        normalized = default_point_rules()
        for event_type in REVENUE_EVENT_TYPES:
            key = event_type.value
            if key not in normalized:
                continue
            user_rule = raw.get(key)
            if not isinstance(user_rule, dict):
                continue
            default_rule = normalized[key]
            # Force-merge only fields the current default uses. This drops
            # stale fields when the rule shape changes between releases (e.g.
            # YouTube memberships moved from per-tier to flat per-event), so
            # existing point_rules.json files migrate without manual edits.
            merged = dict(default_rule)
            for field, value in user_rule.items():
                if field in default_rule and field != "mode":
                    merged[field] = value
            normalized[key] = merged
        return normalized

    def _normalize_rates(self, raw: dict) -> dict:
        rates = default_exchange_rates(self.base_currency)
        if isinstance(raw, dict):
            if raw.get("base_currency"):
                rates["base_currency"] = str(raw["base_currency"]).upper()
            if isinstance(raw.get("rates_to_eur"), dict):
                rates["rates_to_eur"] = {str(k).upper(): float(v) for k, v in raw["rates_to_eur"].items()}
        return rates
