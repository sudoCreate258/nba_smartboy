"""M4-T4: manifest, service worker, offline page and the offline-queue replay contract (R3).

The JavaScript itself runs in the browser; these tests pin the server side it relies on
and the static rules (no external hosts, same-origin only, no build step).
"""
import json
import re
from pathlib import Path

import pytest
from django.contrib.auth import get_user_model
from django.contrib.staticfiles import finders
from django.urls import reverse

from core.models import Contributor, DiscomfortCheck

ROOT = Path(__file__).resolve().parent.parent
FORM = {"at": "2026-11-11T10:25", "area": "neck", "score": "3", "trigger": "end_of_block",
        "countermove": "none", "notes": ""}


@pytest.fixture
def mike(db):
    return Contributor.objects.get(handle="mike")


@pytest.fixture
def client_in(client, db):
    client.force_login(get_user_model().objects.create_user("owner", password="a-long-test-password"))
    return client


def replay(client, data, mode="queue"):
    return client.post(reverse("ui:checkin", args=["discomfort"]), data, HTTP_X_OFFLINE_REPLAY=mode)


def test_manifest_is_installable(client, db):
    resp = client.get("/manifest.webmanifest")
    assert resp.status_code == 200 and resp["Content-Type"] == "application/manifest+json"
    data = json.loads(resp.content)
    assert data["display"] == "standalone" and data["start_url"] == "/" and data["scope"] == "/"
    sizes = {i["sizes"] for i in data["icons"]}
    assert {"192x192", "512x512"} <= sizes
    for icon in data["icons"]:
        path = finders.find(icon["src"].removeprefix("/static/"))
        assert path and Path(path).read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"


def test_service_worker_is_served_from_the_root(client, db):
    resp = client.get("/sw.js")
    body = resp.content.decode()
    assert resp.status_code == 200 and resp["Content-Type"].startswith("application/javascript")
    assert resp["Service-Worker-Allowed"] == "/" and resp["Cache-Control"] == "no-cache"
    assert "/static/ui/app.css" in body and "/offline/" in body and 'var CACHE = "twin-' in body
    assert "url.origin !== self.location.origin" in body  # same-origin only
    assert '"/admin/"' in body  # the admin is never cached


def test_offline_page_is_public_and_has_no_personal_data(client, db):
    resp = client.get("/offline/")
    assert resp.status_code == 200 and b"No connection to your instance" in resp.content


def test_pages_link_the_manifest_and_the_script(client_in, mike):
    html = client_in.get(reverse("ui:home")).content.decode()
    assert 'rel="manifest" href="/manifest.webmanifest"' in html and "/static/ui/offline.js" in html
    form = client_in.get(reverse("ui:checkin", args=["discomfort"])).content.decode()
    assert 'data-offline="Discomfort check"' in form and 'action="/checkin/discomfort/"' in form


def test_replay_saves_and_answers_json(client_in, mike):
    resp = replay(client_in, FORM)
    data = resp.json()
    assert resp.status_code == 200 and data["outcome"] == "created" and data["redirect"] == "/"
    assert data["cid"] == DiscomfortCheck.objects.get().cid


def test_offline_duplicate_is_already_saved(client_in, mike):
    """The same queued check-in sent twice (e.g. the first reply was lost) is stored once."""
    first = replay(client_in, FORM).json()
    second = replay(client_in, FORM).json()
    assert second["outcome"] == "skipped" and second["cid"] == first["cid"]
    assert "already saved" in second["message"]
    assert DiscomfortCheck.objects.count() == 1


def test_replay_with_errors_is_400_json(client_in, mike):
    resp = replay(client_in, {**FORM, "score": "12"})
    assert resp.status_code == 400 and resp.json()["outcome"] == "invalid"
    assert "score" in resp.json()["errors"] and DiscomfortCheck.objects.count() == 0


def test_replay_when_logged_out_is_403_json_not_a_redirect(client, db):
    resp = replay(client, FORM)
    assert resp.status_code == 403 and resp.json()["outcome"] == "login"


def test_queue_replay_sets_no_flash_message_but_live_does(client_in, mike):
    replay(client_in, FORM, mode="queue")
    assert "saved." not in client_in.get(reverse("ui:home")).content.decode()
    replay(client_in, {**FORM, "score": "4"}, mode="live")
    assert "Discomfort check saved." in client_in.get(reverse("ui:home")).content.decode()


def test_offline_assets_stay_on_this_host_and_need_no_build():
    js = (ROOT / "ui" / "static" / "ui" / "offline.js").read_text(encoding="utf-8")
    sw = (ROOT / "ui" / "templates" / "ui" / "sw.js").read_text(encoding="utf-8")
    for text in (js, sw):
        assert not re.search(r"https?://", text)
        assert "import " not in text and "require(" not in text  # plain scripts, no bundler
    assert 'credentials: "same-origin"' in js and "indexedDB" in js
