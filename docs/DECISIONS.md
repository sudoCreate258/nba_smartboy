# Decision log (planner <-> builder)

## Decided
- 2026-11-11 — Planner (Claude chat) owns steering/specs; Kiro builds and runs locally. Files in the repo are the interface.
- 2026-11-11 — Build local-first and get it running before any Buy Me a Coffee, cloud deploy or sharing work.
- 2026-11-11 — M1 stack: Django + PostgreSQL in Docker Compose; Django admin is the M1 data-entry UI.
- 2026-11-11 — Nymbus is the underlying architecture and this repo is its first use case. Source of truth: "Nymbus — Reference Architecture" doc; constraints copied into `.kiro/steering/nymbus.md`. This repo is in Nymbus phase 1.
- 2026-11-11 — M1 includes provenance: contributor on every record, CIDv1 (sha2-256, raw codec over canonical JSON), immutable records, corrections create new records.
- 2026-11-11 — Milestones re-cut to fit Nymbus phase 1: M5 = simulated payout ledger (closes the phase 1 gate); hardening moves to M6.
- 2026-11-11 — Ingestion is adapter-based: screenshot-parser YAML now, direct exports/APIs as later adapters.

### Owner/planner answers to the M1 builder questions (2026-11-11)
- **License: AGPL-3.0-or-later** (owner). `LICENSE` = the official text from https://www.gnu.org/licenses/agpl-3.0.txt, unmodified. Add `SPDX-License-Identifier: AGPL-3.0-or-later` to the README and to new source files.
- **Post-sauna rule blocks:** weight_kg, body_fat_pct, skeletal_muscle_kg, bmr_kcal. Weight is included because sauna fluid loss skews it. spo2 and sleep/HR fields are not blocked.
- **CID stays pure content** (same content = same CID, always). No revision marker in the hash: dedup and payout depend on it.
- **Reverts (A -> B -> A):** allowed, as an event, not a new record. Replace the `supersedes` FK with an append-only `Supersession(old_cid, new_cid, contributor, reason, created_at)` table. "Current" = the record most recently pointed to as `new_cid` (or the only record if none). Re-ingesting A while B is current records a Supersession B -> A. Exact re-ingest of the current record is still a no-op.
- **One current snapshot per date:** one write path. `DailySnapshot.save()` itself takes the contributor-row lock and runs the current-per-date check, so direct saves cannot bypass it. A DB trigger is deferred to M6.
- **Numeric types:** accepted (integers: hrv, sleep_score, resting_hr_sleep, bmr_kcal; Decimal 1 dp: spo2, weight_kg, body_fat_pct, skeletal_muscle_kg; quantize before hashing).
- **bedtime / wake_time:** change to timezone-aware DateTimeField. A 01:30 bedtime belongs to the previous evening's night; a TimeField loses that. `date` = calendar date of wake_time in the contributor's time zone.
- **Time zones:** naive datetimes are never hashed. Ingest interprets offset-less times in the contributor's time zone (add `Contributor.timezone`, default `America/New_York`), then converts to UTC before hashing. Plain dates are hashed as written.
- **Range bounds:** accepted, plus weight_kg 30–300, resting_hr_sleep 20–150, hrv 0–300. Out-of-range or non-finite numbers (e.g. `1e30`, `nan`) raise a validation error, never a raw `decimal.InvalidOperation`.
- **Immutability below the ORM** (raw SQL, bulk_create, _raw_delete): DB trigger deferred to M6.
- **Correction flow for ProbeSession and WorkBlock:** needed before M2 (M2 depends on probes). In M1.1.
- **Fail-closed settings:** accepted. The M1 Status text says `.env` is optional with `twin` fallbacks, which contradicts this; make README, compose and this log agree.

### Contributors and payouts (owner, 2026-11-11)
- Phase 1–3 users contribute **data, not code**: they run a local instance and opt in to sharing with the cooperative's edge servers for backup and federated training.
- **Code contributions open at the worker co-op stage.** DCO (`git commit -s`) for any code accepted before then; a CLA only once the co-op is a legal entity and is the party receiving the rights.
- **Data contributions** are governed separately: a data contribution agreement / co-op membership terms (what is shared, for what purposes, withdrawal, dividend formula), per-study informed consent (IRB) for any clinical-trial participation, and a data license (e.g. CDLA) for any shared datasets.
- **Payout experience:** usage dividends ("Time Coin") arrive like a recurring direct deposit. Contributors keep control: they see which of their data and media generated usage, choose per category what may be used, and can change that at any time. Shapes M5 (see product steering). Real payouts stay behind the Nymbus phase 4 legal gate.

