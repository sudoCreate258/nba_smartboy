# Decision log (planner <-> builder)

## Decided
- 2026-11-11 — Planner (Claude chat) owns steering/specs; Kiro builds and runs locally. Files in the repo are the interface.
- 2026-11-11 — Build local-first and get it running before any Buy Me a Coffee, cloud deploy or sharing work.
- 2026-11-11 — M1 stack: Django + PostgreSQL in Docker Compose; Django admin is the M1 data-entry UI.
- 2026-11-11 — Post-sauna BIA readings rejected.
- 2026-11-11 — Nymbus is the underlying architecture and this repo is its first use case. Source of truth: "Nymbus — Reference Architecture" doc; constraints copied into `.kiro/steering/nymbus.md`. This repo is in Nymbus phase 1.
- 2026-11-11 — M1 now includes provenance: contributor on every record, CIDv1 (sha2-256, raw codec over canonical JSON), immutable records, corrections via `supersedes`.
- 2026-11-11 — Milestones re-cut to fit Nymbus phase 1: M5 = simulated payout ledger (closes the phase 1 gate); hardening moves to M6.
- 2026-11-11 — Ingestion is adapter-based: screenshot-parser YAML now, direct exports/APIs as later adapters.

## Open
- Builder (M1-T6): "body-composition field" for the post-sauna rule is taken as body_fat_pct, skeletal_muscle_kg and bmr_kcal. weight_kg and spo2 are not blocked. Confirm or widen.
- Builder (M1-T6): reverting to values whose CID already exists (A -> B -> A) is skipped as a duplicate (R7), so B stays current. If a revert should be allowed, the CID would need to include `supersedes` or a revision marker.
- Builder (M1-T6): numeric types chosen (not in spec): hrv, sleep_score, resting_hr_sleep, bmr_kcal as integers; spo2, weight_kg, body_fat_pct, skeletal_muscle_kg as Decimal with 1 decimal place (values are quantized before hashing so 97.8 and 97.80 share a CID). bedtime/wake_time are TimeField (no date).
- Builder (M1-T4): timezone-aware datetimes are converted to UTC before hashing; naive datetimes and dates are hashed as written.
- Builder (M1-fix): range bounds not in spec, chosen: sleep_score, spo2, body_fat_pct, accuracy_pct 0-100; sleep_duration_min <= 1440; late_blunders and fast_blunders <= blunders. Confirm or adjust.
- Builder (M1-fix): one-current-snapshot-per-date is enforced by locking the contributor row in ecord_snapshot, not by a DB constraint (a constraint needs a denormalized "is current" column). Direct DailySnapshot.save() still bypasses the rule. Revisit if concurrent writers appear.
- Builder (M1-fix): immutability is enforced in save(), delete() and the queryset (update, ulk_update, delete). Raw SQL, ulk_create of new rows and _raw_delete are not blocked; a DB trigger would be needed for that.
- Builder (M1-fix): settings now fail closed. DJANGO_DEBUG defaults to off, DJANGO_SECRET_KEY is required unless debug, no DB password fallback, compose requires .env and publishes 8000 on 127.0.0.1 only. An existing dev DB volume keeps the password it was created with, so the local .env must match it.
- Builder (M1-fix): ProbeSession and WorkBlock still have no admin correction flow (supersede path); not in the M1 spec, deferred.
- License: Apache-2.0 vs AGPL-3.0 (owner). Planner recommends AGPL-3.0 for the app.
- CID codec: M1 uses raw (0x55) over canonical JSON. AT Protocol uses dag-cbor (0x71). Switch before phase 2 if Nymbus needs CIDs that interoperate with AT Protocol tooling.
- Storage direction: Nymbus phase 2 says central storage under HIPAA-style controls; the owner also wants small, user-run instances with client-side encrypted group backups. Resolve in the Nymbus doc before phase 2.
- Payout: the Nymbus doc says contributors get paid in cryptocurrency; the owner also wants the project free to the public and run by a co-op/nonprofit. M1–M5 use simulated units only.
- Source material (white papers, fitness AI venture brief, `digital-twin.jsx`, CS questions specs) to be added to `docs/`.

## Status
- M1: shipped, pending owner license decision (T0). T1-T10 done.
  - Shipped: Docker Compose stack (Django 5.2 + PostgreSQL 16), `core` app with Contributor (`mike` data migration), immutable ProvenancedRecord with CIDv1 and supersede chain, DailySnapshot (read-only admin, "Save as correction", post-sauna rule), ProbeSession, WorkBlock, `ingest_yaml` command (atomic, CID skip, supersede), GitHub Actions CI (postgres service, pytest). 59 tests pass via `docker compose exec web pytest`.
  - Issues: T0 license is pending, so no `LICENSE` file has been added. The README CI badge uses placeholder `OWNER/REPO` and must be updated once the GitHub remote exists. CI workflow has not run yet (no remote), so it is unverified on GitHub. Docker: `.env` is optional in compose (`required: false`) and defaults fall back to `twin`; `.env.example` uses `change-me` values.
  - Open questions for the planner: the four builder items in Open above (post-sauna field set, A -> B -> A revert handling, numeric types, UTC normalization), plus the license choice.
