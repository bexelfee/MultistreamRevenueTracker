import logging
import urllib.error

import pytest

from multistream_revenue_tracker.services.exchange_rates import fetch_rates_to_eur, refresh_exchange_rates_file


def test_fetch_rates_to_eur_includes_eur_usd_and_cop():
    rates = fetch_rates_to_eur()
    assert rates["EUR"] == 1.0
    assert "USD" in rates
    assert rates["USD"] > 0
    assert "COP" in rates
    assert rates["COP"] > 0


def test_refresh_writes_file(tmp_path):
    path = tmp_path / "exchange_rates.json"
    data = refresh_exchange_rates_file(path)
    assert path.is_file()
    assert "rates_to_eur" in data
    assert data["rates_to_eur"]["EUR"] == 1.0
    assert data["source"] == "exchangerate-api-open"
    assert "COP" in data["rates_to_eur"]


def test_refresh_uses_existing_file_when_fetch_fails(tmp_path, monkeypatch):
    path = tmp_path / "exchange_rates.json"
    path.write_text(
        '{"base_currency":"EUR","source":"cached","rates_to_eur":{"EUR":1.0,"COP":0.0002}}',
        encoding="utf-8",
    )

    def fail_fetch():
        raise urllib.error.URLError("offline")

    monkeypatch.setattr("multistream_revenue_tracker.services.exchange_rates.fetch_rates_to_eur", fail_fetch)
    data = refresh_exchange_rates_file(path)
    assert data["source"] == "cached"
    assert data["rates_to_eur"]["COP"] == 0.0002


def test_refresh_logs_and_does_not_write_when_fetch_fails_and_no_file(tmp_path, monkeypatch, caplog):
    path = tmp_path / "exchange_rates.json"

    def fail_fetch():
        raise urllib.error.URLError("offline")

    monkeypatch.setattr("multistream_revenue_tracker.services.exchange_rates.fetch_rates_to_eur", fail_fetch)
    with caplog.at_level(logging.ERROR):
        data = refresh_exchange_rates_file(path)
    assert not path.is_file()
    assert data["source"] == "unavailable"
    assert "exchange rate fetch failed" in caplog.text.lower()


def test_apply_points_change_clamps_at_zero(tmp_path):
    from datetime import datetime, timezone

    from multistream_revenue_tracker.goals.goal_service import GoalService
    from multistream_revenue_tracker.goals.goal_store import GoalStore
    from multistream_revenue_tracker.goals.point_rules import PointRulesStore
    from multistream_revenue_tracker.revenue.revenue_db import RevenueDatabase

    database = RevenueDatabase(tmp_path / "revenue.db")
    database.initialize()
    service = GoalService(
        GoalStore(tmp_path / "goals"),
        PointRulesStore(tmp_path / "rules.json", tmp_path / "rates.json"),
        database,
    )
    service.create_goal("Test", 1000, datetime(2026, 1, 1, tzinfo=timezone.utc))
    service.apply_points_change(100, add=True)
    assert service.compute_progress().current_points == 100
    service.apply_points_change(500, add=False)
    assert service.compute_progress().current_points == 0
