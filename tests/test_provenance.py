import datetime
from decimal import Decimal

import pytest

from nymbus.provenance import canonical_bytes, compute_cid

FIELDS = {"date": datetime.date(2026, 11, 11), "weight_kg": Decimal("70.0"), "hrv": None}


def test_canonical_bytes_exact():
    assert canonical_bytes("daily_snapshot", "mike", FIELDS) == (
        b'{"contributor":"mike","fields":{"date":"2026-11-11","hrv":null,'
        b'"weight_kg":"70.0"},"kind":"daily_snapshot"}'
    )


def test_canonical_bytes_key_order_independent():
    a = canonical_bytes("k", "mike", {"a": 1, "b": 2})
    b = canonical_bytes("k", "mike", {"b": 2, "a": 1})
    assert a == b


def test_canonical_bytes_keeps_unicode():
    assert "é".encode() in canonical_bytes("k", "mike", {"notes": "é"})


def test_cid_known_vector():
    # sha256("") raw CIDv1 is a well-known value.
    assert compute_cid(b"") == "bafkreihdwdcefgh4dqkjv67uzcmw7ojee6xedzdetojuzjevtenxquvyku"


def test_cid_fixed_record():
    # Pin updated in the synthetic-fixture commit (planner 013): the fields changed, the algorithm did not.
    cid = compute_cid(canonical_bytes("daily_snapshot", "mike", FIELDS))
    assert cid == "bafkreigxku4er6ixo4eraxom5fk2hsuehrecwigzp2qa5vmpuyrubvabqa"


def test_cid_format():
    cid = compute_cid(b"x")
    assert cid.startswith("bafkrei")
    assert cid == cid.lower()
    assert "=" not in cid
    assert len(cid) == 59


def test_cid_deterministic():
    d = canonical_bytes("daily_snapshot", "mike", FIELDS)
    assert compute_cid(d) == compute_cid(d)


def test_cid_changes_with_content():
    base = compute_cid(canonical_bytes("daily_snapshot", "mike", FIELDS))
    assert base != compute_cid(canonical_bytes("daily_snapshot", "mike", {**FIELDS, "hrv": 41}))
    assert base != compute_cid(canonical_bytes("daily_snapshot", "other", FIELDS))
    assert base != compute_cid(canonical_bytes("probe_session", "mike", FIELDS))


def test_naive_datetime_raises():
    with pytest.raises(ValueError):
        canonical_bytes('k', 'mike', {'t': datetime.datetime(2026, 1, 1, 7, 0)})


def test_aware_datetimes_equal_instant_same_bytes():
    a = datetime.datetime(2026, 1, 1, 12, 0, tzinfo=datetime.timezone.utc)
    b = datetime.datetime(2026, 1, 1, 7, 0, tzinfo=datetime.timezone(datetime.timedelta(hours=-5)))
    assert canonical_bytes('k', 'mike', {'t': a}) == canonical_bytes('k', 'mike', {'t': b})

