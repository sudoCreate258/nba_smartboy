"""M5-T5: deposit statement per month and category, its CID, page and download; no currency (R6, R10)."""
import datetime
import json
import re

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from core.models import Contributor
from ledger import service, statement
from ledger.models import AccessEvent, Grant, Revocation
from nymbus import ledger
from tests.test_export import seed

UTC = datetime.timezone.utc
OCT = datetime.datetime(2026, 10, 20, 15, 0, tzinfo=UTC)
NOV = datetime.datetime(2026, 11, 12, 15, 0, tzinfo=UTC)
H = datetime.timedelta(hours=1)


@pytest.fixture
def mike(db):
    m = Contributor.objects.get(handle="mike")
    seed(m)
    service.grant(m, "probes", "self-analysis", "weekly review", now=OCT)
    service.grant(m, "probes", "sim-research-partner", "fatigue study", now=OCT)
    service.grant(m, "training", "sim-research-partner", "volume study", now=OCT)
    service.simulated_read(m, "self-analysis", "probes", now=OCT + H)        # October: 2 records
    for i in range(2):                                                        # November: 2 x 2 + 1 x 2 + 1 x 3
        service.simulated_read(m, "self-analysis", "probes", now=NOV + i * H)
    service.simulated_read(m, "sim-research-partner", "probes", now=NOV + 3 * H)
    service.simulated_read(m, "sim-research-partner", "training", now=NOV + 4 * H)
    return m


@pytest.fixture
def client_in(client, mike):
    client.force_login(get_user_model().objects.create_user("owner", password="a-long-test-password"))
    return client


def test_rows_and_totals_reconcile_with_the_events(mike):
    s = statement.build(mike, "2026-11")
    assert s["unit"] == "simulated credits" and s["months"] == ["2026-11", "2026-10"]
    assert [(r["category"], r["recipient"], r["purpose"], r["reads"], r["records_accessed"], r["distinct_records"],
             r["units"]) for r in s["rows"]] == [
        ("probes", "self-analysis", "weekly review", 2, 4, 2, 4),
        ("probes", "sim-research-partner", "fatigue study", 1, 2, 2, 2),
        ("training", "sim-research-partner", "volume study", 1, 3, 3, 3),
    ]
    assert s["totals"] == [{"category": "probes", "reads": 3, "records_accessed": 6, "units": 6},
                           {"category": "training", "reads": 1, "records_accessed": 3, "units": 3}]
    november = [e for e in AccessEvent.objects.all() if e.at.astimezone(mike.tzinfo).month == 11]
    assert s["units_total"] == sum(e.units for e in november) == 9  # the payout math reconciles
    october = statement.build(mike, "2026-10")
    assert october["units_total"] == 2 and len(october["rows"]) == 1
    assert statement.build(mike, "1999-01")["rows"] == []


def test_months_are_local(mike):
    """An event at 02:00 UTC on 1 December is still November in New York."""
    late = datetime.datetime(2026, 12, 1, 2, 0, tzinfo=UTC)
    service.simulated_read(mike, "self-analysis", "probes", now=late)
    assert statement.build(mike, "2026-11")["units_total"] == 11
    assert statement.build(mike, "2026-12")["rows"] == []


def test_cid_covers_the_content(mike):
    s = statement.build(mike, "2026-11")
    assert s["cid"] == ledger.statement_cid("mike", "America/New_York", s) and s["cid"].startswith("b")
    assert s["cid"] != statement.build(mike, "2026-10")["cid"]
    changed = {**s, "rows": [{**s["rows"][0], "units": 5}] + s["rows"][1:]}
    assert ledger.statement_cid("mike", "America/New_York", changed) != s["cid"]


def test_bad_month_falls_back_to_this_month(mike):
    now = datetime.datetime(2026, 11, 20, tzinfo=UTC)
    for bad in ("2026-1", "2026-13", "nope", "", None, "2026-11-01"):
        assert statement.build(mike, bad, now=now)["month"] == "2026-11"


def test_page_and_download(client_in):
    page = client_in.get(reverse("ui:statement") + "?month=2026-11").content.decode()
    assert "Statement 2026-11" in page and "Research partner (simulated)" in page and "fatigue study" in page
    assert "Total: 9 simulated credits" in page and "Cognitive probes" in page
    resp = client_in.get(reverse("ui:statement_download") + "?month=2026-11")
    assert resp["Content-Disposition"] == 'attachment; filename="statement-mike-2026-11.jsonl"'
    assert resp["Cache-Control"] == "no-store"
    lines = [json.loads(line) for line in b"".join(resp.streaming_content).decode().splitlines()]
    header, rows = lines[0], [x for x in lines if x["type"] == "row"]
    assert header["format"] == "nymbus-statement-jsonl" and header["unit"] == "simulated credits"
    recomputed = {"month": header["month"], "unit": header["unit"],
                  "rows": [{k: v for k, v in r.items() if k != "type"} for r in rows]}
    assert ledger.statement_cid(header["contributor"], header["timezone"], recomputed) == header["cid"]
    assert header["cid"] in page
    assert sum(x["units"] for x in lines if x["type"] == "total") == 9
    empty = client_in.get(reverse("ui:statement") + "?month=2020-01").content.decode()
    assert "No reads in 2020-01." in empty


def test_statement_needs_login(client, db):
    assert client.get(reverse("ui:statement")).status_code == 302
    assert client.get(reverse("ui:statement_download")).status_code == 302


MONEY = re.compile(r"(?i)currency|money|price|amount|usd|eur\b|dollar|cost|cash|payment|\$")


def test_there_is_no_currency_field_anywhere(mike):
    for model in (Grant, Revocation, AccessEvent):
        for field in model._meta.get_fields():
            assert not MONEY.search(field.name), (model.__name__, field.name)
    s = statement.build(mike, "2026-11")
    keys = set(s) | {k for r in s["rows"] for k in r} | {k for t in s["totals"] for k in t}
    assert not any(MONEY.search(k) for k in keys), keys
    for line in statement.jsonl(mike, s):
        assert not any(MONEY.search(k) for k in json.loads(line)), line
