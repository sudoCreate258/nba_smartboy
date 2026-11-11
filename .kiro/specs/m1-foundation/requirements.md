# M1 Foundation + Provenance — Requirements

## Goal
A local Docker stack that stores the owner's daily biometrics, probe sessions
and work blocks as immutable, CID-keyed records tied to a contributor,
ingests biometric YAML, and passes tests in CI. (Nymbus phase 1, layers:
capture + provenance.)

## User stories and acceptance criteria

### R1 Local runtime
As the owner, I want one command to start the system.
- WHEN `docker compose up -d --build` runs THEN web (Django) and db (PostgreSQL) start healthy.
- WHEN I open http://localhost:8000/admin THEN I can log in with a superuser.
- Secrets come from `.env`; `.env.example` documents every variable.

### R2 Contributor
- A `Contributor` has a unique handle. A data migration creates `mike`.
- Every record references exactly one contributor.

### R3 Provenance (CID)
- Every record (R4–R6) gets a CID computed from its canonical content:
  record kind + contributor handle + domain fields. Ingest metadata (file
  name, ingest time) is excluded.
- Same content → same CID; any change in content → different CID.
- Records are immutable: updating a saved record raises an error.
- A correction is a new record whose `supersedes` points at the old one.
  The "current" record for a key (e.g. a date) is the one not superseded.

### R4 Daily snapshot
- Fields: date, sleep_score, bedtime, wake_time, sleep_duration_min,
  resting_hr_sleep, hrv, spo2, weight_kg, body_fat_pct, skeletal_muscle_kg,
  bmr_kcal, bia_timing (pre_session | post_sauna | unknown), source
  (samsung_health | seca | manual), notes.
- All metric fields nullable; nothing is auto-filled.
- WHEN bia_timing = post_sauna AND any body-composition field is set THEN
  validation fails.
- At most one current (non-superseded) snapshot per contributor per date.

### R5 Probe session
- Fields: started_at, kind (puzzle_set | rapid_game | module), time_control,
  n_items, accuracy_pct, median_solve_s, blunders, late_blunders,
  fast_blunders, opponent_rating, own_rating, location (office | remote |
  other), notes.

### R6 Work block
- Fields: start, end, task_type (code | meeting | admin | study | other),
  location (office | remote | commute), interruptions, absorption (1–5),
  effort (1–5), notes.
- Duration is derived, never stored. end must be after start.

### R7 YAML ingest
- `python manage.py ingest_yaml <path> [--contributor mike]` ingests DailySnapshots.
- Unknown keys → error listing them; the whole file is rolled back.
- A record whose CID already exists is skipped (idempotent re-ingest).
- A new CID for a date that already has a current snapshot creates a new
  record superseding it.
- Output: counts of created / skipped / superseded, and each new CID.

### R8 Quality gate
- pytest covers: CID determinism and change-sensitivity, CID format,
  immutability, supersede chain, post-sauna rule, work-block validation,
  ingest happy path, unknown-key rollback, idempotent re-ingest.
- GitHub Actions runs tests on push and pull request.
