# M2 Probe Log — Requirements

## Goal
Turn logged probe sessions into a cognitive-load gauge: a frozen baseline per
probe kind, rolling medians, and amber/red flags that are read together with
sleep and work load. It is a load gauge, not a diagnosis; every report says so.

Housekeeping from the M1.1 review comes first (R0).

### R0 Housekeeping (from DECISIONS, "Planner answers to the M1.1 builder choices and review")
- `record_snapshot` validates before hashing; naive datetime → ValidationError.
- Admin correction with a bad `supersedes` value → form error, not 500.
- SPDX header on `core/migrations/0008_validation_bounds.py`.
- Ambiguous/nonexistent local times (DST) → ValidationError naming the field.
- `git add --renormalize .`; `.agents/` added to `.gitignore`.
- Push `main`; first GitHub Actions run green; run URL recorded in DECISIONS Status.

### R1 Probe fields
- ProbeSession gains `move_time_cv` (Decimal, 2 dp, ≥ 0, nullable): coefficient
  of variation of time per move for rapid games.
- Metrics per kind, with the direction that counts as "worse":

| Kind | Metric | Worse when |
|---|---|---|
| puzzle_set | accuracy_pct | lower |
| puzzle_set | median_solve_s | higher |
| rapid_game | accuracy_pct | lower |
| rapid_game | late_blunders | higher |
| rapid_game | fast_blunders | higher |
| rapid_game | move_time_cv | higher |

- `module` sessions are stored but not scored in M2.

### R2 Baseline
- `ProbeBaseline(contributor, kind, start, end, frozen_at)`, set by the owner in
  admin. It is configuration, not contributed data, so it has no CID.
- If none is set for a kind, the baseline is the first 10 current sessions of that kind.
- A baseline needs ≥ 10 current sessions in its window; otherwise the kind reports
  "insufficient baseline" and raises no flags.
- Per metric: mean and SD over the window. A metric with SD = 0 or < 10 values is skipped and named in the report.

### R3 Rolling signal
- Only current records count (superseded ones are ignored).
- For each scored session after the baseline window: per metric, the median of
  that session and the two before it (same kind), then
  z = (rolling median − baseline mean) / SD, signed so positive = worse.

### R4 Flags
- **Amber:** at the latest three scored sessions in a row, at least two metrics have z ≥ 1.0.
- **Red:** the same at z ≥ 1.5, OR amber while sleep is falling or work load is rising.
- **Sleep falling:** mean sleep_score of the last 3 current nights up to the
  latest session is ≥ 1 SD below the mean of nights inside the baseline window.
- **Work rising:** total WorkBlock hours in the 3 days up to the latest session
  are ≥ 1 SD above the mean 3-day total inside the baseline window.
- Missing sleep or work data → that condition is "insufficient data" (not true), and the report says so.

### R5 Report
- `python manage.py probe_report [--contributor mike] [--kind ...] [--json]`
  prints, per kind: baseline window and n, latest rolling medians and z per
  metric, skipped metrics, flag (none/amber/red) with the reasons, sleep and
  work conditions, and the line "Load gauge, not a medical assessment."
- Probe sessions remain entered through admin (adapters for chess.com come later).

### R6 Quality gate
- The statistics live in a plain-Python module with no Django imports and are
  unit-tested with synthetic series: no flag on a stable series, amber after a
  sustained 1 SD drop on two metrics, no amber after a single bad session,
  red at 1.5 SD, red via amber + falling sleep, insufficient baseline,
  SD = 0 skip, superseded sessions excluded, direction handling per metric.
- Full suite green in Docker and on GitHub Actions.
