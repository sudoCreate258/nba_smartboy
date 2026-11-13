"""027 Part A: dtom records and the capture importer. Synthetic fixtures only (tests/fixtures/*.SYNTHETIC.json)."""
import copy
import json
from io import StringIO
from pathlib import Path

import pytest
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.core.management.base import CommandError
from django.utils.dateparse import parse_datetime

from core.models import Contributor, PostureSample, TwinCapture, TwinMinute
from core.services.export import export_lines
from core.services.records import save_record
from ledger.models import Grant
from twin_metrics.dtom import DtomError, check_capture, check_minute

FIX = Path(__file__).resolve().parent / "fixtures"
CAPTURE = FIX / "twin_capture.SYNTHETIC.json"
MINUTE = FIX / "twin_minute.SYNTHETIC.json"


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture
def mike(db):
    return Contributor.objects.get(handle="mike")


def run(*args):
    out = StringIO()
    call_command("import_twin_capture", *args, stdout=out)
    return out.getvalue()


# --- schema validation -----------------------------------------------------------------------

def test_fixtures_are_valid():
    check_capture(load(CAPTURE))
    check_minute(load(MINUTE))


@pytest.mark.parametrize("path,value,match", [
    (["schema"], "nymbus.twin_capture.v2", "schema"),
    (["exported_at"], "2026-11-13T15:30:00", "time zone"),
    (["exported_at"], "yesterday", "ISO 8601"),
    (["posture_samples_v0"], {"not": "a list"}, "posture_samples_v0"),
    (["posture_samples_v0", 0, "frames"], "30", r"posture_samples_v0\[0\].frames"),
    (["posture_samples_v0", 0, "load_pct", "neck"], True, "load_pct.neck: must be a number"),
    (["posture_samples_v0", 1, "side_view"], "no", "side_view"),
    (["posture_seconds", "sitting"], -1, "between"),
])
def test_capture_validation_is_strict(path, value, match):
    doc = load(CAPTURE)
    target = doc
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    with pytest.raises(DtomError, match=match):
        check_capture(doc)


@pytest.mark.parametrize("path,value,match", [
    (["schema"], "nymbus.twin_capture.v1", "schema"),
    (["t_end"], "2026-11-13T15:05:00Z", "after t_start"),
    (["load_pct_avg"], {"neck": 1, "back": 1, "shL": 1}, "load_pct_avg.shR: missing"),
    (["face", "looking_pct", "screen"], 120, "between"),
    (["events", 0, "type"], "nap", "events\\[0\\].type"),
    (["events", 0, "region"], "knee", "region"),
    (["side_view_pct"], "50", "side_view_pct"),
])
def test_minute_validation_is_strict(path, value, match):
    doc = load(MINUTE)
    target = doc
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    with pytest.raises(DtomError, match=match):
        check_minute(doc)


# --- importer --------------------------------------------------------------------------------

def test_import_splits_capture_and_is_idempotent(mike):
    out = run("--file", str(CAPTURE))
    assert "(2 posture samples) for mike: 3 new records, 0 already stored." in out
    capture = TwinCapture.objects.get()
    assert capture.source == "dtom" and capture.sample_count == 2 and "posture_samples_v0" not in capture.raw
    assert capture.raw["extra_top_level"] == "unknown fields are kept"
    samples = list(PostureSample.objects.order_by("index"))
    assert [s.label for s in samples] == ["sitting", "standing"] and all(s.capture_cid == capture.cid for s in samples)
    assert samples[1].data["future_field"] == {"kept": "as given"}
    assert samples[0].at == parse_datetime("2026-11-13T15:05:00+00:00")
    again = run("--file", str(CAPTURE))
    assert "0 new records, 3 already stored." in again
    assert (TwinCapture.objects.count(), PostureSample.objects.count()) == (1, 2)
    assert not Grant.objects.exists()  # owner-only: the import creates no grants


def test_nulls_stay_null_never_zero(mike):
    run("--file", str(CAPTURE))
    standing = PostureSample.objects.get(index=1)
    assert standing.data["load_pct"]["neck"] is None and standing.data["head_pitch"] is None
    assert standing.data["measures"] is None and standing.data["look"] is None
    assert TwinCapture.objects.get().raw["body_model"]["bone_lengths_m"]["neck"] is None
    line = next(json.loads(x) for x in export_lines(mike) if '"posture_sample"' in x and '"standing"' in x)
    assert line["fields"]["data"]["load_pct"]["neck"] is None


def test_bad_file_imports_nothing(mike, tmp_path):
    doc = load(CAPTURE)
    doc["posture_samples_v0"][1]["at"] = "2026-11-13 15:20"  # no time zone
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps(doc), encoding="utf-8")
    with pytest.raises(CommandError, match="Nothing imported: posture_samples_v0\\[1\\].at"):
        run("--file", str(bad))
    (tmp_path / "x.json").write_text("{not json", encoding="utf-8")
    with pytest.raises(CommandError, match="is not JSON"):
        run("--file", str(tmp_path / "x.json"))
    with pytest.raises(CommandError, match="Cannot read"):
        run("--file", str(tmp_path / "missing.json"))
    assert not TwinCapture.objects.exists() and not PostureSample.objects.exists()


# --- CID stability ---------------------------------------------------------------------------

def test_cids_are_stable_and_content_addressed(mike):
    run("--file", str(CAPTURE))
    first = sorted(TwinCapture.objects.values_list("cid", flat=True)) + sorted(
        PostureSample.objects.values_list("cid", flat=True))
    reordered = load(CAPTURE)
    reordered = {k: reordered[k] for k in reversed(list(reordered))}  # key order does not matter
    stored = TwinCapture.objects.get()
    rebuilt = TwinCapture(contributor=mike, source="dtom", exported_at=stored.exported_at, sample_count=2,
                          raw={k: v for k, v in reordered.items() if k != "posture_samples_v0"})
    assert rebuilt.compute_cid() == stored.cid
    changed = copy.deepcopy(rebuilt.raw)
    changed["posture_seconds"]["sitting"] = 1501
    rebuilt.raw = changed
    assert rebuilt.compute_cid() != stored.cid
    assert all(r.compute_cid() == r.cid for r in list(TwinCapture.objects.all()) + list(PostureSample.objects.all()))
    assert len(set(first)) == 3


def test_twin_minute_record(mike):
    doc = load(MINUTE)
    m = TwinMinute(contributor=mike, source="dtom", t_start=parse_datetime("2026-11-13T15:05:00+00:00"),
                   t_end=parse_datetime("2026-11-13T15:06:00+00:00"), data=doc)
    stored, _ = save_record(m)
    assert stored.data["side_view_pct"] is None and stored.data["load_pct_avg"]["back"] is None
    _, outcome = save_record(TwinMinute(contributor=mike, source="dtom", t_start=m.t_start, t_end=m.t_end, data=doc))
    assert outcome == "skipped"
    bad = TwinMinute(contributor=mike, source="other", t_start=m.t_start, t_end=m.t_end, data=doc)
    with pytest.raises(ValidationError, match="must equal the document"):
        bad.save()


def test_sample_must_point_at_a_capture_of_the_same_contributor(mike):
    s = load(CAPTURE)["posture_samples_v0"][0]
    with pytest.raises(ValidationError, match="twin capture of the same contributor"):
        PostureSample(contributor=mike, capture_cid="bafkreinope", index=0, label=s["label"],
                      at=parse_datetime("2026-11-13T15:05:00+00:00"), data=s).save()
