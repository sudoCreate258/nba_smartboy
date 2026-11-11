# M1.1 Fixes — Requirements

Applies the owner/planner answers recorded on 2026-11-11 in `docs/DECISIONS.md`
("Owner/planner answers to the M1 builder questions"). Read that section first.
Nothing here adds product features; M2 starts after this is green.

### F1 License
- `LICENSE` contains the unmodified AGPL-3.0 text from gnu.org.
- README states `SPDX-License-Identifier: AGPL-3.0-or-later`; new source files carry the SPDX line.

### F2 Supersession events
- `supersedes` FK replaced by append-only `Supersession(old_cid, new_cid, contributor, reason, created_at)`.
- Current record = most recent `new_cid`; works for DailySnapshot, ProbeSession and WorkBlock.
- A -> B -> A: re-ingesting A while B is current records Supersession B -> A; A becomes current; no new record row.
- Re-ingesting the current record is a no-op.

### F3 Single write path for snapshots
- `DailySnapshot.save()` enforces one current snapshot per contributor per date under the contributor-row lock. A direct save that would create a second current snapshot fails.

### F4 Time handling
- `Contributor.timezone` (default `America/New_York`).
- bedtime and wake_time are timezone-aware datetimes; `date` = wake_time's local date.
- Offset-less times in YAML are interpreted in the contributor's time zone; all datetimes are UTC before hashing; naive datetimes are rejected at the model layer.

### F5 Validation
- Post-sauna rule blocks weight_kg, body_fat_pct, skeletal_muscle_kg, bmr_kcal.
- Added bounds: weight_kg 30–300, resting_hr_sleep 20–150, hrv 0–300.
- Non-finite or out-of-range numbers raise a validation error with the field name; ingest rolls back the file.

### F6 Corrections for probes and work blocks
- Admin "Save as correction" for ProbeSession and WorkBlock, recording a Supersession.

### F7 Consistency and verification
- README, compose and DECISIONS agree on `.env` being required (fail-closed).
- Builder runs the full suite itself and records the real test count.
- Kiro task state for M1 (`.agents/tasks/task-m1-foundation/task.json`) is marked done with a verification entry (command run, test count, date).

### Acceptance
New tests for: revert A->B->A, no-op re-ingest of current, direct-save rejection, after-midnight bedtime dated to the wake day, offset-less time -> UTC CID stability, `1e30`/`nan` -> validation error, post-sauna weight rejection, probe/work-block correction. Full suite green in Docker.
