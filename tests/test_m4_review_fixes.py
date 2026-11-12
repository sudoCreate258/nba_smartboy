"""Fixes from the PR #10 (M4) semantic review."""
import datetime
import json
from io import StringIO

import pytest
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.exceptions import ImproperlyConfigured, ValidationError
from django.core.management import call_command
from django.test import Client, override_settings
from django.urls import reverse

from core.models import (Contributor, DailySnapshot, DiscomfortCheck, ProbeSession, Reset, Supersession,
                         WorkBlock)
from core.services.export import ImportError_, export_lines, import_lines
from core.services.records import save_record
from tests.test_export import seed, wipe
from ui.models import ModuleSetting
from ui.today import contributor_for

UTC = datetime.timezone.utc
T = datetime.datetime(2026, 11, 11, 15, 0, tzinfo=UTC)
MIN = datetime.timedelta(minutes=1)


@pytest.fixture
def mike(db):
    return Contributor.objects.get(handle="mike")


@pytest.fixture
def client_in(client, db):
    cache.clear()
    client.force_login(get_user_model().objects.create_user("owner", password="a-long-test-password"))
    return client


def check(mike, score, at=T):
    return DiscomfortCheck(contributor=mike, at=at, area="neck", score=score, trigger="other")


# --- shared write path -----------------------------------------------------------

def test_stale_correction_is_refused_inside_the_lock(mike):
    a, _ = save_record(check(mike, 2))
    save_record(check(mike, 3), supersedes=a)  # someone else corrected A first
    with pytest.raises(ValidationError, match="already corrected"):
        save_record(check(mike, 4), supersedes=a)
    assert DiscomfortCheck.objects.current().count() == 1  # no fork


def test_revert_only_within_the_same_record(mike):
    x, _ = save_record(check(mike, 2))
    y, _ = save_record(check(mike, 5, at=T + MIN))
    clone_of_x = check(mike, 2)  # identical to X, offered as a correction of Y
    with pytest.raises(ValidationError, match="different record"):
        save_record(clone_of_x, supersedes=y)
    assert set(DiscomfortCheck.objects.current()) == {x, y}


def test_stale_snapshot_correction_is_refused(mike):
    day = datetime.date(2026, 11, 11)
    a, _ = save_record(DailySnapshot(contributor=mike, date=day, source="manual", sleep_score=80))
    save_record(DailySnapshot(contributor=mike, date=day, source="manual", sleep_score=81), supersedes=a)
    with pytest.raises(ValidationError, match="already corrected"):
        save_record(DailySnapshot(contributor=mike, date=day, source="manual", sleep_score=82), supersedes=a)
    assert DailySnapshot.objects.current().get().sleep_score == 81


# --- admin ---------------------------------------------------------------------

@pytest.fixture
def admin_in(client, db):
    cache.clear()
    client.force_login(get_user_model().objects.create_superuser("root", "r@localhost", "pw"))
    return client


def test_admin_correction_of_a_superseded_record_is_a_form_error(admin_in, mike):
    a, _ = save_record(check(mike, 2))
    save_record(check(mike, 3), supersedes=a)
    post = {"contributor": mike.pk, "at_0": "2026-11-11", "at_1": "10:00:00", "area": "neck", "score": "4",
            "trigger": "other", "countermove": "none", "notes": ""}
    resp = admin_in.post(reverse("admin:core_discomfortcheck_add") + f"?supersedes={a.cid}", post)
    assert resp.status_code == 200 and b"already corrected" in resp.content
    assert DiscomfortCheck.objects.count() == 2


def test_admin_login_is_rate_limited(db):
    cache.clear()
    get_user_model().objects.create_superuser("root", "r@localhost", "a-long-test-password")
    c = Client()
    for _ in range(5):
        assert c.post("/admin/login/", {"username": "root", "password": "wrong"}).status_code == 200
    blocked = c.post("/admin/login/", {"username": "root", "password": "a-long-test-password"})
    assert blocked.status_code == 429 and b"Too many failed attempts" in blocked.content
    cache.clear()


def test_successful_login_clears_the_address_count_too(client, db):
    cache.clear()
    get_user_model().objects.create_user("owner", password="a-long-test-password")
    for _ in range(4):
        client.post(reverse("ui:login"), {"username": "owner", "password": "wrong"})
    client.post(reverse("ui:login"), {"username": "owner", "password": "a-long-test-password"})
    assert cache.get("login-fail:addr:127.0.0.1") is None
    cache.clear()


