# M2 Probe Log — Tasks

- [x] T0. Housekeeping (R0): record_snapshot validation order, admin bad-supersedes form error, SPDX on 0008, DST rejection, renormalize line endings, `.agents/` in `.gitignore`. Tests for each code fix. Push `main`; confirm the GitHub Actions run is green and record its URL in DECISIONS Status.
- [ ] T1. Canonicalization rule for new nullable fields (design "Data"); test that existing CIDs are unchanged. Decision written to DECISIONS.
- [ ] T2. `ProbeSession.move_time_cv` + migration + admin. _(R1)_
- [ ] T3. `ProbeBaseline` model + admin; default-window logic. _(R2)_
- [ ] T4. `twin_metrics/probes.py` with the full synthetic-series unit tests. _(R2–R4, R6)_
- [ ] T5. Sleep-falling and work-rising conditions in the service layer, incl. insufficient-data handling. Tests. _(R4)_
- [ ] T6. `probe_report` command (text + `--json`). Tests on a seeded database. _(R5)_
- [ ] T7. README section: how to log probes, set a baseline, read the report.
- [ ] T8. Full suite in Docker and on GitHub Actions; write M2 Status in DECISIONS (test count, run URL, open questions).
