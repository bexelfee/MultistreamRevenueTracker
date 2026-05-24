from datetime import datetime, timezone

from multistream_revenue_tracker.revenue.events import EventType, Platform
from multistream_revenue_tracker.goals.point_rules import PointRulesStore
from multistream_revenue_tracker.goals.points_calculator import points_for_event, points_for_event_fractional
from multistream_revenue_tracker.revenue.revenue_db import StoredRevenueEvent
from multistream_revenue_tracker.platforms.youtube_catalog import YoutubeLevelInfo
from multistream_revenue_tracker.platforms.youtube_runtime import YoutubeRuntime


def _stored(**kwargs) -> StoredRevenueEvent:
    defaults = {
        "id": 1,
        "platform": Platform.TWITCH,
        "event_type": EventType.TWITCH_BITS,
        "occurred_at": datetime(2026, 5, 18, 12, 0, tzinfo=timezone.utc),
        "source_event_id": "x",
        "gifter_user_id": None,
        "gifter_user_name": None,
        "recipient_user_id": None,
        "recipient_user_name": None,
        "amount_micros": None,
        "amount_display": None,
        "currency": None,
        "quantity": None,
        "tier": None,
        "message": None,
        "raw": {},
        "created_at": datetime(2026, 5, 18, 12, 0, tzinfo=timezone.utc),
    }
    defaults.update(kwargs)
    return StoredRevenueEvent(**defaults)


def _rules_store(tmp_path) -> PointRulesStore:
    store = PointRulesStore(
        point_rules_path=tmp_path / "point_rules.json",
        exchange_rates_path=tmp_path / "exchange_rates.json",
    )
    store.load()
    return store


def test_twitch_bits_per_quantity(tmp_path):
    store = _rules_store(tmp_path)
    event = _stored(event_type=EventType.TWITCH_BITS, quantity=100)
    assert points_for_event(event, store) == 100


def test_twitch_subscription_tier_points(tmp_path):
    store = _rules_store(tmp_path)
    event = _stored(event_type=EventType.TWITCH_SUBSCRIPTION, tier="2000")
    assert points_for_event(event, store) == 1000


def test_twitch_gift_subscription_quantity_tier(tmp_path):
    store = _rules_store(tmp_path)
    event = _stored(event_type=EventType.TWITCH_SUBSCRIPTION_GIFT, tier="1000", quantity=3)
    assert points_for_event(event, store) == 1500


def test_youtube_super_chat_usd_to_eur(tmp_path):
    store = _rules_store(tmp_path)
    event = _stored(
        platform=Platform.YOUTUBE,
        event_type=EventType.YOUTUBE_SUPER_CHAT,
        amount_micros=10_000_000,
        currency="USD",
    )
    # 10 USD * 0.92 EUR/USD * 100 pts/EUR = 920
    assert points_for_event(event, store) == 920


def test_patreon_pledge_tier_points(tmp_path):
    store = _rules_store(tmp_path)
    store.save_rules({
        **store.rules,
        EventType.PATREON_PLEDGE_CREATE.value: {"mode": "per_event_tier", "tier_points": {"1500": 750}},
    })
    event = _stored(
        platform=Platform.PATREON,
        event_type=EventType.PATREON_PLEDGE_CREATE,
        tier="1500",
    )
    assert points_for_event(event, store) == 750


def test_patreon_pledge_unknown_tier_zero_points(tmp_path):
    store = _rules_store(tmp_path)
    event = _stored(
        platform=Platform.PATREON,
        event_type=EventType.PATREON_PLEDGE_CREATE,
        tier="999",
    )
    assert points_for_event(event, store) == 0


def test_revenue_invalid_scores_zero(tmp_path):
    store = _rules_store(tmp_path)
    from multistream_revenue_tracker.revenue.revenue_validity import build_auto_invalid_raw

    event = _stored(
        event_type=EventType.REVENUE_INVALID,
        tier="1000",
        raw=build_auto_invalid_raw(EventType.TWITCH_RESUBSCRIPTION.value),
    )
    assert points_for_event(event, store) == 0