# --- offline replay -----------------------------------------------------------------

FORMS = {
    "discomfort": {"at": "2026-11-11T10:25", "area": "neck", "score": "3", "trigger": "end_of_block",
                   "countermove": "none", "notes": ""},
    "snapshot": {"date": "2026-11-11", "sleep_score": "81", "bia_timing": "unknown", "notes": ""},
    "probe": {"started_at": "2026-11-11T09:00", "kind": "mini_puzzle", "accuracy_pct": "80", "notes": ""},
    "work": {"start": "2026-11-11T09:30", "end": "2026-11-11T10:20", "task_type": "code", "notes": ""},
}


def replay(client, kind, data):
    return client.post(reverse("ui:checkin", args=[kind]), data, HTTP_X_OFFLINE_REPLAY="queue")


@pytest.mark.parametrize("kind", list(FORMS))
def test_offline_duplicate_is_already_saved_for_every_form(client_in, mike, kind):
    first = replay(client_in, kind, FORMS[kind]).json()
    second = replay(client_in, kind, FORMS[kind]).json()
    assert first["outcome"] == "created" and second["outcome"] == "skipped" and second["cid"] == first["cid"]


def test_replay_of_a_stale_correction_is_409_json(client_in, mike):
    a, _ = save_record(check(mike, 2))
    save_record(check(mike, 3), supersedes=a)
    resp = replay(client_in, "discomfort", {**FORMS["discomfort"], "supersedes": a.cid})
    assert resp.status_code == 409 and resp.json()["outcome"] == "stale"


def test_replay_of_an_unknown_record_or_disabled_module_is_404_json(client_in, mike):
    resp = replay(client_in, "discomfort", {**FORMS["discomfort"], "supersedes": "bafkreinope"})
    assert resp.status_code == 404 and resp.json()["outcome"] == "gone"
    ModuleSetting.objects.create(module_id="zone", enabled=False)
    resp = replay(client_in, "discomfort", FORMS["discomfort"])
    assert resp.status_code == 404 and resp.json()["outcome"] == "gone"
    assert resp["Content-Type"] == "application/json"


def test_csrf_token_endpoint(client_in, client):
    resp = client_in.get(reverse("ui:csrf_token"))
    assert resp.status_code == 200 and len(resp.json()["token"]) >= 32 and resp["Cache-Control"] == "no-store"
    assert Client().get(reverse("ui:csrf_token")).status_code == 302


def test_replay_with_a_fresh_token_passes_csrf_after_relogin(db):
    """The queue fetches /csrf-token/ before each send, so a re-login (token rotation) does not strand it."""
    cache.clear()
    user = get_user_model().objects.create_user("owner", password="a-long-test-password")
    strict = Client(enforce_csrf_checks=True)
    strict.force_login(user)
    stale = strict.get(reverse("ui:csrf_token")).json()["token"]
    strict.logout()
    strict.force_login(user)  # rotates the CSRF secret
    url = reverse("ui:checkin", args=["discomfort"])
    assert strict.post(url, {**FORMS["discomfort"], "csrfmiddlewaretoken": stale},
                       HTTP_X_OFFLINE_REPLAY="queue").status_code == 403
    fresh = strict.get(reverse("ui:csrf_token")).json()["token"]
    resp = strict.post(url, {**FORMS["discomfort"], "csrfmiddlewaretoken": fresh}, HTTP_X_OFFLINE_REPLAY="queue")
    assert resp.status_code == 200 and resp.json()["outcome"] == "created"


def test_correct_this_for_a_reset(client_in, mike):
    now = datetime.datetime.now(UTC).replace(second=0, microsecond=0)
    before = ProbeSession(contributor=mike, started_at=now - 30 * MIN, kind="mini_puzzle", accuracy_pct=70)
    after = ProbeSession(contributor=mike, started_at=now - 5 * MIN, kind="mini_puzzle", accuracy_pct=80)
    before.save()
    after.save()
    old, _ = save_record(Reset(contributor=mike, at=now - 20 * MIN, kind="walk", before_probe_cid=before.cid,
                               after_probe_cid=after.cid))
    page = client_in.get(reverse("ui:checkin", args=["reset"]) + f"?correct={old.cid}").content.decode()
    assert f'value="{before.cid}" selected' in page
    at = (now - 20 * MIN).astimezone(mike.tzinfo).strftime("%Y-%m-%dT%H:%M")
    resp = client_in.post(reverse("ui:checkin", args=["reset"]), {
        "at": at, "kind": "breathing", "before_probe_cid": before.cid, "after_probe_cid": after.cid, "notes": "",
        "supersedes": old.cid})
    assert resp.status_code == 302 and Reset.objects.current().get().kind == "breathing"


