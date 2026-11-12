"""M4-T6: "my data" export (JSON Lines), fresh-database import with identical CIDs, download, /api/v0/ (R5)."""
import datetime
import json
from io import StringIO

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import Client
from django.urls import reverse

from core.models import (Contributor, DailySnapshot, DiscomfortCheck, ProbeSession, Reset, Supersession,
                         TrainingSession, TrainingSet, WeeklyCheck, WorkBlock)
from core.services.export import RECORD_MODELS, export_lines, import_lines, verify_line
from core.services.records import save_record

UTC = datetime.timezone.utc
T = datetime.datetime(2026, 11, 10, 14, 0, tzinfo=UTC)
MIN = datetime.timedelta(minutes=1)


@pytest.fixture
def mike(db):
    return Contributor.objects.get(handle="mike")


def seed(mike):
    """One of every record kind plus corrections that exercise the replay order."""
    snap, _ = save_record(DailySnapshot(contributor=mike, date=datetime.date(2026, 11, 10), source="manual",
                                        sleep_score=80, wake_time=T - datetime.timedelta(hours=2), spo2="96.5",
                                        notes="é ünïcode"))
    save_record(DailySnapshot(contributor=mike, date=datetime.date(2026, 11, 10), source="manual", sleep_score=82,
                              wake_time=T - datetime.timedelta(hours=2)))  # supersedes snap (same date)
    before, _ = save_record(ProbeSession(contributor=mike, started_at=T - 10 * MIN, kind="mini_puzzle",
                                         accuracy_pct="70.0", median_solve_s="12.5"))
    after, _ = save_record(ProbeSession(contributor=mike, started_at=T + 20 * MIN, kind="mini_puzzle",
                                        accuracy_pct="80.0", move_time_cv="0.40"))
    save_record(Reset(contributor=mike, at=T, kind="walk", duration_min=10, before_probe_cid=before.cid,
                      after_probe_cid=after.cid))
    save_record(ProbeSession(contributor=mike, started_at=T + 20 * MIN, kind="mini_puzzle", accuracy_pct="85.0"),
                supersedes=after)  # the reset's probe is corrected afterwards
    block, _ = save_record(WorkBlock(contributor=mike, start=T + MIN * 30, end=T + MIN * 80, task_type="code",
                                     posture="sit", absorption=4, interruptions=0))
    save_record(WorkBlock(contributor=mike, start=T + MIN * 30, end=T + MIN * 90, task_type="code", absorption=5,
                          interruptions=0), supersedes=block)  # overlaps the block it replaces
    save_record(DiscomfortCheck(contributor=mike, at=T + MIN * 95, area="wrist", score=6, trigger="end_of_block",
                                sharp_or_numb=True))
    save_record(WeeklyCheck(contributor=mike, week_start=datetime.date(2026, 11, 9), instrument="OLBI",
                            score="2.40", scale_max="4"))
    session, _ = save_record(TrainingSession(contributor=mike, started_at=T + datetime.timedelta(hours=8),
                                             program="RP", meso_week=1, session_rpe="7.5"))
    save_record(TrainingSet(contributor=mike, session_cid=session.cid, order=1, exercise="Bench Press",
                            muscle_group="chest", load_kg="80", reps=10, rir=2))
    fixed, _ = save_record(TrainingSession(contributor=mike, started_at=session.started_at, program="RP",
                                           meso_week=1, session_rpe="7.5", notes="added later"), supersedes=session)
    save_record(TrainingSet(contributor=mike, session_cid=fixed.cid, order=2, exercise="Row", muscle_group="back",
                            reps=10))


def snapshot_state():
    """Everything that defines the data: CIDs per kind, current CIDs, supersession pairs."""
    state = {}
    for model in RECORD_MODELS:
        state[model.record_kind] = (sorted(model.objects.values_list("cid", flat=True)),
                                    sorted(model.objects.current().values_list("cid", flat=True)))
    state["supersessions"] = sorted(Supersession.objects.values_list("old_cid", "new_cid"))
    return state


def wipe():
    """Simulate a fresh database (records are immutable, so bypass the model guards)."""
    from django.db import connection
    with connection.cursor() as cur:
        for model in RECORD_MODELS + [Supersession]:
            cur.execute(f'DELETE FROM "{model._meta.db_table}"')


def test_export_lines_are_self_verifying(mike):
    seed(mike)
    lines = list(export_lines(mike))
    header = json.loads(lines[0])
    assert header == {**header, "type": "export", "format": "nymbus-jsonl", "version": 1, "contributor": "mike",
                      "timezone": "America/New_York"}
    records = [json.loads(line) for line in lines[1:] if json.loads(line)["type"] == "record"]
    assert len(records) == sum(m.objects.count() for m in RECORD_MODELS) == 14
    assert all(verify_line(r) for r in records)
    assert {r["kind"] for r in records} == {m.record_kind for m in RECORD_MODELS}
    assert sum(json.loads(line)["type"] == "supersession" for line in lines) == 4
    snap = next(r for r in records if r["kind"] == "daily_snapshot" and r["fields"]["spo2"] == "96.5")
    assert snap["fields"]["notes"] == "é ünïcode" and snap["fields"]["wake_time"].endswith("+00:00")


