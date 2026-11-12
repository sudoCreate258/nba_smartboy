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

### Owner decisions: alignment with Techno Rave (#0.1) and the Nymbus Program deck (2026-11-11)
Program map: Nymbus Program Phase 1 "Techno Rave" (liftoff: capture, store, analyze, share) = Nymbus architecture phases 1–3; Program Phase 2 "Tree Hugger" (LLC -> nonprofit, modules and shared data, edu material, homestead DIY); Program Phase 3 "Piggy Bank" (user revenue share, memberships, licensing, shared live feed) = Nymbus phase 4+.
- **Data domain:** fitness first. "Dropped data" was Techno Rave framing, not a requirement. Fitness data is concrete (wearables, smart devices, later camera-based posture). Phone app-usage capture can return later as an adapter.
- **Storage:** Google Drive / Google Cloud is not the default. Local PostgreSQL stays. The getting-started guide stays stack-agnostic ("choose your own stack"): adopters may finish setup with their preferred tools and document what they used. The "our data" boundary must not depend on any local stack choice, so a stable interchange contract (record format, CID, encryption) is required before Nymbus phase 2.
- **CI:** GitHub Actions replaces Travis CI. Close enough to plan.
- **Client:** phone-friendly web app (installable, works on older phones) in M4; Flutter later; keep both doors open. Hardware targets include repurposed old phones and a Raspberry Pi as a mobile mini edge server.
- **Resilience principle:** the twin must work fully offline on low-power local hardware (no internet, no cloud dependency). Decentralized, locally maintainable.
- **Privacy and sharing:** the Nymbus approach (federated learning + differential privacy, client-side encryption before anything leaves the device). Not homomorphic encryption.
- **Rendez-Vous:** parked until the fitness MVP is set up; then built in parallel. Fitness and Rendez-Vous are the first two marketplace modules.
- **Camera posture tracking:** future adapter. Use an open-source pose-estimation library with a license compatible with AGPL (to be confirmed per library); video/images never leave the device and are not stored by default, only derived skeleton keypoints.
- **Renaissance Periodization:** a partnership goal (form, nutrition, plateau tracking), not a code dependency. No public RP API is known.
- **Revenue model (direction, not built):** free for users who participate in an anonymous docuseries/user-story program; user setup stories market the project; early adopters get a "stake" and rewards (Time Coin; shared-commute-as-a-service idea parked). Anything involving stakes, tokens or rewards stays behind the Nymbus phase 4 legal review. "Anonymous" and "docuseries" need a definition before launch (filmed people are identifiable), and free access tied to participation must not be tied to research consent.
- **Governance (direction):** a nonprofit runs a worker co-op. The co-op arm generates revenue from members' skills democratically; the nonprofit holds surplus, which members and affected communities debate. Exact structure depends on revenue scale; legal review before filings. Lion13 Software, LLC (NY) will need updated paperwork before receiving funding.
- **Funding:** NSF PESOSE after there are more users. NSF SBIR Project Pitch and NLnet remain candidates.

