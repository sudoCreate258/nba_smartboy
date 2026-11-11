# M3 Work + Zone — Tasks

Start from `main` after the M2 PR is merged. Branch `feature/m3-work-zone`.

- [ ] T0. Carry-over (R0): 42-day rule for the default baseline; "ratio" label. Tests.
- [ ] T1. WorkBlock `posture`, `planned_length_min` in `OMIT_IF_NULL`; migration; pinned CIDs still pass. _(R1)_
- [ ] T2. `DiscomfortCheck` model + admin + corrections. Tests. _(R2)_
- [ ] T3. `mini_puzzle` probe kind; `Reset` model with CID-reference validation + admin. Tests. _(R3, R4)_
- [ ] T4. `WeeklyCheck` model + admin. Tests. _(R8)_
- [ ] T5. `twin_metrics/zone.py` with the R10 synthetic tests. _(R5–R7)_
- [ ] T6. `zone_report` service + command (text and `--json`), stop signals first. Tests on a seeded DB. _(R9)_
- [ ] T7. README: logging work blocks, discomfort checks, resets and the weekly check; reading the zone report.
- [ ] T8. Full suite in Docker; push branch, open PR, CI green; M3 Status in DECISIONS with test count and run URL.
