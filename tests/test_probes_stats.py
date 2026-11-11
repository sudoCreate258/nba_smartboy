import statistics

import pytest

from twin_metrics import probes
from twin_metrics.probes import METRICS, baseline_stats, evaluate_kind, flag, rolling_medians, rolling_z

PAT = [-1, 1] * 5  # mean 0, sample SD ~1.054


def puzzle(acc=80.0, solve=10.0):
    return {"accuracy_pct": acc, "median_solve_s": solve}


def puzzle_baseline():
    # accuracy SD ~2.108, solve SD ~1.054
    return [puzzle(80 + 2 * p, 10 + p) for p in PAT]


SD_ACC = statistics.stdev([80 + 2 * p for p in PAT])
SD_SOLVE = statistics.stdev([10 + p for p in PAT])


def shifted(n, sds, acc=True, solve=True):
    """n sessions whose accuracy is `sds` SD worse and solve time `sds` SD worse."""
    return [
        puzzle(80 - sds * SD_ACC if acc else 80, 10 + sds * SD_SOLVE if solve else 10)
        for _ in range(n)
    ]


def run(later, base=None, kind="puzzle_set", **kw):
    return evaluate_kind(kind, base if base is not None else puzzle_baseline(), later, **kw)


def test_metric_table_matches_requirements():
    assert METRICS["puzzle_set"] == [("accuracy_pct", "lower"), ("median_solve_s", "higher")]
    assert METRICS["rapid_game"] == [
        ("accuracy_pct", "lower"),
        ("late_blunders", "higher"),
        ("fast_blunders", "higher"),
        ("move_time_cv", "higher"),
    ]
    assert "module" not in METRICS


def test_baseline_stats_mean_sample_sd_n():
    stats = baseline_stats(puzzle_baseline(), METRICS["puzzle_set"])
    mean, sd, n = stats["accuracy_pct"]
    assert (mean, n) == (80.0, 10)
    assert sd == pytest.approx(SD_ACC)


def test_baseline_stats_ignore_missing_values():
    sessions = puzzle_baseline()
    sessions[0]["median_solve_s"] = None
    assert baseline_stats(sessions, METRICS["puzzle_set"])["median_solve_s"][2] == 9


def test_stable_series_no_flag():
    result = run(shifted(6, 0.0))
    assert result["status"] == "ok" and result["level"] == "none"
    assert all(abs(z) < 1e-9 for z in result["z"].values())


def test_amber_after_sustained_one_sd_drop_on_two_metrics():
    result = run(shifted(3, 1.2))
    assert result["level"] == "amber"
    assert result["z"]["accuracy_pct"] == pytest.approx(1.2)
    assert result["z"]["median_solve_s"] == pytest.approx(1.2)


def test_no_amber_with_only_one_metric_elevated():
    assert run(shifted(4, 1.2, solve=False))["level"] == "none"


def test_no_amber_after_a_single_bad_session():
    later = shifted(3, 0.0) + shifted(1, 3.0) + shifted(2, 0.0)
    assert run(later)["level"] == "none"


def test_needs_three_scored_sessions():
    result = run(shifted(2, 3.0))
    assert result["level"] == "none"
    assert "needs 3 scored sessions" in result["reasons"][0]


def test_red_at_one_and_a_half_sd():
    result = run(shifted(3, 1.6))
    assert result["level"] == "red"


def test_between_thresholds_is_amber_not_red():
    assert run(shifted(3, 1.2))["level"] == "amber"


def test_red_via_amber_plus_falling_sleep():
    result = run(shifted(3, 1.2), sleep_falling=True)
    assert result["level"] == "red"
    assert "sleep is falling" in result["reasons"]


def test_red_via_amber_plus_rising_work():
    result = run(shifted(3, 1.2), work_rising=True)
    assert result["level"] == "red"
    assert "work load is rising" in result["reasons"]


def test_unknown_or_false_context_does_not_raise_flag():
    assert run(shifted(3, 1.2), sleep_falling=None, work_rising=False)["level"] == "amber"
    assert run(shifted(3, 0.0), sleep_falling=True, work_rising=True)["level"] == "none"


def test_context_alone_never_flags():
    assert flag([{"accuracy_pct": 0.2}] * 3, True, True)[0] == "none"


@pytest.mark.parametrize("n", [0, 9])
def test_insufficient_baseline(n):
    result = run(shifted(5, 3.0), base=puzzle_baseline()[:n])
    assert result["status"] == "insufficient_baseline"
    assert result["level"] == "none"
    assert result["reasons"] == [f"insufficient baseline: {n} of 10 sessions"]


def test_zero_sd_metric_is_skipped_and_named():
    base = [puzzle(80, 10 + p) for p in PAT]  # accuracy never varies
    result = run(shifted(3, 1.2), base=base)
    assert "accuracy_pct" in result["skipped"] and "SD is 0" in result["skipped"]["accuracy_pct"]
    assert "accuracy_pct" not in result["z"]
    assert result["level"] == "none"  # only one scoreable metric left


def test_metric_with_fewer_than_ten_values_is_skipped():
    base = puzzle_baseline()
    for s in base[:2]:
        s["median_solve_s"] = None
    result = run(shifted(3, 1.2), base=base)
    assert "median_solve_s" in result["skipped"] and "fewer than 10" in result["skipped"]["median_solve_s"]
    assert "median_solve_s" not in result["z"]


def test_direction_lower_is_worse_for_accuracy_higher_for_solve_time():
    better = [puzzle(80 + 2 * SD_ACC, 10 - SD_SOLVE)] * 3
    z = run(better)["z"]
    assert z["accuracy_pct"] == pytest.approx(-2.0) and z["median_solve_s"] == pytest.approx(-1.0)
    assert run(better)["level"] == "none"


def test_direction_higher_is_worse_for_rapid_metrics():
    base = [
        {"accuracy_pct": 70 + p, "late_blunders": 2 + p, "fast_blunders": 1 + p, "move_time_cv": 0.5 + p / 10}
        for p in PAT
    ]
    sd = statistics.stdev(PAT)
    worse = [{"accuracy_pct": 70 - 2 * sd, "late_blunders": 2 + 2 * sd, "fast_blunders": 1 + 2 * sd,
              "move_time_cv": 0.5 + 0.2 * sd}] * 3
    result = run(worse, base=base, kind="rapid_game")
    assert all(z == pytest.approx(2.0) for z in result["z"].values())
    assert result["level"] == "red"


def test_rolling_median_uses_what_exists_then_three():
    sessions = [{"a": v} for v in (1, 5, 3, 9, 9)]
    got = rolling_medians(sessions, [("a", "higher")])
    assert [r["a"] for r in got] == [1, 3, 3, 5, 9]


def test_rolling_median_ignores_none_and_drops_empty_metric():
    got = rolling_medians([{"a": None}, {"a": 4}], [("a", "higher")])
    assert got == [{}, {"a": 4}]


def test_rolling_z_is_empty_for_no_sessions():
    stats = baseline_stats(puzzle_baseline(), METRICS["puzzle_set"])
    assert rolling_z([], stats, METRICS["puzzle_set"]) == []


def test_module_has_no_django_import():
    source = open(probes.__file__, encoding="utf-8").read()
    assert "django" not in source.lower().replace("no django imports", "")
