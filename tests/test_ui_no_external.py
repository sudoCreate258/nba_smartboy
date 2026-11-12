"""M4-T7: zero external requests and page-size budget (R3, R6).

1. Source scan: no http(s) URL in any template, stylesheet or script of the app.
2. Rendered scan: every page and asset the app serves, with data in the database, references
   only this host (no src/href/action/url()/@import/fetch/register to another origin).
3. Size: each page plus the CSS and JS it loads stays under 200 KB.
"""
import re
from pathlib import Path

import pytest
from django.contrib.auth import get_user_model
from django.contrib.staticfiles import finders
from django.urls import reverse

from core.models import Contributor
from tests.test_export import seed

ROOT = Path(__file__).resolve().parent.parent
APP_FILES = [p for p in (ROOT / "ui").rglob("*") if p.suffix in {".html", ".css", ".js", ".webmanifest"}]
URL = re.compile(r"(?i)\b(?:https?:)?//[a-z0-9.-]+")
REF = re.compile(r"""(?ix)
    (?:\b(?:src|href|action|poster|srcset)\s*=\s*["']([^"']*)["'])   # HTML attributes
  | (?:url\(\s*["']?([^"')]*)["']?\s*\))                              # CSS url()
  | (?:@import\s+["']([^"']*)["'])                                    # CSS @import
  | (?:\b(?:fetch|register|importScripts)\(\s*["']([^"']*)["'])       # JS requests
""")
BUDGET = 200_000


def test_app_sources_contain_no_urls():
    assert len(APP_FILES) >= 10
    for path in APP_FILES:
        text = path.read_text(encoding="utf-8")
        assert not URL.search(text), f"{path.relative_to(ROOT)}: {URL.search(text).group(0)}"


@pytest.fixture
def client_in(client, db):
    seed(Contributor.objects.get(handle="mike"))
    client.force_login(get_user_model().objects.create_user("owner", password="a-long-test-password"))
    return client


PAGES = [("ui:home", ""), ("ui:checkin_index", ""), ("ui:trends", ""), ("ui:trends", "?weeks=12"), ("ui:recent", ""),
         ("ui:offline", ""), ("ui:modules", ""), ("ui:permissions", ""), ("ui:statement", "")] + [("ui:checkin", kind) for kind in ("snapshot", "probe", "work", "discomfort", "reset")]


def _url(name, extra):
    if name == "ui:checkin":
        return reverse(name, args=[extra])
    return reverse(name) + extra


def _references(text):
    return [next(g for g in m.groups() if g is not None) for m in REF.finditer(text)]


def _is_local(ref):
    return not re.match(r"(?i)^(?:[a-z][a-z0-9+.-]*:)?//", ref) and not re.match(r"(?i)^(?:https?|ftp|ws|wss):", ref)


def _asset_bytes(client, path):
    resp = client.get(path)
    assert resp.status_code == 200, path
    return b"".join(resp.streaming_content) if resp.streaming else resp.content


@pytest.mark.parametrize("name,extra", PAGES)
def test_rendered_pages_reference_only_this_host_and_fit_the_budget(client_in, name, extra):
    resp = client_in.get(_url(name, extra))
    assert resp.status_code == 200
    html = resp.content.decode()
    assert not URL.search(html), URL.search(html).group(0)
    refs = _references(html)
    assert refs and all(_is_local(r) for r in refs), [r for r in refs if not _is_local(r)]
    assets = {r for r in refs if r.startswith("/static/") and (r.endswith(".css") or r.endswith(".js"))}
    assert assets == {"/static/ui/app.css", "/static/ui/offline.js"}
    total = len(resp.content) + sum(len(_asset_bytes(client_in, a)) for a in assets)
    assert total < BUDGET, f"{_url(name, extra)}: {total} bytes"


def test_login_page_is_local_and_small(client, db):
    resp = client.get(reverse("ui:login"))
    html = resp.content.decode()
    assert not URL.search(html) and all(_is_local(r) for r in _references(html))
    assert len(resp.content) < BUDGET


@pytest.mark.parametrize("path", ["/sw.js", "/manifest.webmanifest", "/static/ui/app.css", "/static/ui/offline.js"])
def test_served_assets_reference_only_this_host(client, db, path):
    text = _asset_bytes(client, path).decode()
    assert not URL.search(text), URL.search(text).group(0)
    assert all(_is_local(r) for r in _references(text))


def test_icons_are_vendored():
    for name in ("ui/icon-192.png", "ui/icon-512.png"):
        assert finders.find(name)


def test_the_checker_catches_external_references():
    """Guard against a scan that silently passes everything."""
    samples = ['<script src="https://cdn.example.com/x.js"></script>', '<link href="//fonts.example.com/a.css">',
               "body { background: url('https://example.com/a.png') }", "@import 'http://example.com/b.css';",
               "fetch('https://api.example.com/v1')"]
    for s in samples:
        assert URL.search(s) or not all(_is_local(r) for r in _references(s)), s
    assert all(_is_local(r) for r in _references('<a href="/trends/?weeks=12">'))