def test_round_trip_into_a_fresh_database_keeps_every_cid(mike):
    seed(mike)
    before = snapshot_state()
    lines = list(export_lines(mike))
    wipe()
    assert snapshot_state() != before
    counts = import_lines(lines)
    assert counts == {"records": 14, "supersessions": 4, "contributor": "mike"}
    assert snapshot_state() == before
    assert list(export_lines(mike))[1:] != []  # and it exports again


def test_import_refuses_a_database_with_records(mike):
    seed(mike)
    with pytest.raises(Exception, match="already has records"):
        import_lines(list(export_lines(mike)))


def test_import_rejects_tampered_content_and_rolls_back(mike):
    seed(mike)
    lines = list(export_lines(mike))
    wipe()
    tampered = [json.loads(line) for line in lines]
    first_record = next(i for i, item in enumerate(tampered) if item["type"] == "record")
    tampered[first_record]["fields"]["sleep_score"] = 99
    with pytest.raises(Exception, match="CID does not match"):
        import_lines([json.dumps(i) for i in tampered])
    assert all(not m.objects.exists() for m in RECORD_MODELS)


@pytest.mark.parametrize("bad,match", [
    (['{"type": "record"}'], "header"),
    (["not json"], "not JSON"),
    (['{"type": "export", "format": "nymbus-jsonl", "version": 2, "contributor": "mike", "timezone": "UTC"}'],
     "unsupported version"),
])
def test_import_rejects_bad_files(db, bad, match):
    with pytest.raises(Exception, match=match):
        import_lines(bad)


def test_commands_round_trip(mike, tmp_path):
    seed(mike)
    before = snapshot_state()
    out = tmp_path / "my-data.jsonl"
    call_command("export_my_data", "--out", str(out), stdout=StringIO(), stderr=StringIO())
    wipe()
    msg = StringIO()
    call_command("import_my_data", str(out), stdout=msg)
    assert "Imported 14 records and 4 corrections for mike; every CID verified." in msg.getvalue()
    assert snapshot_state() == before
    with pytest.raises(CommandError, match="Nothing imported: contributor mike already has records"):
        call_command("import_my_data", str(out), stdout=StringIO())


def test_export_to_stdout_and_unknown_contributor(mike):
    out = StringIO()
    call_command("export_my_data", stdout=out)
    assert json.loads(out.getvalue().splitlines()[0])["type"] == "export"
    with pytest.raises(CommandError, match="Unknown contributor"):
        call_command("export_my_data", "--contributor", "nobody", stdout=StringIO())


# --- web: download button and read-only API ----------------------------------------

@pytest.fixture
def client_in(client, db):
    client.force_login(get_user_model().objects.create_user("owner", password="a-long-test-password"))
    return client


def test_download_button(client_in, mike):
    seed(mike)
    assert b"Download my data" in client_in.get(reverse("ui:recent")).content
    resp = client_in.get(reverse("ui:export"))
    assert resp.status_code == 200 and resp["Content-Type"].startswith("application/x-ndjson")
    assert resp["Content-Disposition"].startswith('attachment; filename="my-data-mike-')
    body = b"".join(resp.streaming_content).decode()
    lines = body.splitlines()
    assert len(lines) == 1 + 14 + 4 and all(json.loads(line) for line in lines)
    assert [json.loads(line) for line in lines[1:]] == [json.loads(line) for line in list(export_lines(mike))[1:]]


def test_download_requires_login_and_get(client_in, db):
    assert Client().get(reverse("ui:export")).status_code == 302
    assert client_in.post(reverse("ui:export")).status_code == 405


def test_recent_page_lists_snapshots(client_in, mike):
    """Regression: a snapshot (a date, not a datetime) on the Recent page."""
    seed(mike)
    page = client_in.get(reverse("ui:recent"))
    assert page.status_code == 200 and b"daily snapshot from 10 Nov" in page.content


@pytest.mark.parametrize("name", ["api_today", "api_trends", "api_recent"])
def test_api_is_read_only_json_behind_login(client_in, mike, name):
    assert Client().get(reverse(f"ui:{name}")).status_code == 403
    assert client_in.post(reverse(f"ui:{name}")).status_code == 405
    resp = client_in.get(reverse(f"ui:{name}"))
    data = resp.json()
    assert resp.status_code == 200 and data["api"] == "v0" and data["contributor"] == "mike"
    assert data["disclaimer"] == "Load gauge, not a medical assessment."


def test_api_payloads(client_in, mike):
    seed(mike)
    today = client_in.get(reverse("ui:api_today")).json()["today"]
    assert {c["kind"] for c in today["checkins"]} == {"snapshot", "probe", "work", "discomfort", "reset"}
    trends = client_in.get(reverse("ui:api_trends") + "?weeks=12").json()["trends"]
    assert trends["weeks"] == 12 and "svg" not in trends["charts"][0]
    assert trends["charts"][0]["title"] == "Sleep score" and isinstance(trends["charts"][0]["points"], list)
    recent = client_in.get(reverse("ui:api_recent")).json()["recent"]
    assert [g["kind"] for g in recent] == ["snapshot", "probe", "work", "discomfort", "reset"]
