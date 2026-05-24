import pytest

from multistream_revenue_tracker.platforms.supported_currencies import is_supported_currency, supported_currency_codes


def test_supported_currency_codes_nonempty():
    codes = supported_currency_codes()
    assert "EUR" in codes
    assert "USD" in codes
    assert len(codes) > 100


def test_is_supported_currency():
    assert is_supported_currency("eur")
    assert not is_supported_currency("XXX")
