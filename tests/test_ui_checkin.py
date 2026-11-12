"""M4-T2: check-in forms for the five record types and "Correct this" (R1)."""
import datetime
import re
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from core.models import (Contributor, DailySnapshot, DiscomfortCheck, ProbeSession, Reset, Supersession,
                         WorkBlock)
from core.services.records import save_record
from core.services.snapshots import CREATED, SKIPPED, SUPERSEDED

NY = datetime.timezone(datetime.timedelta(hours=-5))  # New York in November (EST)


@pytest.fixture
def mike(db):
    return Contributor.objects.get(handle="mike")


@pytest.fixture
def client_in(client, db):
    client.force_login(get_user_model().objects.create_user("owner", password="a-long-test-password"))
    return client


def url(kind, correct=None):
    u = reverse("ui:checkin", args=[kind])
    return u + (f"?correct={correct}" if correct else "")


VALID = {
    "snapshot": {"date": "2026-11-11", "sleep_score": "81", "bedtime": "2026-11-10T22:50", "wake_time": "2026-11-11T06:40",
                 "resting_hr_sleep": "52", "hrv": "48", "bia_timing": "pre_session", "weight_kg": "70.0", "notes": ""},
    "probe": {"started_at": "2026-11-11T09:00", "kind": "mini_puzzle", "n_items": "5", "accuracy_pct": "80",
              "median_solve_s": "11.5", "notes": ""},
    "work": {"start": "2026-11-11T09:30", "end": "2026-11-11T10:20", "task_type": "code", "posture": "sit",
             "planned_length_min": "50", "interruptions": "0", "absorption": "4", "effort": "3", "notes": ""},
    "discomfort": {"at": "2026-11-11T10:25", "area": "neck", "score": "3", "trigger": "end_of_block",
                   "countermove": "chin_tuck_pullapart", "notes": ""},
}
MODELS = {"snapshot": DailySnapshot, "probe": ProbeSession, "work": WorkBlock, "discomfort": DiscomfortCheck}


@pytest.mark.parametrize("kind", ["snapshot", "probe", "work", "discomfort", "reset"])
def test_forms_render_without_javascript(client_in, mike, kind):
    page = client_in.get(url(kind))
    html = page.content.decode()
    assert page.status_code == 200 and 'method="post"' in html  # a plain HTML form; JS only enhances it
    assert re.findall(r"<script[^>]*>", html) == ['<script src="/static/ui/offline.js" defer>']
    assert 'name="csrfmiddlewaretoken"' in html and 'type="submit"' in html


@pytest.mark.parametrize("kind", list(VALID))
def test_valid_post_saves_through_the_write_path(client_in, mike, kind):
    resp = client_in.post(url(kind), VALID[kind], follow=True)
    assert resp.redirect_chain[-1][0] == reverse("ui:home")
    record = MODELS[kind].objects.get()
    assert record.cid.startswith("bafkrei") and record.contributor == mike
    assert "saved." in resp.content.decode()


def test_local_times_are_read_in_the_contributor_zone(client_in, mike):
    client_in.post(url("work"), VALID["work"])
    b = WorkBlock.objects.get()
    assert b.start == datetime.datetime(2026, 11, 11, 14, 30, tzinfo=datetime.timezone.utc)
    snap_page = client_in.post(url("snapshot"), VALID["snapshot"])
    assert snap_page.status_code == 302 and DailySnapshot.objects.get().source == "manual"


@pytest.mark.parametrize("kind,field,value,message", [
    ("snapshot", "sleep_score", "120", "less than or equal to 100"),
    ("probe", "accuracy_pct", "101", "less than or equal to 100"),
    ("work", "end", "2026-11-11T09:00", "end must be after start"),
    ("discomfort", "score", "11", "less than or equal to 10"),
])
def test_invalid_post_shows_the_error_next_to_the_field(client_in, mike, kind, field, value, message):
    resp = client_in.post(url(kind), {**VALID[kind], field: value})
    html = resp.content.decode()
    assert resp.status_code == 200 and message in html
    assert MODELS[kind].objects.count() == 0
    if kind != "work":  # the end-before-start rule is a form-level error
        assert f'id="err-{field}"' in html and 'aria-invalid="true"' in html


