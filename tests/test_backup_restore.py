"""M4.5-T6: restore_backup (R10): back up, lose the data, restore from the crypt remote, CIDs identical."""
import datetime
from io import StringIO

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection

from backup import runner
from core.models import Contributor, Supersession
from core.services.export import RECORD_MODELS
from tests.backup_helpers import crypt_remote
from tests.test_export import seed

pytestmark = pytest.mark.django_db(transaction=True)
NOW = datetime.datetime(2026, 11, 12, 7, 30, tzinfo=datetime.timezone.utc)


@pytest.fixture(scope="module", autouse=True)
def restore_migration_data(django_db_blocker):
    yield
    with django_db_blocker.unblock():
        Contributor.objects.get_or_create(handle="mike", defaults={"timezone": "America/New_York"})


def state():
    out = {m.record_kind: sorted(m.objects.values_list("cid", flat=True)) for m in RECORD_MODELS}
    out["supersessions"] = sorted(Supersession.objects.values_list("old_cid", "new_cid"))
    return out


def lose_everything():
    with connection.cursor() as cur:
        for model in RECORD_MODELS + [Supersession]:
            cur.execute(f'DELETE FROM "{model._meta.db_table}"')


@pytest.fixture
def backed_up(tmp_path, monkeypatch, settings):
    mike, _ = Contributor.objects.get_or_create(handle="mike", defaults={"timezone": "America/New_York"})
    seed(mike)
    config, name, _ = crypt_remote(tmp_path)
    monkeypatch.setenv("RCLONE_CONFIG", str(config))
    settings.BACKUP_REMOTE = name
    run = runner.run_backup(now=NOW)
    assert run.status == "ok", run.error
    return state()


def test_restore_latest_from_the_remote(backed_up):
    lose_everything()
    assert state() != backed_up
    out = StringIO()
    call_command("restore_backup", "--set", "latest", stdout=out)
    text = out.getvalue()
    assert "Downloaded 2026-11-12T073000Z through the crypt remote." in text
    assert "Restored 14 records; every CID matches the export." in text
    assert state() == backed_up


def test_restore_refuses_to_replace_records_without_yes(backed_up):
    with pytest.raises(CommandError, match="already has 14 records"):
        call_command("restore_backup", "--set", "latest", stdout=StringIO())
    call_command("restore_backup", "--set", "latest", "--yes", stdout=StringIO())
    assert state() == backed_up


def test_restore_from_a_downloaded_folder_detects_tampering(backed_up, tmp_path):
    folder = tmp_path / "downloaded"
    runner.download_set("latest", folder)
    lose_everything()
    with open(folder / "twin.dump", "ab") as fh:
        fh.write(b"x")
    with pytest.raises(CommandError, match="Restore failed: verify: twin.dump does not match"):
        call_command("restore_backup", str(folder), stdout=StringIO())


def test_restore_arguments(db_is_unused=None):
    with pytest.raises(CommandError, match="either a downloaded set folder or --set"):
        call_command("restore_backup", stdout=StringIO())
