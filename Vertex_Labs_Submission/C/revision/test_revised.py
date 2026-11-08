from copy import deepcopy
from datetime import datetime, timedelta, timezone

import pytest


NOW = datetime(2026, 11, 1, tzinfo=timezone.utc)
UTC_PLUS_8 = timezone(timedelta(hours=8))
UTC_PLUS_530 = timezone(timedelta(hours=5, minutes=30))


def make_deal(
    last_contact=None,
    *,
    name="Deal",
    stage="Sourcing",
    deal_id="deal-1",
    include_name=True,
    include_contact=True,
):
    deal = {"stage": stage}
    if include_name:
        deal["name"] = name
    if deal_id is not None:
        deal["id"] = deal_id
    if include_contact:
        deal["last_contact"] = last_contact
    return deal


@pytest.mark.parametrize(
    ("age", "expected"),
    [
        (timedelta(days=14, microseconds=1), ["Older by one microsecond"]),
        (timedelta(days=14), ["Exactly fourteen days"]),
        (timedelta(days=14, microseconds=-1), []),
    ],
)
def test_includes_contacts_at_or_before_the_336_hour_cutoff(implementation, age, expected):
    contact = (NOW - age).isoformat()
    deal = make_deal(contact, name=expected[0] if expected else "One microsecond newer")

    assert implementation.deals_needing_followup([deal], today=NOW) == expected


@pytest.mark.parametrize(
    ("today", "contact"),
    [
        (
            datetime(2026, 11, 1, 8, tzinfo=UTC_PLUS_8),
            "2026-10-18T08:00:00+08:00",
        ),
        (
            datetime(2026, 11, 1, 5, 30, tzinfo=UTC_PLUS_530),
            "2026-10-18T05:30:00+05:30",
        ),
    ],
)
def test_today_and_contact_offsets_are_compared_as_utc_instants(implementation, today, contact):
    deal = make_deal(contact, name="Exact offset boundary")

    assert implementation.deals_needing_followup([deal], today=today) == [
        "Exact offset boundary"
    ]


def test_cross_local_date_order_uses_utc_instants(implementation):
    deals = [
        make_deal(
            "2026-10-02T00:30:00+08:00",
            name="Singapore",
            deal_id="sg",
        ),
        make_deal(
            "2026-10-01T23:00:00+05:30",
            name="India",
            deal_id="in",
        ),
    ]

    assert implementation.deals_needing_followup(deals, today=NOW) == ["Singapore", "India"]


def test_equal_utc_contact_instants_preserve_input_order(implementation):
    deals = [
        make_deal("2026-10-01T00:00:00+08:00", name="Zulu", deal_id="z"),
        make_deal("2026-09-30T16:00:00+00:00", name="Alpha", deal_id="a"),
        make_deal("2026-09-30T12:00:00-04:00", name="Mike", deal_id="m"),
    ]

    assert implementation.deals_needing_followup(deals, today=NOW) == [
        "Zulu",
        "Alpha",
        "Mike",
    ]


def test_never_contacted_deals_keep_input_order_and_precede_stale_deals(implementation):
    deals = [
        make_deal((NOW - timedelta(days=20)).isoformat(), name="Zulu stale", deal_id="z-stale"),
        make_deal(None, name="Zulu never", deal_id="z-never"),
        make_deal(None, name="Alpha never", deal_id="a-never"),
        make_deal((NOW - timedelta(days=20)).isoformat(), name="Alpha stale", deal_id="a-stale"),
    ]

    assert implementation.deals_needing_followup(deals, today=NOW) == [
        "Zulu never",
        "Alpha never",
        "Zulu stale",
        "Alpha stale",
    ]