def test_post_sauna_body_composition_is_rejected(client_in, mike):
    resp = client_in.post(url("snapshot"), {**VALID["snapshot"], "bia_timing": "post_sauna"})
    assert "Post-sauna" in resp.content.decode() and DailySnapshot.objects.count() == 0


def test_dst_ambiguous_local_time_is_rejected(client_in, mike):
    resp = client_in.post(url("discomfort"), {**VALID["discomfort"], "at": "2026-11-01T01:30"})
    assert resp.status_code == 200 and DiscomfortCheck.objects.count() == 0
    assert "couldn" in resp.content.decode()  # Django: "...couldn't be interpreted in time zone ..."


def test_overlapping_work_block_shows_the_clash(client_in, mike):
    client_in.post(url("work"), VALID["work"])
    resp = client_in.post(url("work"), {**VALID["work"], "start": "2026-11-11T10:00", "end": "2026-11-11T11:00"})
    assert "Overlaps work block 2026-11-11 09:30-10:20 America/New_York" in resp.content.decode()


@pytest.mark.parametrize("kind", list(VALID))
def test_same_post_twice_is_already_saved(client_in, mike, kind):
    client_in.post(url(kind), VALID[kind])
    resp = client_in.post(url(kind), VALID[kind], follow=True)
    assert "already saved" in resp.content.decode()
    assert MODELS[kind].objects.count() == 1


@pytest.mark.parametrize("kind,field,new", [
    ("snapshot", "sleep_score", "77"), ("probe", "accuracy_pct", "60"), ("work", "absorption", "2"),
    ("discomfort", "score", "5"),
])
def test_correct_this_creates_a_correction(client_in, mike, kind, field, new):
    client_in.post(url(kind), VALID[kind])
    old = MODELS[kind].objects.get()
    page = client_in.get(url(kind, old.cid))
    assert page.status_code == 200 and old.cid in page.content.decode() and "Save correction" in page.content.decode()
    resp = client_in.post(url(kind), {**VALID[kind], field: new, "supersedes": old.cid}, follow=True)
    assert "saved as a correction" in resp.content.decode()
    current = MODELS[kind].objects.current().get()
    assert current.pk != old.pk and str(getattr(current, field)).startswith(new)
    assert Supersession.objects.filter(old_cid=old.cid, new_cid=current.cid).exists()
    assert MODELS[kind].objects.count() == 2


def test_correct_form_is_prefilled_in_local_time(client_in, mike):
    client_in.post(url("work"), VALID["work"])
    old = WorkBlock.objects.get()
    html = client_in.get(url("work", old.cid)).content.decode()
    assert 'value="2026-11-11T09:30"' in html and 'value="2026-11-11T10:20"' in html


def test_correction_keeps_fields_the_form_does_not_show(client_in, mike):
    snap = DailySnapshot(contributor=mike, date=datetime.date(2026, 11, 11), source="samsung_health", sleep_score=80,
                         spo2="96.5", sleep_duration_min=420)
    snap.save()
    client_in.post(url("snapshot"), {"date": "2026-11-11", "sleep_score": "82", "bia_timing": "unknown", "notes": "",
                                     "supersedes": snap.cid})
    new = DailySnapshot.objects.current().get()
    assert new.sleep_score == 82 and new.spo2 == Decimal("96.5") and new.sleep_duration_min == 420
    assert new.source == "samsung_health"


