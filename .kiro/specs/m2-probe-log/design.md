# M2 Probe Log — Design

## Modules
- `twin_metrics/probes.py` (plain Python, no Django; it is twin-specific, not Nymbus):
  - `METRICS = {kind: [(name, worse_when), ...]}` from the R1 table.
  - `baseline_stats(sessions, metrics) -> {metric: (mean, sd, n)}`
  - `rolling_z(sessions_after_baseline, stats, metrics, window=3) -> list[{metric: z}]`
  - `flag(z_series, sleep_falling, work_rising) -> (level, reasons)`
  - Inputs are plain lists of dicts / floats. Use `statistics` (sample SD).
- `core/services/probe_report.py` (Django side): loads current records, picks
  the baseline window, computes the sleep and work conditions, calls
  `twin_metrics.probes`, returns a dict the command prints or dumps as JSON.

## Data
- Migration: `ProbeSession.move_time_cv`. Adding a nullable field changes the
  canonical field set, so existing CIDs must stay stable: canonicalization
  omits null-valued fields that did not exist when the record was created, or
  more simply, null fields are omitted from canonical bytes for all records.
  Pick one, state it in DECISIONS, and add a test proving existing CIDs are unchanged.
- `ProbeBaseline` plain model; admin with list filter by kind.

## Edge cases
- Ties and sessions on the same timestamp: order by (started_at, cid).
- Rolling window before 3 post-baseline sessions exist: use what exists; flags need 3 scored sessions.
- Time zone: "days" for the work and sleep windows are local days in the contributor's time zone.