def test_streamlabs_donation_per_eur(tmp_path):
    store = _rules_store(tmp_path)
    event = _stored(
        platform=Platform.STREAMLABS,
        event_type=EventType.STREAMLABS_DONATION,
        amount_micros=10_000_000,
        currency="EUR",
    )
    assert points_for_event(event, store) == 1000


def test_fractional_rule_keeps_exact_points_until_display_rounding(tmp_path):
    store = _rules_store(tmp_path)
    store.rules["youtube_super_chat"] = {"mode": "per_eur", "points_per_eur": 1.5}
    event = _stored(
        platform=Platform.YOUTUBE,
        event_type=EventType.YOUTUBE_SUPER_CHAT,
        amount_micros=1_000_000,
        currency="EUR",
    )
    assert points_for_event_fractional(event, store) == 1.5
    assert points_for_event(event, store) == 2


def test_youtube_membership_per_tier_points(tmp_path):
    store = _rules_store(tmp_path)
    runtime = YoutubeRuntime()
    runtime.levels = [YoutubeLevelInfo(id="L1", name="Gold")]
    store.youtube_level_resolver = runtime.resolve_level_id
    store.save_rules({
        **store.rules,
        EventType.YOUTUBE_MEMBERSHIP.value: {
            "mode": "per_event_tier",
            "tier_points": {"L1": 250},
        },
    })
    event = _stored(
        platform=Platform.YOUTUBE,
        event_type=EventType.YOUTUBE_MEMBERSHIP,
        tier="Gold",
    )
    assert points_for_event(event, store) == 250


def test_youtube_membership_gift_quantity_times_tier(tmp_path):
    store = _rules_store(tmp_path)
    runtime = YoutubeRuntime()
    runtime.levels = [YoutubeLevelInfo(id="L1", name="Gold")]
    store.youtube_level_resolver = runtime.resolve_level_id
    store.save_rules({
        **store.rules,
        EventType.YOUTUBE_MEMBERSHIP_GIFT.value: {
            "mode": "per_quantity_tier",
            "tier_points": {"L1": 100},
        },
    })
    event = _stored(
        platform=Platform.YOUTUBE,
        event_type=EventType.YOUTUBE_MEMBERSHIP_GIFT,
        tier="Gold",
        quantity=3,
    )
    assert points_for_event(event, store) == 300


def test_youtube_membership_unknown_tier_zero_and_warning(tmp_path, caplog):
    store = _rules_store(tmp_path)
    runtime = YoutubeRuntime()
    runtime.levels = [YoutubeLevelInfo(id="L1", name="Gold")]
    store.youtube_level_resolver = runtime.resolve_level_id
    store.save_rules({
        **store.rules,
        EventType.YOUTUBE_MEMBERSHIP.value: {
            "mode": "per_event_tier",
            "tier_points": {"L1": 250},
        },
    })
    event = _stored(
        platform=Platform.YOUTUBE,
        event_type=EventType.YOUTUBE_MEMBERSHIP,
        tier="Platinum",
    )
    assert points_for_event(event, store) == 0
    assert any("Platinum" in r.message for r in caplog.records if r.levelname == "WARNING")


def test_youtube_membership_per_event_tier_survives_normalize(tmp_path):
    store = _rules_store(tmp_path)
    saved = store.save_rules({
        **store.rules,
        EventType.YOUTUBE_MEMBERSHIP.value: {
            "mode": "per_event_tier",
            "tier_points": {"L1": 42},
        },
    })
    assert saved[EventType.YOUTUBE_MEMBERSHIP.value]["mode"] == "per_event_tier"
    assert saved[EventType.YOUTUBE_MEMBERSHIP.value]["tier_points"]["L1"] == 42


def test_unknown_currency_yields_zero_points(tmp_path, caplog):
    store = _rules_store(tmp_path)
    event = _stored(
        platform=Platform.YOUTUBE,
        event_type=EventType.YOUTUBE_SUPER_CHAT,
        amount_micros=5_000_000,
        currency="JPY",
    )
    assert points_for_event(event, store) == 0
    assert "no exchange rate" in caplog.text
