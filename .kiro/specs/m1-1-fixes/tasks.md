# M1.1 Fixes — Tasks

- [x] T1. Run the full suite yourself (`docker compose exec web pytest`); record the actual count in DECISIONS Status before changing anything.
- [x] T2. Add `LICENSE` (official AGPL-3.0 text, unmodified) and SPDX line in README. Closes M1-T0. _(F1)_
- [x] T3. Supersession table replacing the `supersedes` FK; shared current-record helper; revert and no-op tests. _(F2)_
- [x] T4. Move the current-per-date lock/check into `DailySnapshot.save()`; direct-save rejection test. _(F3)_
- [x] T5. `Contributor.timezone`; bedtime/wake_time as aware datetimes; date = wake local date; UTC before hashing; naive rejected. Tests. _(F4)_
- [x] T6. Post-sauna field set incl. weight_kg; new bounds; non-finite/out-of-range → ValidationError. Tests. _(F5)_
- [ ] T7. Admin "Save as correction" for ProbeSession and WorkBlock. Tests. _(F6)_
- [x] T8. Make README, compose and DECISIONS agree on fail-closed `.env`. _(F7)_
- [ ] T9. Run the full suite, record the count; mark Kiro's M1 task state done with a verification entry; write M1.1 Status in DECISIONS. _(F7)_
