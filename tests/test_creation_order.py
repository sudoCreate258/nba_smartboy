"""M6: export replays in the database's creation order, not the wall clock (found as an intermittent
gate failure: the Docker VM clock stepped back between a record and its correction)."""
import datetime

import pytest
from django.db import connection

from core.models import Contributor, DailySnapshot, Supersession
from core.services.export import export_lines, import_lines
from core.services.records import save_record
from tests.test_export import snapshot_state, wipe

T = datetime.datetime(2026, 11, 10, 14, 0, tzinfo=datetime.timezone.utc)


@pytest.fixture
def mike(db):
    return Contributor.objects.get(handle="mike")


def test_every_row_gets_an_increasing_creation_number_across_tables(mike):
    a, _ = save_record(DailySnapshot(contributor=mike, date=T.date(), source="manual", sleep_score=80))
    b, _ = save_record(DailySnapshot(contributor=mike, date=T.date(), source="manual", sleep_score=81), supersedes=a)
    a, b = DailySnapshot.objects.get(pk=a.pk), DailySnapshot.objects.get(pk=b.pk)
    s = Supersession.objects.get()
    assert a.created_seq < b.created_seq < s.created_seq


def test_a_clock_that_stepped_back_does_not_reorder_the_export(mike):
    save_record(DailySnapshot(contributor=mike, date=T.date(), source="manual", sleep_score=80))
    old = DailySnapshot.objects.get()
    save_record(DailySnapshot(contributor=mike, date=T.date(), source="manual", sleep_score=81), supersedes=old)
    with connection.cursor() as cur:  # the correction's clock reads an hour earlier than the record's
        cur.execute("SET CONSTRAINTS ALL IMMEDIATE")
        cur.execute("ALTER TABLE core_supersession DISABLE TRIGGER core_supersession_append_only")
        cur.execute("UPDATE core_supersession SET created_at = created_at - interval '1 hour'")
        cur.execute("ALTER TABLE core_supersession ENABLE TRIGGER core_supersession_append_only")
    before = snapshot_state()
    lines = list(export_lines(mike))
    wipe()
    import_lines(lines)
    assert snapshot_state() == before
