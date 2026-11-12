"""M6-T1: the database refuses UPDATE and DELETE on every record table, Supersession and the ledger (R1)."""
import pytest
from django.db import DatabaseError, connection, transaction

from core.models import Contributor, Supersession
from core.services.export import EXPORT_MODELS
from tests.test_export import seed
from tests.test_ledger_export import seed_ledger

TABLES = [m._meta.db_table for m in EXPORT_MODELS] + [Supersession._meta.db_table]


@pytest.fixture
def mike(db):
    m = Contributor.objects.get(handle="mike")
    seed(m)
    seed_ledger(m)
    return m


def test_every_protected_table_has_rows_in_the_fixture(mike):
    with connection.cursor() as cur:
        for table in TABLES:
            cur.execute(f'SELECT count(*) FROM "{table}"')
            assert cur.fetchone()[0] > 0, table


@pytest.mark.parametrize("table", TABLES)
def test_raw_sql_update_and_delete_fail(mike, table):
    for sql in (f'UPDATE "{table}" SET created_at = created_at', f'DELETE FROM "{table}"'):
        with pytest.raises(DatabaseError, match="append-only"):
            with transaction.atomic(), connection.cursor() as cur:
                cur.execute(sql)
    with connection.cursor() as cur:
        cur.execute(f'SELECT count(*) FROM "{table}"')
        assert cur.fetchone()[0] > 0


def test_every_record_table_has_the_trigger(db):
    """A record kind added later without a trigger fails here."""
    with connection.cursor() as cur:
        cur.execute("SELECT event_object_table FROM information_schema.triggers "
                    "WHERE trigger_name LIKE %s AND event_manipulation IN ('UPDATE', 'DELETE')", ["%_append_only"])
        protected = {row[0] for row in cur.fetchall()}
    assert set(TABLES) <= protected


def test_inserts_and_contributor_settings_still_work(mike):
    mike.timezone = "Europe/Paris"  # the contributor row is configuration, not a record
    mike.save()
    assert Contributor.objects.get(pk=mike.pk).timezone == "Europe/Paris"