# --- service worker -------------------------------------------------------------------

def test_service_worker_never_caches_api_download_or_no_store(client, db):
    body = client.get("/sw.js").content.decode()
    for path in ("/api/", "/my-data/", "/csrf-token/", "/logout/", "/admin/"):
        assert f'"{path}"' in body
    assert 'indexOf("no-store") === -1' in body and 'url.pathname.indexOf("/static/") !== 0' in body
    assert '"purge-pages"' in body


# --- import validation ----------------------------------------------------------------

def _lines(mike):
    seed(mike)
    lines = [json.loads(line) for line in export_lines(mike)]
    wipe()
    return lines


def _dump(items):
    return [json.dumps(i) for i in items]


def test_import_rejects_corrections_to_unknown_or_cross_kind_records(mike):
    lines = _lines(mike)
    sup = next(i for i, item in enumerate(lines) if item["type"] == "supersession")
    unknown = [dict(item) for item in lines]
    unknown[sup]["new_cid"] = "bafkreiunknown"
    with pytest.raises(ImportError_, match=f"line {sup + 1}: correction refers to a record"):
        import_lines(_dump(unknown))
    cross = [dict(item) for item in lines]
    other_kind = next(i["cid"] for i in lines if i["type"] == "record" and i["kind"] == "weekly_check")
    cross[sup]["new_cid"] = other_kind
    cross.append(cross.pop(sup))  # after the weekly check line, so both endpoints exist
    with pytest.raises(ImportError_, match="same kind"):
        import_lines(_dump(cross))
    selfref = [dict(item) for item in lines]
    selfref[sup]["new_cid"] = selfref[sup]["old_cid"]
    with pytest.raises(ImportError_, match="cannot supersede itself"):
        import_lines(_dump(selfref))
    assert not Supersession.objects.exists()


@pytest.mark.parametrize("mutate,match", [
    (lambda r: r.pop("cid"), "'cid' must be a str"),
    (lambda r: r.update(fields="x"), "'fields' must be a dict"),
    (lambda r: r.update(extra=1), "unexpected keys extra"),
    (lambda r: r["fields"].update(bogus=1), "CID does not match|unknown field"),
])
def test_import_schema_errors_are_line_numbered(mike, mutate, match):
    lines = _lines(mike)
    mutate(lines[1])
    with pytest.raises(ImportError_, match=f"line 2: ({match})"):
        import_lines(_dump(lines))


def test_import_header_must_be_complete(db):
    with pytest.raises(ImportError_, match="line 1"):
        import_lines(['{"type": "export", "format": "nymbus-jsonl", "version": 1}'])
    with pytest.raises(ImportError_, match="line 1: not a nymbus-jsonl export header"):
        import_lines(["[1, 2]"])


def test_import_restores_the_export_time_zone(mike):
    lines = _lines(mike)
    lines[0]["timezone"] = "Europe/Berlin"
    import_lines(_dump(lines))
    assert Contributor.objects.get(handle="mike").timezone == "Europe/Berlin"


def test_import_command_reports_schema_errors_cleanly(mike, tmp_path):
    lines = _lines(mike)
    lines[1].pop("kind")
    p = tmp_path / "bad.jsonl"
    p.write_text("\n".join(_dump(lines)), encoding="utf-8")
    from django.core.management.base import CommandError
    with pytest.raises(CommandError, match="Nothing imported: line 2"):
        call_command("import_my_data", str(p), stdout=StringIO())


# --- configuration --------------------------------------------------------------------------

@override_settings(TWIN_CONTRIBUTOR="nobody")
def test_missing_contributor_is_a_clear_configuration_error(db):
    with pytest.raises(ImproperlyConfigured, match="TWIN_CONTRIBUTOR='nobody'"):
        contributor_for(None)
