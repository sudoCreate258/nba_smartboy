# M3.5 Training Log — Requirements

## Goal
Log strength and conditioning sessions in a shape that matches Renaissance
Periodization (RP) style programming, so training load can be read next to
sleep, probes, zone and discomfort. Priority 1 of the product is joint
durability, so joint pain is captured per set.

### R1 TrainingSession (record, CID)
- Fields: started_at, ended_at (optional), program (free text, e.g. "RP Hypertrophy"),
  mesocycle (free text), meso_week (int ≥ 1), is_deload (bool), location
  (gym | home | other), session_rpe (0–10, optional), notes.

### R2 TrainingSet (record, CID)
- Fields: session_cid (CID of a current TrainingSession of the same
  contributor), order (int ≥ 1), exercise (free text, normalized to lower
  case and trimmed before hashing), muscle_group (choices: chest, back,
  shoulders, biceps, triceps, quads, hamstrings, glutes, calves, abs,
  forearms, full_body, other), load_kg (Decimal 1 dp, ≥ 0, optional),
  reps (int ≥ 0), rir (reps in reserve, 0–10, optional), pump (0–3,
  optional), soreness_before (0–3, optional), joint_pain (0–3, optional),
  joint_pain_area (choices as DiscomfortCheck.area, optional), notes.
- joint_pain ≥ 2 is a stop signal surfaced first in reports, same wording as discomfort.

### R3 CSV import adapter
- `python manage.py ingest_training_csv <path> [--contributor mike]`:
  one row per set with session columns repeated; sessions grouped by
  started_at; atomic per file; unknown columns rejected; idempotent by CID.
- Document the CSV columns in the README with a sample file in `tests/fixtures/`.

### R4 Training report
- `python manage.py training_report [--weeks 4] [--json]`: per local week,
  hard sets per muscle group (sets with rir ≤ 3 or rir missing), total
  tonnage (load × reps), mean RIR, deload weeks marked, joint-pain sets by
  area, and stop signals first. "Load gauge, not a medical assessment."
- Statistics in plain Python (`twin_metrics/training.py`), unit-tested.

### R5 Admin
- Admin for both models with "Save as correction"; inline sets under a session.

### R6 Quality gate
- Tests: CID stability (exercise normalization), session reference validation,
  CSV import (happy path, unknown column rollback, idempotent re-import),
  report statistics, stop signal surfacing. Existing pinned CIDs unchanged.
  Full suite green in Docker and CI.
