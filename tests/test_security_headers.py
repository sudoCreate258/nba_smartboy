"""M6-T4: security headers, `check --deploy` in HTTPS mode, CSRF and session cookies (R4).

ZAP is not used (only published as a namespaced image); these checks stand in for it.
"""
import os
import subprocess
import sys
from pathlib import Path

import pytest
from django.contrib.auth import get_user_model
from django.test import Client, override_settings
from django.urls import reverse

from tests.test_ui_no_external import PAGES, _url

ROOT = Path(__file__).resolve().parent.parent
LONG_KEY = "k" * 20 + "-not-a-real-key-" + "x" * 40


@pytest.fixture
def client_in(client, db):
    client.force_login(get_user_model().objects.create_user("owner", password="a-long-test-password"))
    return client


@pytest.mark.parametrize("name,extra", PAGES + [("ui:permissions", ""), ("ui:statement", ""), ("ui:login", "")])
def test_every_page_sends_the_security_headers(client_in, name, extra):
    resp = client_in.get(_url(name, extra))
    assert resp.status_code in (200, 302)
    csp = resp["Content-Security-Policy"]
    for directive in ("default-src 'self'", "script-src 'self'", "style-src 'self';", "frame-ancestors 'none'",
                      "object-src 'none'", "base-uri 'self'", "form-action 'self'"):
        assert directive in csp, (name, directive)
    assert "unsafe" not in csp
    assert resp["X-Content-Type-Options"] == "nosniff"
    assert resp["Referrer-Policy"] == "same-origin"
    assert resp["X-Frame-Options"] == "DENY"
    assert "camera=()" in resp["Permissions-Policy"]
    assert "Strict-Transport-Security" not in resp  # plain HTTP: no HSTS


def test_assets_and_service_worker_get_headers_too(client, db):
    for path in ("/sw.js", "/manifest.webmanifest", "/static/ui/app.css"):
        resp = client.get(path)
        assert "frame-ancestors 'none'" in resp["Content-Security-Policy"], path


def test_admin_allows_inline_styles_but_not_scripts(client, db):
    csp = client.get("/admin/login/")["Content-Security-Policy"]
    assert "style-src 'self' 'unsafe-inline'" in csp and "script-src 'self';" in csp


@override_settings(SECURE_HSTS_SECONDS=31536000, SECURE_HSTS_INCLUDE_SUBDOMAINS=True, SESSION_COOKIE_SECURE=True,
                   CSRF_COOKIE_SECURE=True, SECURE_SSL_REDIRECT=True, ALLOWED_HOSTS=["192.168.1.20", "testserver"])
def test_https_mode_sends_hsts_and_secure_cookies(db):
    user = get_user_model().objects.create_user("owner", password="a-long-test-password")
    c = Client()
    plain = c.get(reverse("ui:login"))
    assert plain.status_code == 301 and plain["Location"].startswith("https://")
    page = c.get(reverse("ui:login"), secure=True)
    assert page["Strict-Transport-Security"] == "max-age=31536000; includeSubDomains"
    resp = c.post(reverse("ui:login"), {"username": "owner", "password": "a-long-test-password",
                                        "csrfmiddlewaretoken": page.cookies["csrftoken"].value if "csrftoken" in page.cookies else ""},
                  secure=True)
    assert resp.status_code == 302 and user.pk  # logged in
    session = resp.cookies["sessionid"]
    assert session["secure"] and session["httponly"] and session["samesite"] == "Lax"
    assert page.cookies["csrftoken"]["secure"]


def test_csrf_is_enforced_on_every_state_changing_form(db):
    strict = Client(enforce_csrf_checks=True)
    strict.force_login(get_user_model().objects.create_user("owner", password="a-long-test-password"))
    posts = [(reverse("ui:checkin", args=["discomfort"]), {}), (reverse("ui:modules"), {"module_id": "zone"}),
             (reverse("ui:permissions"), {"category": "probes"}), (reverse("ui:logout"), {})]
    for url, data in posts:
        assert strict.post(url, data).status_code == 403, url
    page = strict.get(reverse("ui:modules"))
    token = page.cookies["csrftoken"].value
    ok = strict.post(reverse("ui:modules"), {"module_id": "zone", "enabled": "1", "csrfmiddlewaretoken": token})
    assert ok.status_code == 302


def test_login_page_csrf_cookie_is_httponly_and_lax(client, db):
    resp = client.get(reverse("ui:login"))
    cookie = resp.cookies["csrftoken"]
    assert cookie["httponly"] and cookie["samesite"] == "Lax"


def _deploy_check(**env):
    environ = {k: v for k, v in os.environ.items() if not k.startswith("TWIN_")}
    environ.update({"DJANGO_DEBUG": "0", "DJANGO_SECRET_KEY": LONG_KEY, **env})
    return subprocess.run([sys.executable, "manage.py", "check", "--deploy", "--fail-level", "WARNING"],
                          cwd=ROOT, env=environ, capture_output=True, text=True, timeout=120)


def test_check_deploy_is_clean_in_https_mode():
    result = _deploy_check(TWIN_HTTPS="1", TWIN_HTTPS_HOST="192.168.1.20")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "no issues" in result.stdout


def test_check_deploy_in_plain_http_mode_lists_only_the_https_items():
    """Plain HTTP on 127.0.0.1 is the default local mode; the only deploy warnings are the HTTPS ones."""
    result = _deploy_check()
    import re
    codes = set(re.findall(r"\((security\.W\d+)\)", result.stderr + result.stdout))
    assert codes == {"security.W004", "security.W008", "security.W012", "security.W016"}, result.stderr


def test_https_mode_refuses_debug():
    environ = {k: v for k, v in os.environ.items() if not k.startswith("TWIN_")}
    environ.update({"DJANGO_DEBUG": "1", "TWIN_HTTPS": "1"})
    result = subprocess.run([sys.executable, "manage.py", "check"], cwd=ROOT, env=environ, capture_output=True,
                            text=True, timeout=120)
    assert result.returncode != 0 and "refuses to start while DJANGO_DEBUG=1" in result.stderr
