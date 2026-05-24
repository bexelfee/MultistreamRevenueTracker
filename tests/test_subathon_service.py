"""Tests for subathon timer service."""
from __future__ import annotations

import asyncio
import json

import pytest

from multistream_revenue_tracker.revenue.events import EventType, Platform, StreamEvent, utc_now
from multistream_revenue_tracker.goals.point_rules import PointRulesStore
from multistream_revenue_tracker.revenue.revenue_db import RevenueDatabase
from multistream_revenue_tracker.services.subathon_service import (
    SubathonService,
    format_display,
    format_display_days,
    parse_time_parts,
    seconds_to_add,
)


def test_format_display():
    assert format_display(3661) == "01:01:01"
    assert format_display(0) == "00:00:00"


def test_format_display_days():
    assert format_display_days(90061) == "1 Days 01:01:01"
    assert format_display_days(0) == "0 Days 00:00:00"


def test_snapshot_show_days(tmp_path):
    db = RevenueDatabase(tmp_path / "rev.db")
    db.initialize()
    service = SubathonService(tmp_path / "state.json", db, show_days=True)
    service.set_remaining_seconds(90061)
    assert service.snapshot()["display"] == "1 Days 01:01:01"


def test_seconds_to_add_floor():
    assert seconds_to_add(25, subathon_points=10, subathon_seconds=60) == 150
    assert seconds_to_add(0, subathon_points=10, subathon_seconds=60) == 0
    assert seconds_to_add(5.9, subathon_points=10, subathon_seconds=60) == 35


def test_parse_time_parts():
    assert parse_time_parts(hours=1, minutes=2, seconds=3) == 3723
    assert parse_time_parts(total_seconds=90) == 90


def test_watermark_skips_old_events(tmp_path):
    rules = PointRulesStore(
        point_rules_path=tmp_path / "point_rules.json",
        exchange_rates_path=tmp_path / "exchange_rates.json",
    )
    rules.load()
    rules.rules["twitch_bits"] = {"mode": "per_quantity", "points_per_unit": 1}

    db = RevenueDatabase(tmp_path / "rev.db")
    db.initialize()
    event = StreamEvent(
        platform=Platform.TWITCH,
        event_type=EventType.TWITCH_BITS,
        occurred_at=utc_now(),
        quantity=10,
        source_event_id="bits-1",
    )
    row_id = db.add_revenue_event(event)
    assert row_id is not None
    stored = db.get_revenue_event(row_id)

    service = SubathonService(tmp_path / "subathon_state.json", db, subathon_points=10, subathon_seconds=60)
    service.reset_watermark()
    assert service.on_revenue_event(stored, rules) is False
    assert service.snapshot()["remaining_seconds"] == 0

    row_id2 = db.add_revenue_event(
        StreamEvent(
            platform=Platform.TWITCH,
            event_type=EventType.TWITCH_BITS,
            occurred_at=utc_now(),
            quantity=10,
            source_event_id="bits-2",
        )
    )
    stored2 = db.get_revenue_event(row_id2)
    assert service.on_revenue_event(stored2, rules) is True
    assert service.snapshot()["remaining_seconds"] == 60


def test_tick_decrements_and_stops_at_zero(tmp_path):
    db = RevenueDatabase(tmp_path / "rev.db")
    db.initialize()
    service = SubathonService(tmp_path / "subathon_state.json", db)
    service.set_remaining_seconds(2)
    service.set_running(True)
    assert service.tick_once() is True
    assert service.snapshot()["remaining_seconds"] == 1
    assert service.tick_once() is True
    assert service.snapshot()["remaining_seconds"] == 0
    assert service.tick_once() is False


def test_pause_still_accepts_event_adds(tmp_path):
    rules = PointRulesStore(
        point_rules_path=tmp_path / "rules.json",
        exchange_rates_path=tmp_path / "rates.json",
    )
    rules.load()
    rules.rules["twitch_bits"] = {"mode": "per_quantity", "points_per_unit": 1}

    db = RevenueDatabase(tmp_path / "rev.db")
    db.initialize()
    service = SubathonService(tmp_path / "state.json", db, subathon_points=1, subathon_seconds=30)
    service.set_running(False)

    row_id = db.add_revenue_event(
        StreamEvent(
            platform=Platform.TWITCH,
            event_type=EventType.TWITCH_BITS,
            occurred_at=utc_now(),
            quantity=2,
            source_event_id="x",
        )
    )
    stored = db.get_revenue_event(row_id)
    service.on_revenue_event(stored, rules)
    assert service.snapshot()["remaining_seconds"] == 60
    assert service.snapshot()["running"] is False


def test_persistence_round_trip(tmp_path):
    db = RevenueDatabase(tmp_path / "rev.db")
    db.initialize()
    path = tmp_path / "subathon_state.json"
    service = SubathonService(path, db)
    service.set_remaining_seconds(123)
    service.set_running(True)
    service.reset_watermark()

    service2 = SubathonService(path, db)
    snap = service2.snapshot()
    assert snap["remaining_seconds"] == 123
    assert snap["running"] is True
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert raw["last_processed_event_id"] == db.max_event_id()


@pytest.mark.asyncio
async def test_tick_loop_notifies(tmp_path):
    db = RevenueDatabase(tmp_path / "rev.db")
    db.initialize()
    service = SubathonService(tmp_path / "state.json", db)
    service.set_remaining_seconds(1)
    service.set_running(True)
    notified = asyncio.Event()

    async def on_change() -> None:
        notified.set()

    service.add_listener(on_change)
    shutdown = asyncio.Event()
    task = asyncio.create_task(service.tick_loop(shutdown))
    await asyncio.wait_for(notified.wait(), timeout=3)
    shutdown.set()
    await task
    assert service.snapshot()["remaining_seconds"] == 0
