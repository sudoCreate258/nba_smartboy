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
### Planner answers to the M2 builder questions (2026-11-11)
- `OMIT_IF_NULL` rule: accepted. It is now a standing rule for every later migration (see `.kiro/steering/nymbus.md`).
- Sleep and work windows: accepted as written. "A day without blocks is never read as zero" is right: missing data is not rest.
- Multiple `ProbeBaseline` rows: newest `frozen_at` wins, older rows kept as history. Accepted.
- `move_time_cv`: ratio (std/mean of seconds per move), 2 dp. Accepted; label the admin column "ratio".
- Default baseline spanning months: not accepted. A default baseline is used only if its 10 sessions fall within 42 days; otherwise the kind reports "insufficient baseline: set a ProbeBaseline". In M3-T0.
- Parallel pytest runs share the test DB: run one at a time; CI runs one. No change needed.
- Push order (owner or Kiro orchestrator): push `main` (M1 + M1.1), confirm CI green; then push `feature/m2-probe-log`, open a PR, CI green, merge. Record both run URLs in Status.

### Planner answers on branches, PRs and release (2026-11-11)
- Branch model accepted: `feature/*` and `chore/*` -> `develop` (via PR, CI green) -> `main` (release, owner confirms each one). The M2 "push `main` first" instruction is superseded.
- Merge order: #1 (M1.1) into `develop`. Then run the semantic review on #3 (M2), as M1 and M1.1 had, fix any blocking findings, merge #3. #2 merges only after its fixes below.
- #2 community docs, required before merge:
  - Replace `CODE_OF_CONDUCT.md` with the official Contributor Covenant 2.1 text, copied from contributor-covenant.org, not written from memory. Same rule as `LICENSE`: canonical texts are copied, never retyped.
  - `CONTRIBUTING.md` must match the contributor decision above: outside code contributions are not open until the worker co-op stage; any code accepted before then needs a DCO sign-off (`git commit -s`); add the DCO text (developercertificate.org) as `DCO`. Data contributions are not covered by CONTRIBUTING.
- Release: after #1, #2 and #3 are in `develop`, merge `develop` -> `main` and tag `v0.2.0` (M1 + M1.1 + M2). Owner confirms before the merge.
- GitHub settings (owner): make `develop` the default branch; protect `main` and `develop` (PR required, CI check required, no force push).
- This section and `.kiro/specs/m3-work-zone/` go in one commit on `chore/planner-decisions` off `develop`, merged before #1.
- Merge style: merge commits (no squash), so the `M<n>-T<k>` history stays; delete branches after merge.
- Planner edits in the working tree: the planner writes only `docs/DECISIONS.md` and `.kiro/`. The builder commits them in a separate commit `planner: <summary>` before its own work, never with `git commit -a`. The swept-in edits in `8ae1479` are intended and can stay.

### Planner answers to the M2 review (2026-11-11)
- "ratio" label on the `move_time_cv` admin column: add in M3-T0.
- Overlapping WorkBlocks: validation rejects a WorkBlock that overlaps another current WorkBlock of the same contributor (touching end == start is fine). Work-hours sums also merge overlapping intervals as a guard. Tests for both, in M3-T0.
- Rolling medians with fewer than 3 sessions: keep as is (flags already need 3 scored sessions); add one test that documents it, in M3-T0.

## Open
- CID codec: raw (0x55) over canonical JSON now. AT Protocol uses dag-cbor (0x71). Decide before Nymbus phase 2.
- Storage direction: Nymbus phase 2 says central storage under HIPAA-style controls; the owner also wants small, user-run instances with client-side encrypted group backups. Resolve in the Nymbus doc before phase 2.
- Payout: the Nymbus doc says contributors get paid in cryptocurrency; the owner also wants the project free to the public and run by a co-op/nonprofit. M1–M5 use simulated units only.
- Source material (white papers, fitness AI venture brief, `digital-twin.jsx`, CS questions specs) to be added to `docs/`.
- GitHub remote: `sudoCreate258/nba_smartboy` (private). README badge updated; CI has not run on GitHub yet until the first push.

## Status
- M3: spec written (`.kiro/specs/m3-work-zone/`). Not started; starts after the M2 PR is merged.
- M1: built (T1–T10). T0 decided (AGPL-3.0-or-later). Baseline verified at M1.1 start: `docker compose exec web pytest` ran 76 passed (earlier figures of 59 and 76 were unverified).
- M2: built (T0-T8, spec `.kiro/specs/m2-probe-log/`). Verified 2026-11-11: `docker compose exec web pytest` ran 209 passed (M1.1 baseline was 138); `makemigrations --check --dry-run` reports no changes. GitHub Actions run: https://github.com/sudoCreate258/nba_smartboy/actions/runs/43067143291.
  - Shipped: T0 housekeeping (admin bad `supersedes` is a form error, DST ambiguous/nonexistent ingest times rejected, SPDX on 0008, `.agents/` ignored); `OMIT_IF_NULL` canonicalization rule with pinned pre-M2 CIDs; `ProbeSession.move_time_cv` (migration 0009); `ProbeBaseline` (migration 0010, no CID); `twin_metrics/probes.py` (plain Python statistics); sleep and work conditions and `kind_report` in `core/services/probe_report.py` (`core/services.py` became the `core/services/` package, imports unchanged); `probe_report` command (text and `--json`); README section.
  - T0 deviations: `git add --renormalize .` changed nothing (the repo was already LF in the index and working tree). The T0 push of `main` and the first-CI confirmation are done by the orchestrator, not by the builder.
  - Already correct, tests added only: `record_snapshot` already validated before hashing, so a naive datetime already raised ValidationError.
  - Open questions for the planner: (1) sleep and work window rules in "Sleep and work conditions" above; (2) multiple `ProbeBaseline` rows per kind: newest `frozen_at` wins, older ones are kept as history; (3) `move_time_cv` is stored as a ratio with 2 decimals (max 999.99), not a percent; confirm the unit; (4) the default baseline is the first 10 sessions even if they span months.
- M1.1: built (T1-T9, spec `.kiro/specs/m1-1-fixes/`). Verified 2026-11-11: `docker compose exec web pytest` ran 138 passed; `makemigrations --check` reports no changes. Corrections for DailySnapshot, ProbeSession and WorkBlock all record a Supersession. Not pushed; CI has not run on GitHub yet.
