"""MVP (025 Part A): DEMO seed (R2), provenance page (R3), round-trip proof (R4)."""
from io import StringIO

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.urls import reverse

from core.management.commands.demo_roundtrip import summary
from core.management.commands.seed_demo import seed
from core.models import Contributor, DailySnapshot, ProbeSession, Supersession, TrainingSession, TrainingSet
from core.services.export import EXPORT_MODELS, export_lines
from ledger.models import AccessEvent, Grant, Revocation
from ledger.verify import verify


def counts(who):
    return {m.record_kind: m.objects.filter(contributor=who).count() for m in EXPORT_MODELS} | {
        "supersession": Supersession.objects.filter(contributor=who).count()}


def test_seed_demo_is_synthetic_labelled_complete_and_idempotent(db):
    out = StringIO()
    call_command("seed_demo", stdout=out)
    demo = Contributor.objects.get(handle="demo")
    first = counts(demo)
    assert first["daily_snapshot"] == 15 and first["supersession"] == 1  # 14 days + one correction
    assert first["probe_session"] == 14 and first["training_session"] == 7 and first["training_set"] == 21
    assert (first["grant"], first["access_event"], first["revocation"]) == (1, 2, 1)
    assert DailySnapshot.objects.current().filter(contributor=demo).count() == 14
    assert all("DEMO" in r.notes for m in (DailySnapshot, ProbeSession, TrainingSession, TrainingSet)
               for r in m.objects.filter(contributor=demo))
    assert all(s.weight_kg and s.body_fat_pct for s in DailySnapshot.objects.filter(contributor=demo))
    assert "DEMO" in Grant.objects.get(contributor=demo).purpose
    assert seed() == 0 and counts(demo) == first  # idempotent
    assert verify(demo)[0] == []
    assert not DailySnapshot.objects.filter(contributor__handle="mike").exists()  # the owner's data untouched


@pytest.fixture
def client_in(client, db):
    seed()
    client.force_login(get_user_model().objects.create_user("owner", password="a-long-test-password"))
    return client


def test_provenance_page_shows_cid_chain_reads_and_grant(client_in):
    demo = Contributor.objects.get(handle="demo")
    s = Supersession.objects.get(contributor=demo)
    page = client_in.get(reverse("ui:provenance") + f"?who=demo&cid={s.old_cid}").content.decode()
    assert "DEMO data" in page and s.old_cid in page and "matches its content" in page
    assert f"superseded; current version <code class=\"cid\">{s.new_cid}" in page
    assert "DEMO: mistyped sleep score" in page and "No simulated recipient has read this record." in page
    probe = ProbeSession.objects.filter(contributor=demo).first()
    page = client_in.get(reverse("ui:provenance") + f"?who=demo&cid={probe.cid}").content.decode()
    g = Grant.objects.get(contributor=demo)
    assert "Research partner (simulated)" in page and "DEMO: fatigue study" in page and g.cid in page
    assert "revoked" in page and page.count("simulated credit") == 2 and "Never corrected." in page
    assert client_in.get(reverse("ui:provenance") + "?who=demo&cid=bafkreinope").status_code == 404
    own = client_in.get(reverse("ui:provenance")).content.decode()
    assert "Show the DEMO profile" in own and "No records yet" in own  # mike has none here
    assert client_in.get(reverse("ui:provenance")).status_code == 200


def test_provenance_needs_login_and_is_read_only(client, db):
    assert client.get(reverse("ui:provenance")).status_code == 302
    client.force_login(get_user_model().objects.create_user("owner", password="a-long-test-password"))
    assert client.post(reverse("ui:provenance")).status_code == 405


def test_summary_detects_differences(db):
    seed()
    lines = list(export_lines(Contributor.objects.get(handle="demo")))
    a = summary(lines)
    assert a[2]["events"] == 2 and len(a[0]) == sum(counts(Contributor.objects.get(handle="demo")).values()) - 1
    assert summary([line for line in lines if '"access_event"' not in line or '"seq": 2' not in line])[2] != a[2]


@pytest.fixture(scope="module")
def restore_mike(django_db_blocker):
    yield
    with django_db_blocker.unblock():
        Contributor.objects.get_or_create(handle="mike", defaults={"timezone": "America/New_York"})


@pytest.mark.django_db(transaction=True)
def test_demo_roundtrip_command(restore_mike):
    Contributor.objects.get_or_create(handle="mike", defaults={"timezone": "America/New_York"})
    seed()
    out = StringIO()
    call_command("demo_roundtrip", stdout=out)
    assert "Round trip OK for demo" in out.getvalue() and "ledger head 2 events" in out.getvalue()
    with pytest.raises(CommandError, match="Unknown contributor"):
        call_command("demo_roundtrip", "--contributor", "nobody", stdout=StringIO())
