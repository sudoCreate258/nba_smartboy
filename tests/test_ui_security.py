"""M4-T5: LAN opt-in mode, debug-off static files, cookie/CSRF settings, login rate limit (R4)."""
import os
import subprocess
import sys
from pathlib import Path

import pytest
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import Client
from django.urls import reverse

ROOT = Path(__file__).resolve().parent.parent


def load_settings(env, expr="settings.ALLOWED_HOSTS, settings.CSRF_TRUSTED_ORIGINS"):
    base = {k: v for k, v in os.environ.items() if not k.startswith(("DJANGO_", "TWIN_"))}
    base.update({"DJANGO_SETTINGS_MODULE": "twin.settings", "DJANGO_SECRET_KEY": "x", **env})
    return subprocess.run([sys.executable, "-c", f"from django.conf import settings; print({expr})"],
                          env=base, capture_output=True, text=True, cwd=ROOT)


def test_lan_mode_is_off_by_default():
    result = load_settings({})
    assert result.returncode == 0
    assert result.stdout.strip() == "['localhost', '127.0.0.1'] []"
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    assert '"${TWIN_LAN_HOST:-127.0.0.1}:8000:8000"' in compose


def test_lan_mode_allows_the_lan_host():
    result = load_settings({"TWIN_LAN_HOST": "192.168.1.20"})
    assert result.returncode == 0
    assert result.stdout.strip() == "['localhost', '127.0.0.1', '192.168.1.20'] ['http://192.168.1.20:8000']"


def test_lan_mode_refuses_to_start_with_debug_on():
    result = load_settings({"TWIN_LAN_HOST": "192.168.1.20", "DJANGO_DEBUG": "1"})
    assert result.returncode != 0 and "refuses to start while DJANGO_DEBUG=1" in result.stderr


def test_env_example_defaults_to_debug_off_and_explains_the_secret_key():
    text = (ROOT / ".env.example").read_text(encoding="utf-8")
    assert "DJANGO_DEBUG=0" in text and "get_random_secret_key" in text
    assert "# TWIN_LAN_HOST=" in text  # documented, commented out


def test_cookie_and_header_settings():
    assert settings.SESSION_COOKIE_HTTPONLY and settings.CSRF_COOKIE_HTTPONLY
    assert settings.SESSION_COOKIE_SAMESITE == "Lax" == settings.CSRF_COOKIE_SAMESITE
    assert "django.middleware.csrf.CsrfViewMiddleware" in settings.MIDDLEWARE
    assert settings.X_FRAME_OPTIONS == "DENY"


@pytest.mark.parametrize("path", ["/static/ui/app.css", "/static/ui/offline.js", "/static/admin/css/base.css"])
def test_static_files_are_served_with_debug_off(client, db, path):
    assert settings.DEBUG is False  # pytest-django runs with debug off
    resp = client.get(path)
    assert resp.status_code == 200
    assert b"".join(resp.streaming_content if resp.streaming else [resp.content])


def test_forms_require_csrf(db):
    strict = Client(enforce_csrf_checks=True)
    strict.force_login(get_user_model().objects.create_user("owner", password="a-long-test-password"))
    resp = strict.post(reverse("ui:checkin", args=["discomfort"]), {"area": "neck"})
    assert resp.status_code == 403


@pytest.fixture
def user(db):
    cache.clear()
    yield get_user_model().objects.create_user("owner", password="a-long-test-password")
    cache.clear()


def test_login_is_rate_limited(client, user):
    for _ in range(settings.TWIN_LOGIN_MAX_FAILURES):
        assert client.post(reverse("ui:login"), {"username": "owner", "password": "wrong"}).status_code == 200
    blocked = client.post(reverse("ui:login"), {"username": "owner", "password": "a-long-test-password"})
    assert blocked.status_code == 429 and b"Too many failed attempts" in blocked.content
    assert client.get(reverse("ui:home")).status_code == 302  # still logged out


def test_rate_limit_is_per_address_too(user):
    for i in range(settings.TWIN_LOGIN_MAX_FAILURES):
        Client(REMOTE_ADDR="10.0.0.9").post(reverse("ui:login"), {"username": f"guess{i}", "password": "x"})
    other_user = Client(REMOTE_ADDR="10.0.0.9").post(reverse("ui:login"), {"username": "owner", "password": "x"})
    assert other_user.status_code == 429
    elsewhere = Client(REMOTE_ADDR="10.0.0.10").post(
        reverse("ui:login"), {"username": "owner", "password": "a-long-test-password"})
    assert elsewhere.status_code == 302


def test_successful_login_resets_the_username_count(client, user):
    for _ in range(settings.TWIN_LOGIN_MAX_FAILURES - 1):
        client.post(reverse("ui:login"), {"username": "owner", "password": "wrong"})
    assert client.post(reverse("ui:login"), {"username": "owner", "password": "a-long-test-password"}).status_code == 302
    assert cache.get("login-fail:user:owner") is None
