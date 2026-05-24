from multistream_revenue_tracker.revenue.events import EventType, Platform
from multistream_revenue_tracker.monitors.patreon_monitor import normalize_member_pledge, pledge_key


def _member(**attrs):
    base = {
        "id": "member-uuid-1",
        "type": "member",
        "attributes": {
            "full_name": "Patron One",
            "patron_status": "active_patron",
            "last_charge_status": "Paid",
            "currently_entitled_amount_cents": 1000,
            "pledge_relationship_start": "2026-05-18T12:00:00+00:00",
            "last_charge_date": "2026-05-18T12:00:00+00:00",
        },
    }
    base["attributes"].update(attrs)
    return base


def test_pledge_key_requires_member_id_and_pledge_start():
    assert pledge_key(_member()) == ("member-uuid-1", "2026-05-18T12:00:00+00:00")
    assert pledge_key(_member(pledge_relationship_start=None)) is None


def test_normalize_active_paid_pledge():
    event = normalize_member_pledge(_member())
    assert event is not None
    assert event.platform == Platform.PATREON
    assert event.event_type == EventType.PATREON_PLEDGE_CREATE
    assert event.gifter_user_id == "member-uuid-1"
    assert event.gifter_user_name == "Patron One"
    assert event.tier == "1000"
    assert event.currency == "USD"
    assert event.amount_display == "$10.00/mo"
    assert event.source_event_id == "patreon:member-uuid-1:2026-05-18T12:00:00+00:00"


def test_normalize_declined_patron_returns_none():
    assert normalize_member_pledge(_member(last_charge_status="Declined")) is None


def test_normalize_former_patron_returns_none():
    assert normalize_member_pledge(_member(patron_status="former_patron")) is None


def test_normalize_free_entitlement_returns_none():
    assert normalize_member_pledge(_member(currently_entitled_amount_cents=0)) is None
