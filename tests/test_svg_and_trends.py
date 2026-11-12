"""M4-T3: twin_metrics/svg.py (string output) and the trends page."""
import datetime
import re

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from core.models import Contributor, DailySnapshot, DiscomfortCheck, ProbeSession, WorkBlock
from twin_metrics.svg import bar_chart, line_chart
from ui.trends import build

UTC = datetime.timezone.utc


# --- svg ---------------------------------------------------------------------

def test_line_chart_is_accessible_svg_with_values_in_desc():
    svg = line_chart("Sleep <score>", [("01 Nov", 80.0), ("02 Nov", None), ("03 Nov", 72.5)], "pts")
    assert svg.startswith("<svg ") and svg.endswith("</svg>")
    assert 'role="img"' in svg and "<title>Sleep &lt;score&gt;</title>" in svg
    assert "<desc>01 Nov: 80 pts; 02 Nov: no data; 03 Nov: 72.5 pts</desc>" in svg
    assert "<script" not in svg and "http" not in svg


def test_missing_values_break_the_line_and_are_not_filled():
    svg = line_chart("x", [("a", 1.0), ("b", 2.0), ("c", None), ("d", 3.0), ("e", 4.0)])
    assert svg.count("<polyline") == 2 and svg.count("<circle") == 4
    lone = line_chart("x", [("a", 1.0), ("b", None), ("c", 2.0)])
    assert lone.count("<polyline") == 0 and lone.count("<circle") == 2


def test_band_and_empty_and_flat_series():
    assert 'class="band"' in line_chart("x", [("a", 50.0)], band=(40.0, 60.0))
    assert "Reference range 40 to 60" in line_chart("x", [("a", 50.0)], band=(40.0, 60.0))
    empty = line_chart("x", [])
    assert "<desc>no data</desc>" in empty and "<polyline" not in empty
    assert "<circle" in line_chart("x", [("a", 5.0), ("b", 5.0)])  # flat line still renders


def test_bar_chart():
    svg = bar_chart("Hours", [("w1", 10.0), ("w2", None), ("w3", 0.0)], "h")
    assert svg.count('class="bar"') == 2 and "w2: no data" in svg


# --- trends page ---------------------------------------------------------------

@pytest.fixture
def mike(db):
    return Contributor.objects.get(handle="mike")


TODAY = datetime.date(2026, 11, 11)  # Wednesday


def test_build_charts_with_data(mike):
    DailySnapshot(contributor=mike, date=TODAY, source="manual", sleep_score=82, hrv=50, resting_hr_sleep=52,
                  bedtime=datetime.datetime(2026, 11, 11, 5, 30, tzinfo=UTC),  # 00:30 New York
                  bia_timing="pre_session", weight_kg="70.0").save()
    DailySnapshot(contributor=mike, date=TODAY - datetime.timedelta(days=1), source="manual", bia_timing="unknown",
                  weight_kg="71.0").save()
    start = datetime.datetime(2026, 11, 10, 14, tzinfo=UTC)
    WorkBlock(contributor=mike, start=start, end=start + datetime.timedelta(hours=2), task_type="code", absorption=5,
              interruptions=0).save()
    DiscomfortCheck(contributor=mike, at=start, area="low_back", score=4, trigger="other").save()
    data = build(mike, weeks=4, today=TODAY)
    titles = [c["title"] for c in data["charts"]]
    assert titles[:6] == ["Sleep score", "Bedtime (hour, 24 = midnight)", "Resting HR during sleep", "HRV",
                          "Weight (pre-session readings only)", "Body fat (pre-session readings only)"]
    by = {c["title"]: c for c in data["charts"]}
    assert "11 Nov: 82" in by["Sleep score"]["svg"]
    assert "11 Nov: 24.5" in by["Bedtime (hour, 24 = midnight)"]["svg"]
    weight = by["Weight (pre-session readings only)"]["svg"]
    assert "11 Nov: 70 kg" in weight and "10 Nov: no data" in weight  # the unknown-timing reading is not shown
    assert "09 Nov: 2 h" in by["Weekly work hours"]["svg"]
    assert "09 Nov: 100 %" in by["Weekly focus share"]["svg"]
    assert "Discomfort: low back (weekly mean, 0-10)" in by
    assert data["first_day"] == datetime.date(2026, 10, 19)
    assert all(c["source"] for c in data["charts"])


def test_probe_chart_band_needs_a_usable_baseline(mike):
    t0 = datetime.datetime(2026, 10, 20, 14, tzinfo=UTC)
    for i in range(12):
        ProbeSession(contributor=mike, started_at=t0 + datetime.timedelta(days=i), kind="puzzle_set",
                     accuracy_pct=80 + (-1) ** i).save()
    by = {c["title"]: c for c in build(mike, weeks=4, today=TODAY)["charts"]}
    puzzle = by["Probe puzzle_set: rolling median accuracy (last 3 sessions)"]
    assert 'class="band"' in puzzle["svg"] and "baseline mean +/- 1 SD" in puzzle["source"]
    rapid = by["Probe rapid_game: rolling median accuracy (last 3 sessions)"]
    assert 'class="band"' not in rapid["svg"] and "no usable baseline yet" in rapid["source"]


@pytest.fixture
def client_in(client, db):
    client.force_login(get_user_model().objects.create_user("owner", password="a-long-test-password"))
    return client


@pytest.mark.parametrize("weeks,expected", [("4", "4 weeks"), ("12", "12 weeks"), ("nope", "4 weeks")])
def test_trends_page(client_in, mike, weeks, expected):
    page = client_in.get(reverse("ui:trends") + f"?weeks={weeks}")
    html = page.content.decode()
    assert page.status_code == 200 and f"<strong>{expected}</strong>" in html
    assert html.count("<svg ") >= 11 and html.count("Load gauge, not a medical assessment.") >= 11
    assert re.findall(r"<script[^>]*>", html) == ['<script src="/static/ui/offline.js" defer>']
    assert not re.search(r"https?://", html)
    assert len(page.content) < 200_000


def test_trends_requires_login(client, db):
    assert client.get(reverse("ui:trends")).status_code == 302
