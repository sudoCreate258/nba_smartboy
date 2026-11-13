"""027 Part B: POST /api/twin/minute (token, origin, size, idempotency, nulls). Synthetic fixtures only."""
import json
from io import StringIO
from pathlib import Path

import pytest
from django.core.management import call_command
from django.test import Client

from core.models import TwinMinute

MINUTE = json.loads((Path(__file__).resolve().parent / "fixtures" / "twin_minute.SYNTHETIC.json").read_text("utf-8"))
URL = "/api/twin/minute"
TOKEN = "test-only-token-" + "x" * 30
DTOM = "http://127.0.0.1:8765"


@pytest.fixture
def on(settings, db):
    settings.DTOM_INGEST_TOKEN = TOKEN
    return Client(enforce_csrf_checks=True)  # the view must work without a CSRF token


def post(client, doc=MINUTE, token=TOKEN, origin=DTOM, raw=None, content_type="application/json"):
    headers = {"HTTP_X_NYMBUS_TOKEN": token} if token is not None else {}
    if origin:
        headers["HTTP_ORIGIN"] = origin
    return client.post(URL, raw if raw is not None else json.dumps(doc), content_type=content_type, **headers)


def test_good_post_stores_a_minute(on):
    resp = post(on)
    assert resp.status_code == 201 and resp.json()["outcome"] == "created"
    assert resp["Access-Control-Allow-Origin"] == DTOM and resp["Cache-Control"] == "no-store"
    m = TwinMinute.objects.get()
    assert m.cid == resp.json()["cid"] and m.source == "dtom" and m.contributor.handle == "mike"
    assert m.t_start.isoformat() == "2026-11-13T15:05:00+00:00"
    assert post(on, origin="http://localhost:8765").status_code == 200  # the other dtom origin; a duplicate
    assert post(on, origin=None).status_code == 200  # a non-browser client with the token (no Origin header)


def test_nulls_are_stored_as_null(on):
    post(on)
    data = TwinMinute.objects.get().data
    assert data["side_view_pct"] is None and data["load_pct_avg"]["back"] is None
    assert data["face"]["brow_tension"] is None and data["events"][1]["region"] is None


def test_bad_or_missing_token_and_unset_env(on, settings):
    assert post(on, token="wrong").status_code == 401
    assert post(on, token=None).status_code == 401
    settings.DTOM_INGEST_TOKEN = ""
    resp = post(on, token="")
    assert resp.status_code == 503 and "not set" in resp.json()["error"]
    assert not TwinMinute.objects.exists()


def test_wrong_origin_is_refused_even_with_the_token(on):
    for origin in ("http://evil.example", "http://127.0.0.1:8000", "https://127.0.0.1:8765", "null"):
        resp = post(on, origin=origin)
        assert resp.status_code == 403 and "Access-Control-Allow-Origin" not in resp, origin
    preflight = on.options(URL, HTTP_ORIGIN="http://evil.example")
    assert preflight.status_code == 403
    assert not TwinMinute.objects.exists()


def test_preflight_from_dtom(on):
    resp = on.options(URL, HTTP_ORIGIN=DTOM, HTTP_ACCESS_CONTROL_REQUEST_METHOD="POST")
    assert resp.status_code == 204 and resp["Access-Control-Allow-Origin"] == DTOM
    assert "X-Nymbus-Token" in resp["Access-Control-Allow-Headers"] and resp["Access-Control-Allow-Methods"] == "POST"
    assert "Access-Control-Allow-Credentials" not in resp
    assert on.get(URL, HTTP_ORIGIN=DTOM).status_code == 405


def test_oversize_bad_json_and_bad_minute(on):
    big = dict(MINUTE, padding="x" * (64 * 1024))
    assert post(on, big).status_code == 413
    assert post(on, raw="{not json").status_code == 400
    assert post(on, raw="{}", content_type="text/plain").status_code == 415
    bad = dict(MINUTE, side_view_pct="50")
    resp = post(on, bad)
    assert resp.status_code == 400 and "side_view_pct" in resp.json()["error"]
    assert not TwinMinute.objects.exists()


def test_duplicate_minute_is_idempotent_and_a_changed_one_conflicts(on):
    first = post(on).json()["cid"]
    again = post(on)
    assert again.status_code == 200 and again.json() == {"outcome": "duplicate", "cid": first}
    changed = json.loads(json.dumps(MINUTE))
    changed["face"]["yawns"] = 2
    resp = post(on, changed)
    assert resp.status_code == 409 and resp.json()["cid"] == first
    later = dict(MINUTE, t_start="2026-11-13T15:06:00Z", t_end="2026-11-13T15:07:00Z")
    assert post(on, later).status_code == 201
    assert TwinMinute.objects.count() == 2


def test_make_ingest_token_prints_a_fresh_token():
    out, err = StringIO(), StringIO()
    call_command("make_ingest_token", stdout=out, stderr=err)
    call_command("make_ingest_token", stdout=(second := StringIO()), stderr=StringIO())
    line = out.getvalue().strip()
    assert line.startswith("DTOM_INGEST_TOKEN=") and len(line) > len("DTOM_INGEST_TOKEN=") + 40
    assert line != second.getvalue().strip() and "not stored" in err.getvalue()
