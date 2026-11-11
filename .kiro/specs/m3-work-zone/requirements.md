# M3 Work + Zone — Requirements

## Goal
Measure "the zone" (sustained high-focus work) and what protects or erodes it:
posture, discomfort, triggers (commute, meetings, desk), and short resets
between blocks. Output is a weekly zone report. Same rule as M2: a load
gauge, not a medical assessment.

### R0 Carry-over
- Default probe baseline only if its 10 sessions fall within 42 days; else
  "insufficient baseline: set a ProbeBaseline" (DECISIONS, M2 answers).
- Admin column for `move_time_cv` labeled "ratio".

### R1 Work block additions (all nullable, all in `OMIT_IF_NULL`)
- `posture`: sit | stand | mixed.
- `planned_length_min`: the Pomodoro length the block was planned at (e.g. 25, 40, 50).

### R2 Discomfort check (new record type, CID)
- Fields: at, area (neck | shoulder | wrist | hip | low_back | other),
  score 0–10, trigger (end_of_commute | end_of_meeting | end_of_block |
  standing_long | other), countermove (none | hip_flexor | chin_tuck_pullapart |
  wrist_mobility | dead_hang | calf_weight_shift | walk | other),
  sharp_or_numb (bool), notes.
- `sharp_or_numb = true` is a stop signal: the zone report lists it at the top
  with "stop the block; get it checked by a professional".

### R3 Reset (new record type, CID)
- Fields: at, kind (walk | cold_shower | dead_hang_mobility | breathing | nap | none),
  duration_min, before_probe_cid, after_probe_cid (CIDs of ProbeSessions), notes.
- `none` is the control condition.

### R4 Mini-probe
- New ProbeSession kind `mini_puzzle` (about 5 puzzles, taken between blocks).
  Metrics: accuracy_pct (worse lower), median_solve_s (worse higher).
  M2 baseline/flag logic applies to it like any other kind.

### R5 Zone metrics
- High-focus block: absorption ≥ 4 and interruptions ≤ 1 (missing values → not counted as high-focus).
- Per local week: total work hours; high-focus minutes; focus share
  (high-focus minutes / total minutes); median and interquartile range of
  high-focus block length (the "Θ" band); breakdown by location, posture and
  planned_length_min.
- **Amber (zone):** focus share falls ≥ 20% vs the mean of the previous 3 weeks
  while total hours are within ±10% of that mean — running on effort, not flow.
- Fewer than 3 prior weeks → "insufficient data".

### R6 Reset effect
- Per reset kind: n, mean change (after − before) in mini-probe accuracy and
  median solve time, compared with `none`. Kinds with n < 5 are shown but
  marked "not interpretable yet".

### R7 Discomfort summary
- Per local week: mean score per area; count of checks ≥ 3 by trigger; share
  of ≥ 3 checks followed by a countermove; any sharp_or_numb entries.

### R8 Weekly burnout check (new record type, CID)
- Fields: week_start (local Monday), instrument (free text, e.g. the name of
  the questionnaire used), score, scale_max, notes. Item text is not stored
  or shipped in the repo.
- Shown in the zone report next to the zone and probe trends; never combined into a single score.

### R9 Report
- `python manage.py zone_report [--contributor mike] [--weeks 4] [--json]`,
  covering R5–R8, with "Load gauge, not a medical assessment." and stop
  signals first.

### R10 Quality gate
- Zone, reset and discomfort statistics in plain Python (`twin_metrics/zone.py`),
  unit-tested with synthetic data: high-focus classification with missing
  values, weekly bucketing across midnight and DST weeks, Θ median/IQR,
  zone amber true/false/insufficient, reset n < 5 marking, sharp_or_numb surfacing.
- Existing CIDs unchanged (pinned tests still pass).
- Full suite green in Docker and on GitHub Actions.