### Owner decisions: anonymity, consent and legal timing (2026-11-11)
- **Development is not slowed by legal work.** Legal steps are checkpoints tied to milestones, not prerequisites for coding.
- **Participant identity:** participants are referred to only by codes (study/trial #NNN, region #XXX). Codes are pseudonymous, not anonymous, so: no names, faces, voices or exact dates in any public material; public numbers are aggregates with at least 10 people per reported group (smaller groups are merged or suppressed).
- **Marketing media:** commercials and the docuseries use hired actors or animation (e.g. claymation) dramatizing aggregated before/after experiences. Every piece states it is a dramatization with actors and that results vary; no actor is presented as a real participant.
- **Consent:** framed as ethical AI use, in plain language: per-category, opt-in, revocable at any time (M5 permissions), shown before any data leaves the device, and never a condition of free access. A research use by an institution adds that institution's own consent and ethics review.
- **Wording:** call it a "pilot" or "user study" publicly until an institutional partner with an ethics board (IRB) runs it; "clinical trial" is used only then.
- **Legal checkpoints (owner gates):**
  1. Before the first user other than Mike stores data on a shared server (Nymbus phase 2): privacy notice, consent flow, breach-notification plan.
  2. Before accepting money beyond small tips (grants, sponsorships, revenue): entity paperwork for Lion13 Software, LLC; tips reported as income.
  3. Before any "clinical trial" use: institutional partner + IRB.
  4. Before stakes, tokens or rewards with monetary value: Nymbus phase 4 legal review.

### Owner direction: "our data" transition and the Coding Village institution (2026-11-11)
- Source: "Coding Days" deck (SUNY Orange Computer and Technology Department, dev group). The institution that runs "our data" is a Coding Village: ranks Genin -> Chunin -> Jounin/ANBU -> Kage (Hokage); Power Groups (Communication, Source Code, Hardware, and mixed Purple/Orange/Green).
- **The twin is the entry project.** Path to Genin requires implementing a self-tracking open-source project; Chunin registration includes a proxy to the participant's self-tracking software, tested yearly against software updates. So the getting-started guide doubles as the Genin curriculum, and "choose your own stack" setups are part of the evaluation.
- **Hokage runs a local OurData server** and must exchange and host backups with at least two other Hokage. This defines the transition step.
- **P1.5 "OurData backup" (between Nymbus phase 1 and 2):**
  - A member's instance encrypts its "my data" export (M4) on the device and sends it to their village's OurData server.
  - The OurData server stores ciphertext only and cannot read it; it replicates the ciphertext to at least two peer OurData servers.
  - Restore works on a fresh instance with the member's key; CIDs are identical after restore.
  - No analysis, sharing or payout on the server in P1.5 (that is Nymbus phase 2+).
  - Prerequisites: M4 export format, M6 HTTPS and signed images. Legal checkpoint 1 applies (privacy notice, consent, breach plan), because other people's data, even encrypted, sits on a shared server.
- **Fit with existing milestones:** Coding Days scenario 4 (ergonomic, skeletal and visual strain from heavy computer use) is what M3 measures.
- **Points that need owner decisions before Nymbus phase 2 (recorded, not decided):**
  1. The deck's base-rate model sells and loans anonymized usage data, demographic information and testimonials to third parties, priced by user demographic. This conflicts with the per-category, revocable consent decided earlier and with avoiding demographic data. Selling health data also triggers stricter privacy laws.
  2. "Attention stock market" falls under the Nymbus phase 4 legal review.
  3. Rank-based approval (Kage approves contracts) vs the worker co-op's democratic model: define which decisions are democratic and which are delegated.
  4. Health insurance for Chunin implies an employer: decide which entity employs members.
  5. "Kickback" to host governments: call it a revenue share with host communities and define it in the governance documents.

### Owner direction on village governance (2026-11-11)
- **Data sales happen at village level, not centrally.** A village (local) that sells data has more agency and less hidden resale than a central board (compare local vs state government). Demographic attributes may be used for pricing at village level. Safeguards to design before Nymbus phase 2: each sale approved through the village process, aggregation thresholds (at least 10 people per reported group, as already decided), per-category consent still applies, and a public log of sales per village.
- **Kage as public face.** Decisions are handled by the Kage rather than put to every user directly; ANBU provide internal checks (internal affairs, compliance, security). The path to Hokage builds in data-management duties. The balance between Kage authority and the worker co-op's democratic votes is defined in the governance documents.
- **Health insurance and retirement:** aim to partner directly with physicians and medical professionals so a basic package is a standard minimum for members, not a novelty. Likely easier to pilot in Europe or Canada. Needs legal review per country (legal checkpoint 2).
- **Tag cleanup:** the mistaken `v0.2.0` tag on `73b5e75` is deleted (owner, 2026-11-11).

### M3 builder choices (builder, 2026-11-11)
Choices the spec left open. Owner or planner may overrule.
- **Overlap rule and corrections:** a WorkBlock correction may overlap the block it replaces (the admin passes the source CID through `replaces_cid`, which is not a field and not in the CID). An identical block is a duplicate, not an overlap.
- **42-day default baseline:** measured from the first to the 10th session's `started_at`; exactly 42 days is accepted. A configured ProbeBaseline has no span limit.
- **Zone amber prior weeks:** the 3 calendar weeks right before the week. Each must have work blocks; a week without blocks is missing data, not rest, so the result is "insufficient data". Prior mean share 0 never raises amber.
- **Theta IQR:** inclusive quartiles; one block gives q1 = q3 = median.
- **Reported weeks:** `zone_report` shows the `--weeks` local weeks ending with the week of `--until` (default: today). Discomfort, stop signals and weekly checks are limited to those weeks; zone amber still looks at earlier weeks; reset effect uses all resets up to the end of the window (more data, n < 5 marking still applies).
- **Reset references:** validated at save time (current `mini_puzzle` of the same contributor, before < at < after). In the report a referenced probe that was corrected later is followed to its current version.
- **WeeklyCheck score:** decimal (2 places), because some instruments report a mean rather than a whole-number total; `0 <= score <= scale_max`.
- **mini_puzzle** is a scored kind in `probe_report` like the others (own baseline, same flag rules); `zone_report` lists every kind's probe flag.

### M3 semantic review fixes (builder, 2026-11-11)
Two-model review of PR #6: 19 issues (4 High, 8 Medium, 7 Low); report in `.agents/reviews/` (gitignored). Fixed:
- Reset effect: sample size and "interpretable" are per metric (usable before/after pairs), not per Reset row; `vs none` is marked underpowered unless both sides have n >= 5 (High #1, #4).
- Zone totals and focus minutes use the union of block intervals, so overlapping rows stored before the overlap rule are counted once (High #2).
- Reset probes are resolved through corrections and then rechecked against the Reset's rules (same contributor, `mini_puzzle`, before < at < after); failing or unresolvable resets are listed as excluded and not counted; resets using corrected probes are counted in the output (High #3, Medium #6). Resolution is one in-memory pass (Medium #8).
- `WorkBlock.save()` takes the contributor row lock around the overlap check and insert (Medium #5). Clash messages show local time and zone (Medium #10).
- Stop signals before the reported weeks are counted on one line (Medium #11). `--until` documented as "the whole week containing this date" (Medium #12). The work-block query is bounded to the window plus the 3-week amber lookback (Medium #8).
- Free-text notes are never part of report output, text or JSON (Medium #7). Rule for M4 export: decide separately (export is the user's own data).
- Small: zero-minute weeks are "insufficient data" in amber (#16); the JSON hook raises on unknown types (#17); the probe renderer uses `DEFAULT_BASELINE_N` (#14); tests for falling-hours amber, contributor isolation and midweek `--until` (#19).
Deferred (non-blocking, listed for the planner): a shared write helper for corrections and duplicate checks used by admin and future write paths (#9, before M4 forms); a stable reason code for baseline failures in JSON (#13, before M4); no uniqueness rule for WeeklyCheck per week and instrument (#15); mini_puzzle flagging with about 5 items per session (#18, owner decision).

### M3.5 builder choices (builder, 2026-11-11)
Choices the spec left open. Owner or planner may overrule.
- **Sets reference sessions by CID** (`session_cid`, like Reset), so the admin cannot use a Django inline. The session page shows its current sets in a read-only table with "view / correct" links and an "Add a set to this session" link that prefills the session CID.
- **Corrected sessions:** sets keep the old session CID; reports follow the supersession chain to the current session (same in-memory resolver as resets). New sets must reference a current session.
- **Set order** is unique among current sets of a session (a correction may reuse the order of the set it replaces; an identical set is a duplicate, skipped on import).
- **Exercise normalization:** lower case, trimmed, and inner whitespace collapsed ("Bench  Press" = "bench press").
- **Optional fields:** `program`, `mesocycle`, `meso_week`, `location`, `session_rpe` (decimal, 1 place), `load_kg` (empty = bodyweight, tonnage 0), `rir`, `pump`, `soreness_before`, `joint_pain`, `joint_pain_area`. `reps` capped at 1000.
- **CSV:** required columns `started_at`, `order`, `exercise`, `muscle_group`, `reps`; other header columns may be left out (treated as empty); columns in any order; unknown columns rejected; UTF-8 with or without BOM; blank rows skipped; choice values lower-cased; rows of one session (same `started_at` + `program`) must agree on the session columns, otherwise the file is rejected. Errors name the file line.
- **Report:** weeks by session start (local ISO week); "joint-pain sets by area" counts sets with joint pain >= 1 ("unknown" when no area); a deload week is any week with a deload session; mean RIR shows how many sets recorded RIR; free-text notes are never in report output.

### M3.5 semantic review fixes (builder, 2026-11-11)
Two-model review: 10 issues (3 High, 5 Medium, 2 Low); report in `.agents/reviews/` (gitignored). All fixed:
- One correction-chain helper, `core.models.Lineage` (also used by the zone report's probe resolver). A session's lineage is every CID whose corrections end at it.
- CSV import follows session corrections: a row that matches a corrected session attaches new sets to the current version, and a set already stored under an earlier version is skipped (High #1).
- Set order is unique across the whole lineage of a session (High #2). TrainingSet inserts take the contributor row lock (Medium #5).
- Admin: a current session lists sets attached to any of its versions; a superseded session links to its current version and has no add link (High #3).
- The report counts sessions without sets and marks a zero-set deload week (Medium #4); it loads only sessions in the window and counts earlier stop signals in the database (Medium #6).
- A joint-pain area needs a joint-pain score (Medium #7). `program` groups case- and spacing-insensitively but must match exactly within a session, so a typo is an error, not a second session (Medium #8). Repeated CSV columns are rejected (Low #9).
- Shared helpers (`DISCLAIMER`, `STOP_TEXT`, `iso_default`, `localize`, `describe`) moved to `core/services/common.py` (Low #10).

### History rewrite and repository rename (owner, 2026-11-11)
- **History rewrite:** the owner force-pushed a rewrite (git-filter-repo `--mailmap`) that replaces the work email with the GitHub noreply address in every commit. File content is unchanged (all trees identical); every commit SHA changed. New tips: `main` 989b935, `develop` d9abbac, tag `v0.2.0` -> 989b935. Commit SHAs written in this log before 2026-11-11 20:27 ET refer to the old history (for example `b22e433` is now 989b935); old commits stay reachable on GitHub only through PR refs until GitHub Support removes them.
- **Rename:** the GitHub repository is now `sudoCreate258/nymbus_v1510` (was `nba_smartboy`); GitHub redirects the old URL. Tracked files use the new name.
- **Local folder stays `nba_smartboy`** for now: the owner's permissions file, the steering files (`.kiro/steering/product.md`, `tech.md`) and the planner's checks use that path, and Docker Compose derives the database volume name `nba_smartboy_pgdata` from it. Renaming the folder later needs those updated together (and the volume carried over).
- New commits use the noreply address (passed per command; the builder does not change git config).

### M4 builder choices (builder, 2026-11-11, in progress)
Choices the spec left open. Owner or planner may overrule.
- **App name:** `ui` (the design allows `app` or `ui`; `ui` avoids confusion with Django "apps").
- **Which contributor a login sees:** Nymbus phase 1 has one contributor per instance, so every login maps to `TWIN_CONTRIBUTOR` (env, default `mike`). Linking Django users to contributors is Nymbus phase 2.
- **Home screen stop signals:** sharp_or_numb discomfort checks and training sets with joint pain >= 2 in the current local week, plus a count of earlier ones.
- **One write path (closes M3 review #9):** `core/services/records.save_record()` does the duplicate check, the correction (`replaces_cid` for overlap/order checks, Supersession event, revert to an identical earlier record) and the contributor lock. The admin and the app both call it; DailySnapshots go through `record_snapshot` inside it.
- **Check-in forms:** one page per record type (snapshot, probe, work block, discomfort, reset), no JavaScript. Local `datetime-local` input in the contributor's time zone; DST-ambiguous or skipped times are rejected. The reset form picks the before/after mini-probes from the last 3 days instead of typing CIDs. App-entered snapshots get `source = manual`.
- **Offline (T4):** the service worker is served from `/sw.js` (scope `/`), caches the shell (CSS, `offline.js`, icons, `/offline/`, manifest) and every page viewed (network first), only same-origin GETs, never `/admin/`. `offline.js` (vanilla, no build) sends check-ins with `X-Offline-Replay`; the view answers JSON (`created`, `skipped` = already saved by CID, `superseded`, 400 `invalid` with field errors, 403 `login`). Live submits ("live") go home with the flash message; invalid or logged-out live submits fall back to a normal form post so errors render next to the fields. Unreachable instance: the form is kept in IndexedDB and replayed in order when the phone is online; failures stay listed with the reason. Manifest, service worker and offline page are public (no personal data). Icons are generated PNGs in the repo.
- **LAN mode and debug off (T5):** `TWIN_LAN_HOST` (unset = off) is both the Compose bind address (`${TWIN_LAN_HOST:-127.0.0.1}:8000`) and an extra `ALLOWED_HOSTS` / `CSRF_TRUSTED_ORIGINS` entry (`http://<host>:8000`); settings raise `ImproperlyConfigured` when it is set with `DJANGO_DEBUG=1`. Static files are served by WhiteNoise 6.12.0 (pinned pip dependency, `WHITENOISE_USE_FINDERS`, no collectstatic step, no CDN). `.env.example` now defaults to `DJANGO_DEBUG=0`. The dev server (`runserver`) stays the web server until M6 hardening.
- **Login rate limit (T5):** 5 failed attempts per username or per client address within 15 minutes, then HTTP 429 with a plain message; counts live in Django's default local-memory cache (one process, reset on restart). A successful login clears the username count.
- **Export and import (T6):** nymbus-jsonl v1 (header, record and supersession lines, creation order; format in `docs/DATA_MODEL.md`). Record `fields` are the canonical content (`nymbus.provenance.normalize_fields`), so every line is self-verifying. `import_my_data` only into a database with no records for the contributor; it replays in creation order (so references and corrections validate as they did originally), sets `replaces_cid` for corrections, inserts snapshots without the one-per-date rule (history comes from the supersession lines), checks each CID twice and is atomic. Round-trip test covers every record kind, a corrected snapshot, a corrected probe referenced by a reset, an overlapping work-block correction and sets under a corrected training session. Not exported: users, ProbeBaseline settings; `created_at` is not restored.
- **API (T6):** `/api/v0/today`, `/api/v0/trends?weeks=4|12`, `/api/v0/recent`: GET only, same session login (403 JSON when logged out, 405 for other methods), `Cache-Control: no-store`. Trends return the chart data (points, unit, band, source), not SVG.
- **Module registry (design addition from 011):** three Django apps `modules/probes`, `modules/zone`, `modules/training`, each with a `module.json` (id, name, version, description, reads/writes/shares as `{kind, category}`, compute `{profile: on-demand|off-hours, hint}`, and `ui` = the check-in kinds, home sections and chart groups it owns). `ui/modules.py` discovers and validates them; `ui.ModuleSetting` stores on/off (configuration, no CID; migration `ui/0001`; a module without a setting is on). Off = its check-in forms 404, its home sections, charts and Recent groups are hidden, also in `/api/v0/`. Records are never touched and stay in the export. The daily snapshot form, sleep and body charts are core (not a module). Report commands and the admin ignore the switch (operator tools). Per-category permission enforcement is M5.
- **Review fixes (PR #10, two-model review, 23 issues):**
  - `save_record` takes the contributor lock before checking that the record being corrected is still current (no forks); a revert must stay within the corrected record's lineage; a snapshot correction must target the current snapshot of its date.
  - Offline queue: every refusal of a replay is JSON (`invalid` 400, `stale` 409, `gone` 404, `login` 403); the client reads the status first, marks permanent failures with their reason and moves on, and stops (to retry) only on no connection, login or 5xx. Each replay fetches a fresh CSRF token from `/csrf-token/` (Django rotates it at login; the cookie stays HttpOnly). Retries every minute, on `visibilitychange` and `online`.
  - Service worker: cache-first only for `/static/` and the manifest; pages cached only if HTML, not `no-store` and not an attachment; never `/admin/`, `/api/`, `/my-data/`, `/csrf-token/`, `/logout/`. Logout deletes saved pages (keeps unsent check-ins for the next login). Registered only in a secure context.
  - LAN mode (planner decision): plain HTTP keeps the offline check-in queue but browsers do not allow installing or offline pages there; README says so; HTTPS stays in M6. Manual phone checklist in OPERATIONS.
  - Stop signals are core (always on Today, whatever module is off). Admin login shares the rate limiter; a successful login clears the username and the address counts. Admin correction of a superseded record is a form error (was a 500).
  - Import: every line is checked against the v1 shape (types, no extra keys, known kinds and fields); correction lines must reference records earlier in the file and pass `Supersession.record` (same kind and contributor, not self); every failure is a line-numbered error; an empty destination takes the export's time zone.
  - `TWIN_CONTRIBUTOR` naming no contributor is a clear `ImproperlyConfigured`. Missing flag CSS added. `task-done.ps1` returns non-zero when the push fails. The local gate and CI now syntax-check `offline.js` and the rendered `sw.js` with node (official `node:22-alpine` locally).
  - Deferred (non-blocking): probe history windowing on Today/Trends (#14, perf), `ingest_training_csv` still has its own write path (#18), browser automation (no Docker Official Image for it; manual checklist instead), single-contributor mapping (every Django account sees the one contributor; phase 1 by design).
- **Known limit (T4):** a reset entered offline can only pick mini-probes the instance already has (the probes' CIDs come from the server), so log the mini-probes online or enter the reset after they are sent.
- **Correct this:** from the Recent page (current records of the last 14 days). The form is prefilled; fields the form does not show (e.g. `spo2`, ratings, the original `source`) are carried over from the record being corrected, so a correction never drops data. A snapshot correction keeps its date. Records already superseded cannot be corrected (the current version must be).

### M4.5 builder choices (builder, 2026-11-11)
Choices the spec (021) left open. Owner or planner may overrule.
- **Tooling (R3):** the web image (official `python:3.12-slim`, Debian 13) gets `rclone` 1.60 from Debian and `pg_dump`/`pg_restore` 16 copied from the official `postgres:16` image. Debian's own client is 17, whose dumps a 16 server can reject; copying from `postgres:16` keeps them identical to the server. One image does everything because the backup needs Django (export, CID checks). Not `alpine:3.20 + apk`: that would need a second Python setup for the export and CID verification. No third-party images. Tests assert the tool versions.
- **Layout on the remote:** `<BACKUP_REMOTE>sets/<UTC start time>/` holding `twin.dump` (`pg_dump -Fc`), one `my-data-<handle>.jsonl` per contributor, `manifest.json` and, with `BACKUP_INCLUDE_INBOX=1`, `inbox.tar.gz`. Manifest: format, version, UTC time, git commit (read from `.git`; "unknown" if absent), app version (`TWIN_VERSION`), file names/sizes/SHA-256, record counts per type.
- **Secrets (R4):** the rclone config is mounted read-only (`RCLONE_CONFIG_HOST`) into the opt-in `backup` service only; `rclone.conf` and `backups/` are gitignored; a hygiene test scans tracked-style files for crypt sections, obscured passwords and OAuth tokens (with a self-test). The builder never ran `rclone config` or saw a crypt password; tests build a throwaway local crypt remote with random passwords at run time.
- **Schedule (R6):** a night starts at the window start (local). Due when the last attempt began before the latest window start: inside the window = nightly; a missed window = one catch-up on the next check; never twice a night (a failed attempt also counts, so a broken setup retries the next night, not every 5 minutes). A window start skipped by DST moves to the instant the clocks jump. The loop checks every 5 minutes and survives database restarts. `backup_now` is manual and exits non-zero on failure.
- **Retention (R7):** newest set of each of the last 7 local days with sets, plus newest set of each of the last 4 ISO weeks with sets; unknown names are never deleted; pruning happens only after the new set verified.
- **Verify (R8):** fresh download through crypt, manifest equal to the uploaded one, size and SHA-256 per file, `pg_restore` into a scratch database, every export line recomputes its CID, the CID sets in the restored tables equal the exports' and the manifest counts, scratch database dropped. The "import_my_data verification" in R8 is done as the CID comparison (the import command itself needs an empty database; the comparison checks the same property on the restored dump). A failed verify leaves earlier sets untouched and shows red on Today.
- **Status (R9):** `backup.status`: ok up to 48 h, amber 48 h to 7 days, red after 7 days or when the latest attempt failed; "not set up" when no remote is configured. On Today and as `today.backup` in `/api/v0/today`.
- **Restore (R10):** `restore_backup --set latest|NAME [--yes]` (or a downloaded folder): checks hashes, `pg_restore --clean`, compares CIDs. It refuses to replace a database that already has records unless `--yes`. Tested end to end with a local crypt remote (back up, delete everything, restore, identical CIDs), and once as the documented commands in fresh containers against the real local database (restored into a scratch database, then dropped).
- **Review fixes (PR #11, two-model review, 18 de-duplicated issues: 4 High, 11 Medium, 3 Low):**
  - Also from the second pass: crypt is refused when `no_data_encryption` is on, `filename_encryption` is off, or there is no password; an rclone config inside the repository folder is refused; restore refuses a set whose database has migrations this code lacks (made by newer code), checked in the scratch restore before anything is replaced; the scratch restore needs free disk of twice the set size and stray `twin_verify_*`/`twin_restore_check` databases are dropped at the start of every run; a failed attempt is retried inside the window up to 3 attempts a night, 20 minutes apart (success or an exhausted night ends it); GitHub CI installs rclone and the PostgreSQL 16 client (the backup tests need them); the unused `make-test-remote.py` was removed (tests use `tests/backup_helpers.py`); `TWIN_VERSION` can be set from the environment.
  - Found by running the documented fresh-machine steps for real: a freshly migrated database holds the seeded `mike` contributor, which the all-tables "already has data" check counted as data, so the runbook's restore without `--yes` would have been refused (now that one row counts as empty; `--yes` is only for replacing real data and is no longer in the fresh-machine command); and sets made before the manifest carried a supersession count failed the stricter check (now compared only when present).
  - Deferred: moving rclone out of the web image into the backup service only (#14 in part; the config-outside-repo check and the opt-in profile limit the exposure; a second image is more to maintain than it removes).
  - First reviewer's 8 issues:
  - Crypt is enforced: `require_crypt` reads each remote's type from `rclone config dump` (aliases are followed) and refuses plain backends, local paths and unknown names before anything is built or uploaded; restore refuses them too. Tests assert not a byte reaches a plain remote.
  - Staging then publish: sets upload to `staging/<set>`, are verified there, and only then `moveto` `sets/<set>`. `latest`, restore by name and retention only look in `sets/`; failed sets stay in staging and are purged by the next successful run. A failed verify can no longer be restored or displace verified history.
  - One snapshot: the dump (`pg_dump --snapshot`), the exports and the counts read the same exported repeatable-read snapshot. Verification now also compares correction (supersession) events and checks the export header; the manifest counts supersessions.
  - Restore proves the set in a scratch database first, then replaces the live database with `pg_restore --clean --single-transaction` (all or nothing), then compares again. The "already has data" check covers every table (users and settings too), not only records. The runbook stops the web and backup services during the restore.
  - Interrupted attempts: a `running` row older than 6 hours is marked failed ("Interrupted") before each check, is excluded from the "already ran this night" test (so the night is retried), and shows red on Today.
  - Verify and prune are separate outcomes: `published`/`prune_error` on `BackupRun`; a failed delete of old sets leaves the new set `ok` (with a warning on Today and in `backup_now`), and failure stages are named backup / verify / publish.
  - The secret scan now covers `.kiro` (tracked specs), with a test that it does.
- **Not done here:** nothing runs against Google Drive (owner connects it, R5). Data directory permissions and key backup are the owner's responsibility (OPERATIONS says so). Dump and export are plain files only inside the container's temp folder until rclone encrypts them; the temp folder is deleted after each run.

### Planner answers to M3 (2026-11-11)
- M3 builder choices accepted.
- Demographic pricing (owner clarification): its purpose is to put a tangible value on data from different groups to see where costs can be cut or optimized. It runs only on aggregates (at least 10 people per group), never on individual-level demographic records.
- v0.2.0 = `main` at `b22e433` (PR #5). Tagged by the owner.

### Planner: training log, camera adapter, debug (2026-11-11)
- M3.5 Training log added before M4 so RP-style training data (sets, reps, load, RIR, pump, soreness, joint pain, mesocycle week/deload) can be logged now. Manual entry and CSV import; no RP API dependency.
- Camera-based posture/pose tracking (two cameras for 3D) is a later adapter (M7, spec after M4). Rules already decided: video stays on the device and is not stored by default; only derived keypoints become records; library license must be AGPL-compatible.
- Debug: on for local development only until M4 makes debug-off fully usable.

### Owner direction: cloud storage, modules and local models (2026-11-11)
- **Cloud storage is a backup target, not the database.** The owner has 1 TB of unused cloud storage (more than local disk). M4.5 adds client-side encrypted backups pushed during off-hours with a bandwidth limit, to a remote the user chooses; first target is Google Drive via rclone (its `crypt` remote encrypts before upload). The remote holds ciphertext only; keys stay local; losing the key loses the backup, so the README covers key backup. PostgreSQL stays the live store.
- **Off-hours is also when heavy local compute runs** (model training, pose processing), not just uploads. Federated learning is about training without pooling raw data; it is not a storage method.
- **Modular UI and local models.** Every feature is a module with a manifest: id, version, record kinds it reads (by data category), kinds it writes, compute profile (on-demand or off-hours; CPU/GPU hint), and what it may share. The core enforces the user's per-module, per-category grants (M5 permissions extend to modules). Modules and local models can be added or removed to personalize the experience; a removed module loses access immediately; its outputs stay as records with provenance.
- **First modules:** probes, zone, training (M3.5), later pose (M7) and Rendez-Vous. This is the seed of the Nymbus module marketplace; the manifest format should move into the Nymbus doc once stable.

## Open
- CID codec: raw (0x55) over canonical JSON now. AT Protocol uses dag-cbor (0x71). Decide before Nymbus phase 2.
- Storage direction: Nymbus phase 2 says central storage under HIPAA-style controls; the owner also wants small, user-run instances with client-side encrypted group backups. Resolve in the Nymbus doc before phase 2.
- Payout: the Nymbus doc says contributors get paid in cryptocurrency; the owner also wants the project free to the public and run by a co-op/nonprofit. M1–M5 use simulated units only.
- Source material (white papers, fitness AI venture brief, `digital-twin.jsx`, CS questions specs) to be added to `docs/`.
- GitHub remote: `sudoCreate258/nymbus_v1510` (public).

## Status
- M4.5: built (T1-T7, spec `.kiro/specs/m4-5-encrypted-backup/`) on `feature/m4-5-encrypted-backup`. Local gate 588 passed + migrations clean + JavaScript syntax OK. Shipped: backup tooling in the image, opt-in `backup` Compose profile, schedule/retention (plain Python), runner (dump, exports, manifest, encrypted upload, full verify, prune), `backup_now`, `backup_loop`, `restore_backup`, `BackupRun` log (migration `backup/0001`), backup status on Today and in the API, OPERATIONS steps for the owner and the restore runbook. Not yet run against a real cloud remote (owner connects it).
- M4: built (T1-T7 + module registry, spec `.kiro/specs/m4-phone-app/`) on `feature/m4-phone-app`. Local gate 513 passed (`scripts/ci-local.ps1`, makemigrations clean). Shipped: `ui` app (login with rate limit, Today, Check in for five record types, Correct this, Trends with server-rendered SVG, Recent, Modules, My data download), shared write path `save_record` (admin and app), offline (manifest, root service worker, IndexedDB queue with JSON replay and CID duplicate handling), LAN opt-in mode, debug-off static via WhiteNoise, `export_my_data` / `import_my_data` (nymbus-jsonl v1, round trip with identical CIDs), read-only `/api/v0/`, external-request scan and 200 KB budget tests. New migrations: `ui/0001` (ModuleSetting). New dependency: whitenoise 6.12.0. The JavaScript is syntax-checked with node in the local gate and in CI; it is not exercised in a browser by the test suite (manual phone checklist in OPERATIONS).
- 003 internal docs: `docs/ARCHITECTURE.md`, `docs/OPERATIONS.md` (backup/restore tested byte-exact into a scratch database), `docs/DATA_MODEL.md` generated from the models by `data_model_doc` (test fails when stale). `backups/` gitignored. Local gate 393 passed.
- M3.5: built (T1-T5, spec `.kiro/specs/m3-5-training-log/`) on `feature/m3-5-training-log` (branched from the M3 tip while PR #6 waits for CI). Verified 2026-11-11: `docker compose exec web pytest` ran 376 passed (M3 after review: 314), 387 after the review fixes. Migration 0015 is additive. Exact CSV header from planner message 012, pinned by a test.
- Release v0.2.0 (M1 + M1.1 + M2): owner approved in chat 2026-11-11; PR #5 `develop` -> `main` merged at `b22e433`; CI on `main` green (https://github.com/sudoCreate258/nymbus_v1510/actions/runs/43084786354). Tag by the owner.
- M3: built (T0-T8, spec `.kiro/specs/m3-work-zone/`) on `feature/m3-work-zone`. Verified 2026-11-11: `docker compose exec web pytest` ran 299 passed (M2 was 209), 314 after the review fixes; `makemigrations --check --dry-run` reports no changes; pinned pre-M2 ProbeSession and pre-M3 WorkBlock CIDs unchanged. Migrations 0011-0014 are additive only. Shipped: T0 (42-day default baseline, "ratio" label, WorkBlock overlap rule + merged-interval sums, early-median test), WorkBlock `posture`/`planned_length_min` (OMIT_IF_NULL), DiscomfortCheck, `mini_puzzle` kind, Reset, WeeklyCheck, `twin_metrics/zone.py`, `zone_report` (text and `--json`), README section. GitHub Actions run: see the M3 PR.
- M1: built (T1–T10). T0 decided (AGPL-3.0-or-later). Baseline verified at M1.1 start: `docker compose exec web pytest` ran 76 passed (earlier figures of 59 and 76 were unverified).
- M2: built (T0-T8, spec `.kiro/specs/m2-probe-log/`). Verified 2026-11-11: `docker compose exec web pytest` ran 209 passed (M1.1 baseline was 138); `makemigrations --check --dry-run` reports no changes. GitHub Actions run: https://github.com/sudoCreate258/nymbus_v1510/actions/runs/43067143291.
  - Shipped: T0 housekeeping (admin bad `supersedes` is a form error, DST ambiguous/nonexistent ingest times rejected, SPDX on 0008, `.agents/` ignored); `OMIT_IF_NULL` canonicalization rule with pinned pre-M2 CIDs; `ProbeSession.move_time_cv` (migration 0009); `ProbeBaseline` (migration 0010, no CID); `twin_metrics/probes.py` (plain Python statistics); sleep and work conditions and `kind_report` in `core/services/probe_report.py` (`core/services.py` became the `core/services/` package, imports unchanged); `probe_report` command (text and `--json`); README section.
  - T0 deviations: `git add --renormalize .` changed nothing (the repo was already LF in the index and working tree). The T0 push of `main` and the first-CI confirmation are done by the orchestrator, not by the builder.
  - Already correct, tests added only: `record_snapshot` already validated before hashing, so a naive datetime already raised ValidationError.
  - Open questions for the planner: (1) sleep and work window rules in "Sleep and work conditions" above; (2) multiple `ProbeBaseline` rows per kind: newest `frozen_at` wins, older ones are kept as history; (3) `move_time_cv` is stored as a ratio with 2 decimals (max 999.99), not a percent; confirm the unit; (4) the default baseline is the first 10 sessions even if they span months.
- M1.1: built (T1-T9, spec `.kiro/specs/m1-1-fixes/`). Verified 2026-11-11: `docker compose exec web pytest` ran 138 passed; `makemigrations --check` reports no changes. Corrections for DailySnapshot, ProbeSession and WorkBlock all record a Supersession. Not pushed; CI has not run on GitHub yet.
