"""M5-T6: Permissions page: categories with record counts, grant, revoke with confirmation (R1, R7)."""
import datetime
import re

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from core.models import Contributor
from ledger import service
from ledger.models import AccessEvent, Grant, Revocation
from ledger.service import AccessRefused
from tests.test_export import seed
from tests.test_ui_no_external import URL, _is_local, _references
from ui.models import ModuleSetting

UTC = datetime.timezone.utc


@pytest.fixture
def mike(db):
    m = Contributor.objects.get(handle="mike")
    seed(m)
    return m


@pytest.fixture
def client_in(client, mike):
    client.force_login(get_user_model().objects.create_user("owner", password="a-long-test-password"))
    return client


def page(client):
    return client.get(reverse("ui:permissions")).content.decode()


def test_categories_grouped_by_owner_with_record_counts(client_in):
    html = page(client_in)
    owners = re.findall(r'<h2 id="owner-([a-z]+)">', html)
    assert owners == ["core", "probes", "zone", "training"]
    for text in ("Daily metrics (sleep, heart rate, body composition)", "1 current record (daily_snapshot)",
                 "2 current records (probe_session)", "2 current records (work_block, reset)",
                 "3 current records (training_session, training_set)", "No one may read this category."):
        assert text in html, text


def test_grant_from_the_page(client_in, mike):
    resp = client_in.post(reverse("ui:permissions"), {"category": "probes", "probes-recipient": "sim-research-partner",
                                                       "probes-purpose": "fatigue study", "probes-end": ""},
                          follow=True)
    html = resp.content.decode()
    assert "Research partner (simulated) may now read Cognitive probes." in html
    g = Grant.objects.get()
    assert (g.category, g.recipient, g.purpose, g.end) == ("probes", "sim-research-partner", "fatigue study", None)
    assert f'href="/permissions/revoke/{g.cid}/"' in html and "fatigue study" in html
    service.simulated_read(mike, "sim-research-partner", "probes")  # the grant works


def test_grant_with_a_local_end_time(client_in, mike):
    end = (datetime.datetime.now(mike.tzinfo) + datetime.timedelta(days=30)).replace(second=0, microsecond=0)
    client_in.post(reverse("ui:permissions"), {"category": "training", "training-recipient": "self-analysis",
                                               "training-purpose": "volume", "training-end": end.strftime("%Y-%m-%dT%H:%M")})
    assert Grant.objects.get().end == end


@pytest.mark.parametrize("data,error", [
    ({"probes-recipient": "self-analysis", "probes-purpose": ""}, "This field is required."),
    ({"probes-recipient": "a-real-company", "probes-purpose": "x"}, "Select a valid choice."),
    ({"probes-recipient": "self-analysis", "probes-purpose": "x", "probes-end": "2020-01-01T09:00"},
     "The end must be in the future."),
])
def test_invalid_grants_show_errors_and_write_nothing(client_in, data, error):
    resp = client_in.post(reverse("ui:permissions"), {"category": "probes", **data})
    assert resp.status_code == 400 and error in resp.content.decode()
    assert not Grant.objects.exists()


def test_unknown_category_is_404(client_in):
    assert client_in.post(reverse("ui:permissions"), {"category": "genome"}).status_code == 404


def test_revoke_needs_confirmation(client_in, mike):
    g = service.grant(mike, "probes", "self-analysis", "weekly review")
    service.simulated_read(mike, "self-analysis", "probes")
    confirm = client_in.get(reverse("ui:revoke", args=[g.cid]))
    html = confirm.content.decode()
    assert confirm.status_code == 200 and "Revoke this grant?" in html and "Revoke now" in html
    assert not Revocation.objects.exists()  # GET changes nothing
    resp = client_in.post(reverse("ui:revoke", args=[g.cid]), {"reason": "study over"}, follow=True)
    html = resp.content.decode()
    assert "Revoked: Self-analysis (simulated) can no longer read Cognitive probes." in html
    assert Revocation.objects.get().reason == "study over"
    assert "Past grants (1)" in html and "(revoked)" in html
    with pytest.raises(AccessRefused):
        service.simulated_read(mike, "self-analysis", "probes")
    assert AccessEvent.objects.count() == 1
    again = client_in.post(reverse("ui:revoke", args=[g.cid]), follow=True)
    assert "already revoked" in again.content.decode()
    later = client_in.get(reverse("ui:revoke", args=[g.cid]), follow=True)
    assert "no longer active; there is nothing to revoke" in later.content.decode()
    assert client_in.get(reverse("ui:revoke", args=["bafkreinope"])).status_code == 404


def test_another_contributors_grant_is_404(client_in):
    other = Contributor.objects.create(handle="someone")
    g = service.grant(other, "probes", "self-analysis", "x")
    assert client_in.get(reverse("ui:revoke", args=[g.cid])).status_code == 404


def test_module_off_is_shown_and_pages_need_login(client, client_in):
    ModuleSetting.objects.create(module_id="zone", enabled=False)
    assert 'Work and zone <span class="flag flag-amber">module off</span>' in page(client_in)
    client.logout()
    assert client.get(reverse("ui:permissions")).status_code == 302
    assert client.get(reverse("ui:revoke", args=["x"])).status_code == 302


def test_revoke_page_is_local(client_in, mike):
    g = service.grant(mike, "probes", "self-analysis", "x")
    html = client_in.get(reverse("ui:revoke", args=[g.cid])).content.decode()
    assert not URL.search(html) and all(_is_local(r) for r in _references(html))
    assert len(html) < 200_000


def test_service_worker_never_caches_ledger_pages(client, db):
    body = client.get("/sw.js").content.decode()
    assert '"/permissions/"' in body and '"/statement/"' in body