@pytest.mark.parametrize(
    ("stage", "expected"),
    [
        ("Sourcing", ["Sourcing deal"]),
        ("Diligence", ["Diligence deal"]),
        ("Closed - Won", []),
        ("Closed - Lost", []),
    ],
)
def test_only_sourcing_and_diligence_are_open_stages(implementation, stage, expected):
    deal = make_deal(
        "2026-10-01T00:00:00+00:00",
        stage=stage,
        name=f"{stage} deal",
    )

    assert implementation.deals_needing_followup([deal], today=NOW) == expected


@pytest.mark.parametrize("stage", ["Closed - Won", "Closed - Lost"])
def test_closed_deals_skip_name_and_contact_validation(implementation, stage):
    deal = {
        "id": f"closed-{stage}",
        "stage": stage,
        "last_contact": object(),
    }

    assert implementation.deals_needing_followup([deal], today=NOW) == []


def test_future_contact_one_microsecond_after_today_is_rejected(implementation):
    deal = make_deal(
        (NOW + timedelta(microseconds=1)).isoformat(),
        name="Future contact",
        deal_id="future-1us",
    )

    with pytest.raises(ValueError) as exc:
        implementation.deals_needing_followup([deal], today=NOW)

    message = str(exc.value).lower()
    assert "future-1us" in message
    assert "last_contact" in message
    assert "future" in message


def test_contact_equal_to_now_with_an_offset_is_valid_and_not_stale(implementation):
    deal = make_deal(
        "2026-11-01T08:00:00+08:00",
        name="Contacted now",
        deal_id="equal-now",
    )

    assert implementation.deals_needing_followup([deal], today=NOW) == []


@pytest.mark.parametrize(
    ("last_contact", "reason_tokens"),
    [
        ("2026-10-01T00:00:00", ("timezone", "time zone", "offset")),
        ("not-an-iso-timestamp", ("format", "date", "iso")),
        ("2026-02-30T00:00:00+00:00", ("date", "invalid")),
        (17, ("type", "string", "iso")),
    ],
)
def test_invalid_last_contact_raises_value_error_with_id_and_reason(
    implementation, last_contact, reason_tokens
):
    deal = make_deal(last_contact, name="Invalid contact", deal_id="bad-contact")

    with pytest.raises(ValueError) as exc:
        implementation.deals_needing_followup([deal], today=NOW)

    message = str(exc.value).lower()
    assert "bad-contact" in message
    assert "last_contact" in message
    assert any(token in message for token in reason_tokens)


@pytest.mark.parametrize(
    ("today", "reason_tokens"),
    [
        (datetime(2026, 11, 1), ("timezone", "time zone", "offset")),
        ("2026-11-01T00:00:00+00:00", ("datetime", "type")),
        (17, ("datetime", "type")),
    ],
)
def test_invalid_today_raises_value_error_with_deal_id_and_reason(
    implementation, today, reason_tokens
):
    deal = make_deal(NOW.isoformat(), name="Today context", deal_id="today-context")

    with pytest.raises(ValueError) as exc:
        implementation.deals_needing_followup([deal], today=today)

    message = str(exc.value).lower()
    assert "today-context" in message
    assert "today" in message
    assert any(token in message for token in reason_tokens)


def test_today_validation_precedes_closed_record_validation(implementation):
    deal = {
        "id": "today-first",
        "stage": "Closed - Won",
        "last_contact": object(),
    }

    with pytest.raises(ValueError) as exc:
        implementation.deals_needing_followup(
            [deal],
            today=datetime(2026, 11, 1),
        )

    message = str(exc.value).lower()
    assert "today-first" in message
    assert any(token in message for token in ("today", "timezone", "time zone", "offset"))


@pytest.mark.parametrize("stage", ["Closed - Pending", "ClosedOther", "Qualified", "sourcing", None, 17])
def test_unknown_stage_raises_value_error(implementation, stage):
    deal = make_deal(NOW.isoformat(), stage=stage, name="Unknown stage", deal_id="unknown-stage")

    with pytest.raises(ValueError) as exc:
        implementation.deals_needing_followup([deal], today=NOW)

    message = str(exc.value).lower()
    assert "unknown-stage" in message
    assert "stage" in message
    assert "unknown" in message or "unsupported" in message


