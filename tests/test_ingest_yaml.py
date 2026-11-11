import datetime
from io import StringIO
from pathlib import Path

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from core.models import DailySnapshot, Supersession

FIXTURE = Path(__file__).parent / "fixtures" / "sample_snapshots.yaml"


def ingest(path):
    out = StringIO()
    call_command("ingest_yaml", str(path), stdout=out)
    return out.getvalue()


def write(tmp_path, text):
    p = tmp_path / "in.yaml"
    p.write_text(text, encoding="utf-8")
    return p


@pytest.mark.django_db
def test_happy_path():
    out = ingest(FIXTURE)
    assert "created=2 skipped=0 superseded=0" in out
    assert DailySnapshot.objects.count() == 2
    for s in DailySnapshot.objects.all():
        assert s.cid in out
        assert s.contributor.handle == "mike"
    s = DailySnapshot.objects.get(date=datetime.date(2026, 11, 11))
    assert s.bedtime == datetime.datetime(2026, 11, 11, 3, 54, tzinfo=datetime.timezone.utc)
    assert str(s.weight_kg) == "97.8"
    assert s.wake_time is None and s.spo2 is None


@pytest.mark.django_db
def test_single_mapping_file(tmp_path):
    out = ingest(write(tmp_path, "date: 2026-11-11\nsource: manual\nhrv: 40\n"))
    assert "created=1" in out


@pytest.mark.django_db
def test_unknown_key_errors_and_rolls_back_whole_file(tmp_path):
    p = write(
        tmp_path,
        "- date: 2026-11-11\n  source: manual\n  hrv: 40\n"
        "- date: 2026-11-12\n  source: manual\n  vo2max: 50\n  steps: 9\n",
    )
    with pytest.raises(CommandError) as exc:
        ingest(p)
    assert "vo2max" in str(exc.value) and "steps" in str(exc.value)
    assert DailySnapshot.objects.count() == 0


@pytest.mark.django_db
def test_validation_error_rolls_back_earlier_records(tmp_path):
    p = write(
        tmp_path,
        "- date: 2026-11-11\n  source: manual\n  hrv: 40\n"
        "- date: 2026-11-12\n  source: samsung_health\n  bia_timing: post_sauna\n  body_fat_pct: 25.0\n",
    )
    with pytest.raises(CommandError, match="Record 2"):
        ingest(p)
    assert DailySnapshot.objects.count() == 0


@pytest.mark.django_db
def test_reingest_is_idempotent():
    ingest(FIXTURE)
    before = set(DailySnapshot.objects.values_list("cid", flat=True))
    out = ingest(FIXTURE)
    assert "created=0 skipped=2 superseded=0" in out
    assert set(DailySnapshot.objects.values_list("cid", flat=True)) == before


@pytest.mark.django_db
def test_changed_value_supersedes(tmp_path):
    ingest(FIXTURE)
    changed = FIXTURE.read_text(encoding="utf-8").replace("hrv: 41", "hrv: 45")
    out = ingest(write(tmp_path, changed))
    assert "created=0 skipped=1 superseded=1" in out
    new = DailySnapshot.objects.current().get(date=datetime.date(2026, 11, 11))
    assert new.hrv == 45
    assert DailySnapshot.objects.get(cid=Supersession.objects.get().old_cid).hrv == 41
    assert new.cid in out
    assert DailySnapshot.objects.count() == 3
    assert DailySnapshot.objects.current().count() == 2


@pytest.mark.django_db
def test_unknown_contributor_option():
    with pytest.raises(CommandError):
        call_command("ingest_yaml", str(FIXTURE), "--contributor", "nobody")


@pytest.mark.django_db
def test_missing_required_key(tmp_path):
    with pytest.raises(CommandError, match="date"):
        ingest(write(tmp_path, "source: manual\n"))


@pytest.mark.django_db
def test_bad_yaml_shape(tmp_path):
    with pytest.raises(CommandError):
        ingest(write(tmp_path, "just a string\n"))


@pytest.mark.django_db
def test_revert_via_ingest_records_supersession_only(tmp_path):
    ingest(FIXTURE)
    changed = write(tmp_path, FIXTURE.read_text(encoding='utf-8').replace('hrv: 41', 'hrv: 45'))
    ingest(changed)
    out = ingest(FIXTURE)
    assert 'created=0 skipped=1 superseded=1' in out
    assert DailySnapshot.objects.count() == 3
    assert Supersession.objects.count() == 2
    assert DailySnapshot.objects.current().get(date=datetime.date(2026, 11, 11)).hrv == 41
    assert 'skipped=2' in ingest(FIXTURE)



@pytest.mark.django_db
def test_offsetless_times_use_contributor_timezone_and_cid_is_stable(tmp_path):
    naive = "date: 2026-11-11\nsource: manual\nbedtime: 2026-11-10 23:15:00\nwake_time: 2026-11-11 07:00:00\n"
    explicit = "date: 2026-11-11\nsource: manual\nbedtime: 2026-11-11T04:15:00+00:00\nwake_time: 2026-11-11T07:00:00-05:00\n"
    ingest(write(tmp_path, naive))
    s = DailySnapshot.objects.get()
    assert s.bedtime == datetime.datetime(2026, 11, 11, 4, 15, tzinfo=datetime.timezone.utc)
    out = ingest(write(tmp_path, explicit))
    assert "skipped=1" in out and DailySnapshot.objects.count() == 1


@pytest.mark.django_db
def test_contributor_timezone_changes_interpretation(tmp_path):
    from core.models import Contributor

    Contributor.objects.filter(handle="mike").update(timezone="UTC")
    ingest(write(tmp_path, "date: 2026-11-11\nsource: manual\nwake_time: 2026-11-11 07:00:00\n"))
    assert DailySnapshot.objects.get().wake_time.hour == 7


@pytest.mark.django_db
def test_bare_time_string_is_rejected_with_rollback(tmp_path):
    p = write(
        tmp_path,
        '- date: 2026-11-11\n  source: manual\n- date: 2026-11-12\n  source: manual\n  bedtime: "22:54"\n',
    )
    with pytest.raises(CommandError, match="Record 2"):
        ingest(p)
    assert DailySnapshot.objects.count() == 0

@pytest.mark.django_db
@pytest.mark.parametrize("bad", ["1e30", ".nan", "1.0e30"])
def test_non_finite_or_huge_number_names_field_and_rolls_back(tmp_path, bad):
    p = write(
        tmp_path,
        f"- date: 2026-11-11\n  source: manual\n  hrv: 40\n- date: 2026-11-12\n  source: manual\n  weight_kg: {bad}\n",
    )
    with pytest.raises(CommandError, match="Record 2: weight_kg"):
        ingest(p)
    assert DailySnapshot.objects.count() == 0


@pytest.mark.django_db
def test_post_sauna_weight_rejected_on_ingest(tmp_path):
    p = write(tmp_path, "date: 2026-11-11\nsource: manual\nbia_timing: post_sauna\nweight_kg: 97.8\n")
    with pytest.raises(CommandError, match="Post-sauna"):
        ingest(p)
    assert DailySnapshot.objects.count() == 0