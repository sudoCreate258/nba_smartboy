"""Fixes from the PR #12 (M5) semantic review that need their own setup."""
import threading
import time

import pytest
from django.contrib.auth import get_user_model
from django.db import connection, transaction
from django.test import Client
from django.urls import reverse

from core.models import Contributor
from ledger import service, statement
from ledger.models import AccessEvent, Grant
from ledger.service import AccessRefused


@pytest.fixture(scope="module", autouse=True)
def restore_migration_data(django_db_blocker):
    """The transactional test flushes the database; put the data migration's contributor back."""
    yield
    with django_db_blocker.unblock():
        Contributor.objects.get_or_create(handle="mike", defaults={"timezone": "America/New_York"})


@pytest.mark.django_db(transaction=True)
def test_a_read_waiting_on_a_concurrent_revoke_is_refused():
    """Two real transactions: the revoke holds the contributor lock; the read started meanwhile waits,
    then sees the committed revocation (its clock is read only once it holds the lock)."""
    mike, _ = Contributor.objects.get_or_create(handle="mike", defaults={"timezone": "America/New_York"})
    g = service.grant(mike, "probes", "self-analysis", "review")
    asked, result = threading.Event(), {}

    def reader():
        try:
            asked.wait(5)
            service.simulated_read(Contributor.objects.get(pk=mike.pk), "self-analysis", "probes")
            result["outcome"] = "read"
        except AccessRefused:
            result["outcome"] = "refused"
        finally:
            connection.close()

    thread = threading.Thread(target=reader)
    thread.start()
    with transaction.atomic():
        Contributor.objects.select_for_update().get(pk=mike.pk)
        asked.set()
        time.sleep(1.0)  # the reader is now blocked on the lock
        assert "outcome" not in result
        service.revoke(mike, g.cid)
    thread.join(15)
    assert result == {"outcome": "refused"}
    assert AccessEvent.objects.count() == 0


def test_a_clock_that_steps_back_cannot_date_a_read_before_a_revocation(db, monkeypatch):
    """M6: the gate saw the VM clock step back; ledger times never go backwards per contributor."""
    import datetime
    from django.utils import timezone as tz
    mike = Contributor.objects.get(handle="mike")
    g = service.grant(mike, "probes", "self-analysis", "review")
    service.revoke(mike, g.cid)
    earlier = tz.now() - datetime.timedelta(minutes=5)
    monkeypatch.setattr(service.timezone, "now", lambda: earlier)
    with pytest.raises(AccessRefused):
        service.simulated_read(mike, "self-analysis", "probes")
    later = service.grant(mike, "probes", "self-analysis", "again")
    assert later.start >= g.revocation().at  # dated at the ledger's latest time, not the stepped-back clock


@pytest.fixture
def strict(db):
    client = Client(enforce_csrf_checks=True)
    client.force_login(get_user_model().objects.create_user("owner", password="a-long-test-password"))
    return client


def test_permission_changes_need_the_csrf_token(strict):
    mike = Contributor.objects.get(handle="mike")
    data = {"category": "probes", "probes-recipient": "self-analysis", "probes-purpose": "x"}
    assert strict.post(reverse("ui:permissions"), data).status_code == 403
    assert not Grant.objects.exists()
    g = service.grant(mike, "probes", "self-analysis", "x")
    assert strict.post(reverse("ui:revoke", args=[g.cid])).status_code == 403
    assert g.revocation() is None


def test_an_invalid_month_is_named_on_the_page(client, db):
    client.force_login(get_user_model().objects.create_user("owner", password="a-long-test-password"))
    html = client.get(reverse("ui:statement") + "?month=2026-13").content.decode()
    assert '"2026-13" is not a month (YYYY-MM); showing' in html
    assert statement.build(Contributor.objects.get(handle="mike"), "2026-13")["ignored_month"] == "2026-13"
