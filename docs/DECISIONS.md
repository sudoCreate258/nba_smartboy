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
- License: Apache-2.0 vs AGPL-3.0 (owner). Planner recommends AGPL-3.0 for the app.
- CID codec: M1 uses raw (0x55) over canonical JSON. AT Protocol uses dag-cbor (0x71). Switch before phase 2 if Nymbus needs CIDs that interoperate with AT Protocol tooling.
- Storage direction: Nymbus phase 2 says central storage under HIPAA-style controls; the owner also wants small, user-run instances with client-side encrypted group backups. Resolve in the Nymbus doc before phase 2.
- Payout: the Nymbus doc says contributors get paid in cryptocurrency; the owner also wants the project free to the public and run by a co-op/nonprofit. M1–M5 use simulated units only.
- Source material (white papers, fitness AI venture brief, `digital-twin.jsx`, CS questions specs) to be added to `docs/`.

## Status
- M1: not started.
