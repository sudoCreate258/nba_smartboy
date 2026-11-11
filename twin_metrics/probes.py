# SPDX-License-Identifier: AGPL-3.0-or-later
"""Probe statistics: baseline, rolling z-scores and amber/red flags.

Plain Python, no Django imports. A session is a dict of metric name to number
(or None when the metric was not recorded). This is a load gauge, not a
medical assessment.
"""
import statistics

LOWER, HIGHER = "lower", "higher"

# kind -> [(metric, direction that counts as "worse")]
METRICS = {
    "puzzle_set": [("accuracy_pct", LOWER), ("median_solve_s", HIGHER)],
    "rapid_game": [
        ("accuracy_pct", LOWER),
        ("late_blunders", HIGHER),
        ("fast_blunders", HIGHER),
        ("move_time_cv", HIGHER),
    ],
}

MIN_BASELINE = 10  # sessions in the window, and values per metric
WINDOW = 3  # rolling median window, also the run of sessions a flag needs
AMBER_Z, RED_Z = 1.0, 1.5
MIN_METRICS = 2  # metrics that must be elevated at once


def _values(sessions, name):
    return [s[name] for s in sessions if s.get(name) is not None]


def baseline_stats(sessions, metrics):
    """{metric: (mean, sd, n)} over the baseline sessions; sample SD.

    mean/sd are None when there are no values (mean) or fewer than two (sd).
    """
    out = {}
    for name, _ in metrics:
        values = _values(sessions, name)
        mean = statistics.fmean(values) if values else None
        sd = statistics.stdev(values) if len(values) >= 2 else None
        out[name] = (mean, sd, len(values))
    return out


def skipped_metrics(stats):
    """{metric: reason} for metrics that cannot be scored."""
    out = {}
    for name, (_, sd, n) in stats.items():
        if n < MIN_BASELINE:
            out[name] = f"fewer than {MIN_BASELINE} baseline values ({n})"
        elif not sd:
            out[name] = "baseline SD is 0"
    return out


def rolling_medians(sessions, metrics, window=WINDOW):
    """Per session, per metric: median of that session and up to window-1 before it.

    Uses what exists when fewer sessions precede; None values are ignored; a
    metric with no values in the window is absent from that session's dict.
    """
    out = []
    for i in range(len(sessions)):
        chunk = sessions[max(0, i - window + 1) : i + 1]
        row = {}
        for name, _ in metrics:
            values = _values(chunk, name)
            if values:
                row[name] = statistics.median(values)
        out.append(row)
    return out


def rolling_z(sessions_after_baseline, stats, metrics, window=WINDOW):
    """Per session after the baseline: {metric: z}, positive = worse. Skipped metrics are absent."""
    skipped = skipped_metrics(stats)
    out = []
    for medians in rolling_medians(sessions_after_baseline, metrics, window):
        row = {}
        for name, direction in metrics:
            if name in skipped or name not in medians:
                continue
            mean, sd, _ = stats[name]
            z = (medians[name] - mean) / sd
            row[name] = -z if direction == LOWER else z
        out.append(row)
    return out


def _sustained(z_series, threshold):
    """True when each of the latest WINDOW sessions has >= MIN_METRICS metrics at z >= threshold."""
    if len(z_series) < WINDOW:
        return False
    return all(
        sum(1 for z in row.values() if z >= threshold) >= MIN_METRICS for row in z_series[-WINDOW:]
    )


def flag(z_series, sleep_falling=None, work_rising=None):
    """(level, reasons); level is 'none', 'amber' or 'red'.

    sleep_falling / work_rising are True, False, or None for insufficient data
    (None never raises a flag).
    """
    if len(z_series) < WINDOW:
        return "none", [f"needs {WINDOW} scored sessions after the baseline ({len(z_series)} so far)"]
    if _sustained(z_series, RED_Z):
        return "red", [f"{MIN_METRICS}+ metrics at z >= {RED_Z} for {WINDOW} sessions in a row"]
    if _sustained(z_series, AMBER_Z):
        reasons = [f"{MIN_METRICS}+ metrics at z >= {AMBER_Z} for {WINDOW} sessions in a row"]
        context = [text for text, on in (("sleep is falling", sleep_falling), ("work load is rising", work_rising)) if on]
        if context:
            return "red", reasons + context
        return "amber", reasons
    return "none", []


def deviates(value, baseline_values, worse, k=1.0):
    """Is `value` at least k sample SDs worse than the mean of baseline_values?

    worse is 'lower' (sleep) or 'higher' (work hours). Returns None (insufficient
    data) when value is missing, there are fewer than two baseline values, or their SD is 0.
    """
    if value is None or len(baseline_values) < 2:
        return None
    sd = statistics.stdev(baseline_values)
    if not sd:
        return None
    gap = statistics.fmean(baseline_values) - value if worse == LOWER else value - statistics.fmean(baseline_values)
    return gap >= k * sd


def evaluate_kind(kind, baseline_sessions, later_sessions, sleep_falling=None, work_rising=None,
                  baseline_problem=None):
    """Full result for one probe kind from plain-dict sessions (oldest first).

    baseline_problem: text explaining why the baseline window cannot be used
    (for example a default window spread over too many days); no flags are raised.
    """
    metrics = METRICS[kind]
    result = {
        "kind": kind,
        "n_baseline": len(baseline_sessions),
        "n_scored": len(later_sessions),
        "stats": {},
        "skipped": {},
        "medians": {},
        "z": {},
        "level": "none",
        "reasons": [],
    }
    if baseline_problem:
        result["status"] = "insufficient_baseline"
        result["reasons"] = [baseline_problem]
        return result
    if len(baseline_sessions) < MIN_BASELINE:
        result["status"] = "insufficient_baseline"
        result["reasons"] = [f"insufficient baseline: {len(baseline_sessions)} of {MIN_BASELINE} sessions"]
        return result
    stats = baseline_stats(baseline_sessions, metrics)
    z_series = rolling_z(later_sessions, stats, metrics)
    result["status"] = "ok"
    result["stats"] = stats
    result["skipped"] = skipped_metrics(stats)
    if later_sessions:
        result["medians"] = rolling_medians(later_sessions, metrics)[-1]
        result["z"] = z_series[-1]
    result["level"], result["reasons"] = flag(z_series, sleep_falling, work_rising)
    return result