def test_snapshot_correction_keeps_the_date(client_in, mike):
    client_in.post(url("snapshot"), VALID["snapshot"])
    old = DailySnapshot.objects.get()
    resp = client_in.post(url("snapshot"), {**VALID["snapshot"], "date": "2026-11-12", "wake_time": "2026-11-12T06:40",
                                            "supersedes": old.cid})
    assert "keeps the date" in resp.content.decode() and DailySnapshot.objects.count() == 1


def test_correcting_a_superseded_record_is_refused(client_in, mike):
    client_in.post(url("discomfort"), VALID["discomfort"])
    old = DiscomfortCheck.objects.get()
    client_in.post(url("discomfort"), {**VALID["discomfort"], "score": "4", "supersedes": old.cid})
    resp = client_in.get(url("discomfort", old.cid), follow=True)
    assert "already corrected" in resp.content.decode()


def test_unknown_kind_or_cid_is_404(client_in, mike):
    assert client_in.get(reverse("ui:checkin", args=["sleep"])).status_code == 404
    assert client_in.get(url("work", "bafkreinope")).status_code == 404


def test_other_contributors_records_cannot_be_corrected(client_in, mike):
    sam = Contributor.objects.create(handle="sam")
    DiscomfortCheck(contributor=sam, at=datetime.datetime(2026, 11, 11, 15, tzinfo=datetime.timezone.utc), area="hip",
                    score=2, trigger="other").save()
    assert client_in.get(url("discomfort", DiscomfortCheck.objects.get().cid)).status_code == 404


# --- reset ------------------------------------------------------------------

def _minis(mike):
    now = datetime.datetime.now(datetime.timezone.utc).replace(second=0, microsecond=0)
    before = ProbeSession(contributor=mike, started_at=now - datetime.timedelta(minutes=30), kind="mini_puzzle",
                          accuracy_pct=70)
    after = ProbeSession(contributor=mike, started_at=now - datetime.timedelta(minutes=5), kind="mini_puzzle",
                         accuracy_pct=80)
    before.save()
    after.save()
    at = (now - datetime.timedelta(minutes=20)).astimezone(mike.tzinfo).strftime("%Y-%m-%dT%H:%M")
    return before, after, at


def test_reset_picks_recent_mini_probes(client_in, mike):
    before, after, at = _minis(mike)
    html = client_in.get(url("reset")).content.decode()
    assert f'value="{before.cid}"' in html and "70.0%" in html
    resp = client_in.post(url("reset"), {"at": at, "kind": "walk", "duration_min": "10", "before_probe_cid": before.cid,
                                         "after_probe_cid": after.cid, "notes": ""})
    assert resp.status_code == 302
    r = Reset.objects.get()
    assert (r.before_probe_cid, r.after_probe_cid) == (before.cid, after.cid)


def test_reset_with_swapped_probes_shows_the_rule(client_in, mike):
    before, after, at = _minis(mike)
    resp = client_in.post(url("reset"), {"at": at, "kind": "walk", "before_probe_cid": after.cid,
                                         "after_probe_cid": before.cid, "notes": ""})
    assert "must start before the reset" in resp.content.decode() and Reset.objects.count() == 0


# --- shared write path --------------------------------------------------------

def test_save_record_outcomes(mike):
    t = datetime.datetime(2026, 11, 11, 15, tzinfo=datetime.timezone.utc)
    make = lambda score: DiscomfortCheck(contributor=mike, at=t, area="neck", score=score, trigger="other")  # noqa: E731
    a, outcome = save_record(make(2))
    assert outcome == CREATED
    assert save_record(make(2))[1] == SKIPPED
    b, outcome = save_record(make(3), supersedes=a)
    assert outcome == SUPERSEDED and list(DiscomfortCheck.objects.current()) == [b]
    back, outcome = save_record(make(2), supersedes=b)  # revert to the first version: no new row
    assert outcome == SUPERSEDED and back.pk == a.pk and DiscomfortCheck.objects.count() == 2
    assert list(DiscomfortCheck.objects.current()) == [a]
