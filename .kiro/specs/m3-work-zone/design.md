# M3 Work + Zone — Design

- New record models `DiscomfortCheck`, `Reset`, `WeeklyCheck` subclass
  `ProvenancedRecord` (CID, contributor, immutable, corrections via Supersession,
  admin "Save as correction" via `CorrectableAdmin`).
- `Reset.before_probe_cid` / `after_probe_cid` are plain CID strings (same
  rule as Supersession). Validation: both must reference current
  `mini_puzzle` sessions of the same contributor, before < reset.at < after.
- `WorkBlock.posture` and `planned_length_min` added to `WorkBlock.OMIT_IF_NULL`.
- `twin_metrics/zone.py` (no Django): takes lists of dicts with aware UTC
  datetimes and a tz name; buckets by local ISO week (Monday start).
  Blocks crossing midnight count in the week of their start.
- `core/services/zone_report.py` loads current records and calls it;
  `zone_report` command prints text or JSON.
- Mini-probe kind added to `twin_metrics/probes.METRICS`.