### Planner answers to the M1.1 builder choices and review (2026-11-11)
- Accepted: `date` validated against the wake_time local date (explicit `date` stays required in YAML); `save(supersede=True)` as the correction path; Supersession stores plain CID strings (CID is the cross-layer key in Nymbus, so no FK); incremental migrations 0006–0008.
- Review fixes go in M2-T0 (housekeeping) before probe work:
  - `record_snapshot` validates before hashing; a naive datetime raises ValidationError.
  - Admin "Save as correction" with a bad `supersedes` value shows a form error, not a 500.
  - SPDX header on `0008_validation_bounds.py`.
  - DST: ambiguous or nonexistent local times are rejected with a ValidationError naming the field (no silent pick). Provenance beats convenience.
  - Line endings: `git add --renormalize .` so the repo is LF everywhere, per `.gitattributes`.
  - `.agents/` (Kiro task state and reviews) is added to `.gitignore`. `docs/DECISIONS.md` stays the shared record; summarize review findings there.
- Push: yes. Push `main` (after M2-T0) and confirm the first GitHub Actions run is green before M2-T1. Record the run URL in Status. Note: `.git/refs/remotes/origin/main` already exists locally, so check what (if anything) was pushed earlier.
- Process: combined commits are fine when edits overlap; say so in the message.

### Canonicalization of new nullable fields (builder, M2-T1, 2026-11-11)
- Chosen: a per-model `OMIT_IF_NULL` tuple on `ProvenancedRecord`. A field listed there is left out of the canonical content while its value is null, and included once set. Fields that existed at creation (all current ones) are not listed, so every existing CID is unchanged.
- Rejected: omitting all null fields for every record. It would re-hash every stored record (all have some nulls) and break existing CIDs.
- Rule for later milestones: any nullable field added after records exist must be added to `OMIT_IF_NULL` in the same migration PR. Tests pin two pre-M2 ProbeSession CIDs (`tests/test_canonicalization.py`).
### Sleep and work conditions (builder, M2-T5, 2026-11-11)
- Choices the spec left open. Owner or planner may overrule; the code is in `core/services/probe_report.py`.
- Sleep falling uses the 3 local days ending on the day of the latest session of that kind. All 3 need a current `sleep_score`, otherwise the condition is "insufficient data". Baseline nights are current snapshots dated inside the baseline window; SD is the sample SD of their scores (needs 2 nights and SD > 0).
- Work rising: hours of current WorkBlocks overlapping the 3 local days ending on the latest session day (blocks are clipped to the window, so midnight-crossing blocks split by local day). Baseline totals are every 3-day window inside the baseline window that holds at least one block. No blocks in the recent 3 days, or fewer than 2 baseline windows with varying totals, is "insufficient data". A day without blocks is never read as zero hours on its own.
- "Latest session" is the latest current session of the kind being reported.
## Open
- CID codec: raw (0x55) over canonical JSON now. AT Protocol uses dag-cbor (0x71). Decide before Nymbus phase 2.
- Storage direction: Nymbus phase 2 says central storage under HIPAA-style controls; the owner also wants small, user-run instances with client-side encrypted group backups. Resolve in the Nymbus doc before phase 2.
- Payout: the Nymbus doc says contributors get paid in cryptocurrency; the owner also wants the project free to the public and run by a co-op/nonprofit. M1–M5 use simulated units only.
- Source material (white papers, fitness AI venture brief, `digital-twin.jsx`, CS questions specs) to be added to `docs/`.
- GitHub remote: `sudoCreate258/nba_smartboy` (private). README badge updated; CI has not run on GitHub yet until the first push.

## Status
- M1: built (T1–T10). T0 decided (AGPL-3.0-or-later). Baseline verified at M1.1 start: `docker compose exec web pytest` ran 76 passed (earlier figures of 59 and 76 were unverified).
- M2: spec written (`.kiro/specs/m2-probe-log/`). Not started.
- M1.1: built (T1-T9, spec `.kiro/specs/m1-1-fixes/`). Verified 2026-11-11: `docker compose exec web pytest` ran 138 passed; `makemigrations --check` reports no changes. Corrections for DailySnapshot, ProbeSession and WorkBlock all record a Supersession. Not pushed; CI has not run on GitHub yet.
