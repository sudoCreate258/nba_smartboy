"""025 Part C: implied muscle volume, imbalance flags, body map (R13-R15). Synthetic fixtures only."""
import datetime

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from core.models import Contributor, DiscomfortCheck, TrainingSession, TrainingSet
from twin_metrics.muscles import flags, validate_map, weekly_volume
from ui.body import build, muscle_map, svg

MAP = {"muscles": ["chest", "upper_back", "triceps", "quads", "hamstrings"],
       "flags": {"lr_ratio_band": [0.9, 1.1],
                 "pairs": [{"muscles": ["chest", "upper_back"], "band": [0.7, 1.4]}]},
       "exercises": {"bench press": {"primary": {"chest": 1.0}, "secondary": {"triceps": 0.5}, "source": "x"},
                     "row": {"primary": {"upper_back": 1.0}, "secondary": {}, "source": "x"},
                     "split squat": {"primary": {"quads": 1.0}, "secondary": {"hamstrings": 0.25}, "source": "x"}}}


def test_volume_is_sets_reps_load_weight():
    v = weekly_volume([{"exercise": "bench press", "reps": 10, "load_kg": 60, "sets": 3},
                       {"exercise": "bench press", "reps": 8, "load_kg": 70},
                       {"exercise": "pull-up", "reps": 8, "load_kg": 0},
                       {"exercise": "row", "reps": 10, "load_kg": None}], MAP)
    assert v["total"] == {"chest": 3 * 10 * 60 + 8 * 70, "triceps": 0.5 * (1800 + 560)}
    assert v["unmapped"] == {"pull-up": 1} and v["no_load"] == 1


def test_left_right_and_pair_flags_follow_the_bands():
    sets = [{"exercise": "split squat", "reps": 10, "load_kg": 20, "side": "L"},
            {"exercise": "split squat", "reps": 10, "load_kg": 20, "side": "R"}]
    v = weekly_volume(sets, MAP)
    assert v["side"]["quads"] == {"L": 200.0, "R": 200.0} and flags(v, MAP) == []  # balanced, no pair trained
    v = weekly_volume(sets + [{"exercise": "split squat", "reps": 3, "load_kg": 20, "side": "L"}], MAP)
    lr = [f for f in flags(v, MAP) if f["kind"] == "left_right"]
    assert {f["muscles"][0] for f in lr} == {"quads", "hamstrings"} and lr[0]["ratio"] == pytest.approx(1.3)
    edge = weekly_volume([{"exercise": "split squat", "reps": 11, "load_kg": 20, "side": "L"},
                          {"exercise": "split squat", "reps": 10, "load_kg": 20, "side": "R"}], MAP)
    assert flags(edge, MAP) == []  # ratio 1.1 is inside the band (inclusive)
    pair = weekly_volume([{"exercise": "bench press", "reps": 10, "load_kg": 100},
                          {"exercise": "row", "reps": 10, "load_kg": 60}], MAP)
    assert [f["ratio"] for f in flags(pair, MAP) if f["kind"] == "pair"] == [pytest.approx(100 / 60)]
    only = weekly_volume([{"exercise": "bench press", "reps": 10, "load_kg": 50}], MAP)
    assert flags(only, MAP) == [{"kind": "pair", "muscles": ["chest", "upper_back"], "ratio": None, "band": [0.7, 1.4]}]


def test_shipped_map_is_valid_and_every_row_has_a_source():
    m = muscle_map()
    assert len(m["exercises"]) >= 20 and all("source" in r for r in m["exercises"].values())
    with pytest.raises(ValueError):
        validate_map({**MAP, "exercises": {"x": {"primary": {"chest": 1.5}, "source": "x"}}})
    with pytest.raises(ValueError):
        validate_map({**MAP, "exercises": {"x": {"primary": {"chest": 1.0}}}})


def test_avatar_renders_an_empty_week():
    out = svg({"total": {}, "side": {}, "unmapped": {}, "no_load": 0}, [])
    assert out.startswith('<svg class="body-map"') and "not measured" in out and "front" in out and "back" in out
    assert 'fill-opacity="0.08"' in out and "style=" not in out


@pytest.fixture
def mike(db):
    return Contributor.objects.get(handle="mike")


def test_week_from_records_and_page(client, mike):
    tz = mike.tzinfo
    monday = datetime.date(2026, 11, 9)
    at = datetime.datetime(2026, 11, 10, 18, 0, tzinfo=tz)
    s = TrainingSession(contributor=mike, started_at=at, program="synthetic", soreness=3)
    s.save()
    TrainingSet(contributor=mike, session_cid=s.cid, order=1, exercise="Bench Press", muscle_group="chest",
                load_kg="60", reps=10, side="bilateral", rpe="8", tempo="3-1-1-0", rest_s=120).save()
    TrainingSet(contributor=mike, session_cid=s.cid, order=2, exercise="split squat", muscle_group="quads",
                load_kg="20", reps=10, side="L", joint_pain=2, joint_pain_area="hip").save()
    DiscomfortCheck(contributor=mike, at=at, area="wrist", score=4, trigger="other").save()
    b = build(mike, monday)
    assert b["sets"] == 2 and b["volume"]["total"]["chest"] == 600
    assert {p["area"] for p in b["pains"]} == {"wrist", "hip"}
    assert any(f["kind"] == "left_right" and f["ratio"] is None for f in b["flags"])  # only the left leg
    assert build(mike, monday - datetime.timedelta(days=7))["sets"] == 0
    client.force_login(get_user_model().objects.create_user("owner", password="a-long-test-password"))
    html = client.get(reverse("ui:body") + "?week=2026-11-12").content.decode()
    assert "Estimated, not measured." in html and "week of 2026-11-09" in html and 'class="pain"' in html
    assert "chest: 600 kg-reps" in html
    empty = client.get(reverse("ui:body") + "?week=2020-01-06").content.decode()
    assert "No sets with a load this week." in empty and "None this week." in empty


def test_new_optional_fields_keep_old_cids(mike):
    """side, rpe, tempo, rest_s and soreness are OMIT_IF_NULL: records without them hash as before."""
    at = datetime.datetime(2026, 11, 10, 18, 0, tzinfo=datetime.timezone.utc)
    s = TrainingSession(contributor=mike, started_at=at, program="RP")
    assert "soreness" not in s.domain_fields()
    st = TrainingSet(contributor=mike, session_cid="x", order=1, exercise="row", muscle_group="back", reps=10)
    assert not {"side", "rpe", "tempo", "rest_s"} & set(st.domain_fields())
