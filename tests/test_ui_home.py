"""M4-T1: app skeleton (login, base layout, home screen with today's status)."""
import datetime
import re
from pathlib import Path

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from core.models import Contributor, DailySnapshot, DiscomfortCheck, ProbeSession, TrainingSession, TrainingSet
from ui.today import checkins, today

ROOT = Path(__file__).resolve().parent.parent
UTC = datetime.timezone.utc
NOW = datetime.datetime(2026, 11, 11, 17, 0, tzinfo=UTC)  # 12:00 New York, Wednesday


@pytest.fixture
def mike(db):
    return Contributor.objects.get(handle="mike")


@pytest.fixture
def user(db):
    return get_user_model().objects.create_user("owner", password="a-long-test-password")


@pytest.fixture
def logged_in(client, user):
    client.force_login(user)
    return client


def test_every_page_requires_login(client, db):
    resp = client.get(reverse("ui:home"))
    assert resp.status_code == 302 and resp.url.startswith(reverse("ui:login"))


def test_login_page_and_login(client, user):
    page = client.get(reverse("ui:login"))
    assert page.status_code == 200 and b'name="csrfmiddlewaretoken"' in page.content
    bad = client.post(reverse("ui:login"), {"username": "owner", "password": "wrong"})
    assert bad.status_code == 200 and b'role="alert"' in bad.content
    resp = client.post(reverse("ui:login"), {"username": "owner", "password": "a-long-test-password"})
    assert resp.status_code == 302 and resp.url == reverse("ui:home")
    assert client.get(reverse("ui:login")).status_code == 302  # already logged in


def test_logout_is_post_only(logged_in):
    assert logged_in.get(reverse("ui:logout")).status_code == 405
    assert logged_in.post(reverse("ui:logout")).status_code == 302
    assert logged_in.get(reverse("ui:home")).status_code == 302


def test_checkins_done_and_missing(mike):
    day = NOW.astimezone(mike.tzinfo).date()
    DailySnapshot(contributor=mike, date=day, source="manual", sleep_score=80).save()
    ProbeSession(contributor=mike, started_at=NOW, kind="mini_puzzle", accuracy_pct=80).save()
    ProbeSession(contributor=mike, started_at=NOW - datetime.timedelta(days=1), kind="puzzle_set").save()
    assert {label: done for label, done, _ in checkins(mike, day)} == {"Daily snapshot": True, "Probe": True, "Work block": False,
                                        "Discomfort check": False, "Reset": False}


def test_checkins_use_the_local_day(mike):
    # 01:00 UTC on the 12th is 20:00 on the 11th in New York.
    DiscomfortCheck(contributor=mike, at=datetime.datetime(2026, 11, 12, 1, 0, tzinfo=UTC), area="neck", score=2,
                    trigger="other").save()
    assert {l: d for l, d, _ in checkins(mike, datetime.date(2026, 11, 11))}["Discomfort check"] is True
    assert {l: d for l, d, _ in checkins(mike, datetime.date(2026, 11, 12))}["Discomfort check"] is False


def test_today_collects_stop_signals_from_discomfort_and_training(mike):
    DiscomfortCheck(contributor=mike, at=NOW - datetime.timedelta(hours=2), area="wrist", score=7, trigger="other",
                    sharp_or_numb=True).save()
    session = TrainingSession(contributor=mike, started_at=NOW - datetime.timedelta(hours=1), program="RP")
    session.save()
    TrainingSet(contributor=mike, session_cid=session.cid, order=1, exercise="Squat", muscle_group="quads", reps=5,
                joint_pain=2, joint_pain_area="low_back").save()
    t = today(mike, now=NOW)
    assert [s["what"] for s in t["stop_signals"]] == ["wrist discomfort, score 7", "joint pain 2 (low_back), squat"]
    assert {p["kind"] for p in t["probes"]} == {"puzzle_set", "rapid_game", "mini_puzzle"}
    assert t["zone"]["flag"] == "insufficient data"


def test_home_page(logged_in, mike):
    DiscomfortCheck(contributor=mike, at=datetime.datetime.now(UTC), area="wrist", score=7, trigger="other",
                    sharp_or_numb=True).save()
    page = logged_in.get(reverse("ui:home"))
    html = page.content.decode()
    assert page.status_code == 200
    assert html.index("Stop signals") < html.index("Check-ins") < html.index("Flags")
    assert "wrist discomfort, score 7" in html and "Stop the block; get it checked by a professional." in html
    assert "Discomfort check: done" in html and "Work block: missing" in html
    assert "Load gauge, not a medical assessment." in html
    assert len(page.content) < 200_000


def test_home_without_stop_signals_has_no_alert(logged_in, mike):
    html = logged_in.get(reverse("ui:home")).content.decode()
    assert 'role="alert"' not in html and "Probe: puzzle_set" in html


def test_templates_and_static_make_no_external_requests():
    """Early version of the R3 scan (T7 extends it): no http(s) URL to another host."""
    files = list((ROOT / "ui").rglob("*.html")) + list((ROOT / "ui").rglob("*.css")) + list((ROOT / "ui").rglob("*.js"))
    assert files
    for path in files:
        urls = re.findall(r"https?://[^\s\"')]+", path.read_text(encoding="utf-8"))
        assert urls == [], (path, urls)
