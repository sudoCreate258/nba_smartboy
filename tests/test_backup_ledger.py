"""M5-T7: the backup counts, verifies and restores the ledger; sets from before M5 still verify."""
import datetime
import json
from io import StringIO

import pytest
from django.core.management import call_command
from django.db import connection

from backup import runner
from core.models import Contributor
from core.services.export import EXPORT_MODELS
from ledger.models import AccessEvent
from ledger.verify import verify
from tests.test_export import seed
from tests.test_ledger_export import seed_ledger

pytestmark = pytest.mark.django_db(transaction=True)
NOW = datetime.datetime(2026, 11, 12, 7, 30, tzinfo=datetime.timezone.utc)


@pytest.fixture(scope="module", autouse=True)
def restore_migration_data(django_db_blocker):
    yield
    with django_db_blocker.unblock():
        Contributor.objects.get_or_create(handle="mike", defaults={"timezone": "America/New_York"})


@pytest.fixture
def mike():
    m, _ = Contributor.objects.get_or_create(handle="mike", defaults={"timezone": "America/New_York"})
    seed(m)
    seed_ledger(m)
    return m


def state():
    return {m.record_kind: sorted(m.objects.values_list("cid", flat=True)) for m in EXPORT_MODELS}


def test_set_counts_and_verifies_the_ledger(mike, tmp_path):
    folder = tmp_path / "set"
    manifest = runner.build_set(folder, now=NOW, include_inbox=False)
    assert {k: manifest["record_counts"][k] for k in ("grant", "revocation", "access_event")} == {
        "grant": 2, "revocation": 1, "access_event": 3}
    assert runner.verify_restore(folder, manifest, scratch="twin_verify_ledger") == 14 + 6


def test_sets_from_before_the_ledger_still_verify(mike, tmp_path):
    folder = tmp_path / "set"
    manifest = runner.build_set(folder, now=NOW, include_inbox=False)
    for kind in ("grant", "revocation", "access_event"):
        manifest["record_counts"].pop(kind)
    assert runner.verify_restore(folder, manifest, scratch="twin_verify_preledger") == 14


def test_a_missing_access_event_in_the_export_is_detected(mike, tmp_path):
    folder = tmp_path / "set"
    manifest = runner.build_set(folder, now=NOW, include_inbox=False)
    export = folder / "my-data-mike.jsonl"
    lines = export.read_text(encoding="utf-8").splitlines()
    drop = next(i for i, line in enumerate(lines) if json.loads(line).get("kind") == "access_event")
    lines.pop(drop)
    export.write_text("\n".join(lines) + "\n", encoding="utf-8")
    with pytest.raises(runner.BackupError, match="access_event CIDs in the restored dump differ"):
        runner.verify_restore(folder, manifest, scratch="twin_verify_ledger_bad")


def test_restore_brings_the_ledger_back_append_only(mike, tmp_path):
    folder = tmp_path / "set"
    runner.build_set(folder, now=NOW, include_inbox=False)
    before = state()
    with connection.cursor() as cur:
        cur.execute("TRUNCATE ledger_grant, ledger_revocation, ledger_accessevent")
    call_command("restore_backup", str(folder), "--yes", stdout=StringIO())
    assert state() == before
    assert verify(Contributor.objects.get(handle="mike"))[0] == []
    with pytest.raises(Exception, match="append-only"):  # the restored tables keep their triggers
        with connection.cursor() as cur:
            cur.execute("DELETE FROM ledger_accessevent")
    assert AccessEvent.objects.count() == 3
