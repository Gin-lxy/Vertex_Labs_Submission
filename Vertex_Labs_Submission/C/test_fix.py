from datetime import datetime, timezone

from fix import deals_needing_followup


def test_excludes_closed():
    deals = [
        {"name": "A", "stage": "Closed - Won",
         "last_contact": "2026-09-01T09:00:00+08:00"},
    ]
    assert deals_needing_followup(deals) == []


def test_stale_deal_returned():
    today = datetime(2026, 11, 1, tzinfo=timezone.utc)
    deals = [
        {"name": "B", "stage": "Diligence",
         "last_contact": "2026-10-01T09:30:00+08:00"},
    ]
    assert deals_needing_followup(deals, today=today) == ["B"]


def test_no_shared_state():
    deals = [
        {"name": "C", "stage": "Sourcing",
         "last_contact": "2026-09-01T09:00:00+08:00"},
    ]
    deals_needing_followup(deals)
    assert deals_needing_followup(deals) == ["C"]


def test_mixed_offsets_sorted_most_stale_first():
    today = datetime(2026, 11, 1, tzinfo=timezone.utc)
    deals = [
        {"name": "India", "stage": "Sourcing",
         "last_contact": "2026-10-02T10:00:00+05:30"},
        {"name": "Singapore", "stage": "Sourcing",
         "last_contact": "2026-10-01T09:30:00+08:00"},
    ]
    result = deals_needing_followup(deals, today=today)
    assert result == ["Singapore", "India"]
