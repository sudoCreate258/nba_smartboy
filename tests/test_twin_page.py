"""027 Part C: /twin/ owner page and its daily summary. Synthetic fixtures only."""
import copy
import datetime
import json
from pathlib import Path

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from core.models import Contributor, TwinMinute
from core.services.records import save_record
from twin_metrics.dtom import sparkline, summarize_day

MINUTE = json.loads((Path(__file__).resolve().parent / "fixtures" / "twin_minute.SYNTHETIC.json").read_text("utf-8"))
UTC = datetime.timezone.utc


def minute_at(start, **changes):
    doc = copy.deepcopy(MINUTE)
    doc["t_start"] = start.isoformat().replace("+00:00", "Z")
    doc["t_end"] = (start + datetime.timedelta(minutes=1)).isoformat().replace("+00:00", "Z")
    for path, value in changes.items():
        target = doc
        keys = path.split("__")
        for k in keys[:-1]:
            target = target[k]
        target[keys[-1]] = value
    return doc


def test_summary_skips_nulls_never_counts_them_as_zero():
    a = minute_at(datetime.datetime(2026, 11, 13, 15, 5, tzinfo=UTC))  # neck 11 avg, back null
    b = minute_at(datetime.datetime(2026, 11, 13, 15, 6, tzinfo=UTC), load_pct_avg__neck=5.0,
                  load_pct_max__neck=20.0, face__blinks_per_min=None, face__looking_pct__screen=75,
                  posture__sitting_s=30)
    s = summarize_day([a, b])
    assert s["minutes"] == 2 and s["sitting_min"] == 1.5
    assert s["load_avg"]["neck"] == 8.0 and s["load_max"]["neck"] == 20.0
    assert s["load_avg"]["back"] is None and s["load_max"]["back"] is None and s["fatigue_max"]["back"] is None
    assert s["minutes_above"] == {"neck": 1, "back": 0, "shL": 0, "shR": 0}  # 11 > 10, 5 is not
    assert s["blinks_per_min"] == 13 and s["screen_pct"] == 80
    empty = summarize_day([])
    assert empty["minutes"] == 0 and empty["sitting_min"] is None and empty["blinks_per_min"] is None


def test_sparkline_has_gaps_for_nulls():
    assert sparkline([None, None]) == []
    segments = sparkline([1, 2, None, 3])
    assert len(segments) == 2 and segments[0].count(",") == 2 and segments[1].count(",") == 1
    assert sparkline([4, 4])  # a flat line still draws


@pytest.fixture
def client_in(client, db):
    client.force_login(get_user_model().objects.create_user("owner", password="a-long-test-password"))
    return client


def store(mike, doc):
    start = datetime.datetime.fromisoformat(doc["t_start"].replace("Z", "+00:00"))
    save_record(TwinMinute(contributor=mike, source="dtom", t_start=start,
                           t_end=start + datetime.timedelta(minutes=1), data=doc))


def test_page_shows_the_day_with_label_rows_and_summary(client_in):
    mike = Contributor.objects.get(handle="mike")
    store(mike, minute_at(datetime.datetime(2026, 11, 13, 15, 5, tzinfo=UTC)))
    store(mike, minute_at(datetime.datetime(2026, 11, 13, 15, 6, tzinfo=UTC), load_pct_avg__neck=5.0))
    store(mike, minute_at(datetime.datetime(2026, 11, 14, 15, 5, tzinfo=UTC)))  # another local day
    from core.management.commands.import_twin_capture import import_capture
    from tests.test_twin_import import CAPTURE, load
    import_capture(load(CAPTURE), mike)  # samples at 15:05 and 15:20 UTC on the same day
    html = client_in.get(reverse("ui:twin") + "?day=2026-11-13").content.decode()
    assert "Estimated by dtom, not a clinical measurement." in html
    assert "<dt>Minutes recorded</dt><dd>2</dd>" in html and "<dt>Sitting</dt><dd>2 min</dd>" in html
    assert html.count("<td>10:0") == 2  # 15:05 and 15:06 UTC are 10:05 and 10:06 in New York
    assert '<polyline points="' in html and "10:05 sitting, looking screen" in html and "10:20 standing" in html
    assert "<td>Back</td><td>–</td><td>–</td>" in html  # never measured: a dash, not 0


def test_empty_day_needs_login_and_bad_day_falls_back(client, client_in):
    html = client_in.get(reverse("ui:twin") + "?day=2020-01-01").content.decode()
    assert "No dtom minutes on this day." in html and "None on this day." in html
    assert client_in.get(reverse("ui:twin") + "?day=nope").status_code == 200
    assert client_in.post(reverse("ui:twin")).status_code == 405
    client.logout()
    assert client.get(reverse("ui:twin")).status_code == 302