@pytest.mark.parametrize("name", [None, "", "   "])
def test_open_deal_requires_nonempty_name_with_id_in_error(implementation, name):
    deal = make_deal(
        NOW.isoformat(),
        name=name,
        deal_id="missing-name",
    )

    with pytest.raises(ValueError) as exc:
        implementation.deals_needing_followup([deal], today=NOW)

    message = str(exc.value).lower()
    assert "missing-name" in message
    assert "name" in message
    assert any(token in message for token in ("nonempty", "required", "missing", "string"))


def test_open_deal_missing_name_reports_input_index(implementation):
    deal = make_deal(
        NOW.isoformat(),
        include_name=False,
        deal_id=None,
    )

    with pytest.raises(ValueError) as exc:
        implementation.deals_needing_followup([deal], today=NOW)

    message = str(exc.value).lower()
    assert "name" in message
    assert "index" in message and "0" in message


def test_open_deal_missing_last_contact_is_not_treated_as_never_contacted(implementation):
    deal = make_deal(
        name="Missing contact field",
        deal_id="missing-contact",
        include_contact=False,
    )

    with pytest.raises(ValueError) as exc:
        implementation.deals_needing_followup([deal], today=NOW)

    message = str(exc.value).lower()
    assert "missing-contact" in message
    assert "last_contact" in message
    assert "required" in message or "missing" in message


def test_explicit_none_contact_is_included(implementation):
    deal = make_deal(None, name="Never contacted", deal_id="never-contacted")

    assert implementation.deals_needing_followup([deal], today=NOW) == ["Never contacted"]


def test_name_is_used_as_error_context_when_id_is_missing(implementation):
    deal = make_deal(
        "2026-10-01T00:00:00",
        name="Named fallback",
        deal_id=None,
    )

    with pytest.raises(ValueError) as exc:
        implementation.deals_needing_followup([deal], today=NOW)

    message = str(exc.value).lower()
    assert "named fallback" in message
    assert any(token in message for token in ("timezone", "time zone", "offset"))


def test_empty_input_returns_empty_list(implementation):
    assert implementation.deals_needing_followup([], today=NOW) == []


def test_input_is_not_modified(implementation):
    deals = [
        make_deal((NOW - timedelta(days=10)).isoformat(), name="Recent", deal_id="recent"),
        make_deal((NOW - timedelta(days=20)).isoformat(), name="Stale", deal_id="stale"),
        make_deal(None, name="Never", deal_id="never"),
    ]
    original = deepcopy(deals)

    implementation.deals_needing_followup(deals, today=NOW)

    assert deals == original


def test_separate_calls_do_not_share_results_or_state(implementation):
    stale = [make_deal((NOW - timedelta(days=14)).isoformat(), name="Stale", deal_id="stale")]
    recent = [make_deal((NOW - timedelta(days=13)).isoformat(), name="Recent", deal_id="recent")]

    assert implementation.deals_needing_followup(stale, today=NOW) == ["Stale"]
    assert implementation.deals_needing_followup(recent, today=NOW) == []
    assert implementation.deals_needing_followup(stale, today=NOW) == ["Stale"]


def test_missing_today_uses_patched_current_utc_time(implementation, monkeypatch):
    class FixedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            fixed_now = cls(2026, 11, 1, tzinfo=timezone.utc)
            if tz is None:
                return fixed_now.replace(tzinfo=None)
            return fixed_now.astimezone(tz)

    monkeypatch.setattr(implementation, "datetime", FixedDateTime)
    deal = make_deal(
        (NOW - timedelta(hours=336)).isoformat(),
        name="Default today boundary",
        deal_id="default-today",
    )

    assert implementation.deals_needing_followup([deal]) == ["Default today boundary"]
