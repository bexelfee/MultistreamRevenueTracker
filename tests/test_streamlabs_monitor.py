from multistream_revenue_tracker.revenue.events import EventType, Platform
from multistream_revenue_tracker.monitors.streamlabs_monitor import (
    _is_streamlabs_donation_payload,
    normalize_streamlabs_donation,
)


def test_is_streamlabs_donation_payload():
    assert _is_streamlabs_donation_payload({"type": "donation", "message": []})
    assert _is_streamlabs_donation_payload({"type": "donation", "for": "streamlabs", "message": []})
    assert not _is_streamlabs_donation_payload({"type": "donation", "for": "twitch_account", "message": []})
    assert not _is_streamlabs_donation_payload({"type": "bits", "for": "twitch_account", "message": []})


def test_normalize_streamlabs_donation():
    event = normalize_streamlabs_donation(
        {
            "id": 96164121,
            "name": "test",
            "amount": "13.37",
            "formatted_amount": "$13.37",
            "message": "hello",
            "currency": "USD",
        }
    )
    assert event is not None
    assert event.platform == Platform.STREAMLABS
    assert event.event_type == EventType.STREAMLABS_DONATION
    assert event.is_revenue
    assert event.source_event_id == "96164121"
    assert event.gifter_user_name == "test"
    assert event.amount_micros == 13_370_000
    assert event.currency == "USD"
    assert event.message == "hello"


def test_normalize_streamlabs_donation_requires_id():
    assert normalize_streamlabs_donation({"name": "x", "amount": "1"}) is None


def test_normalize_streamlabs_donation_stores_envelope_metadata():
    event = normalize_streamlabs_donation(
        {"id": 1, "name": "donor", "amount": "5.00", "currency": "USD"},
        envelope_event_id="evt_abc",
        envelope_for="streamlabs",
    )
    assert event is not None
    assert event.raw["streamlabs_envelope_event_id"] == "evt_abc"
    assert event.raw["streamlabs_envelope_for"] == "streamlabs"
