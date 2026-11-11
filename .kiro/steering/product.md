---
inclusion: always
---

# Product: Human Performance Twin (repo: nba_smartboy)

## What it is
The first use case of Nymbus (see `nymbus.md`) and its one-person reference
implementation: a self-hosted "digital twin" that joins biometrics, training,
cognitive probes and work blocks so the owner can see how load (physical +
job) affects sleep, recovery and cognitive acuity.

## Who it serves
- Now: the owner (Mike) — returning athlete, software engineer working
  multiple remote/hybrid jobs ("Da Vinci work cycle").
- Later (Nymbus phase 2+): other contributors in the fitness AI venture.

## Questions the twin must answer (in priority order)
1. Joint durability: is load (training + desk posture) creating pain/discomfort trends?
2. Sleep: is bedtime/sleep score holding under job load?
3. Recomposition: are fat and muscle trending the right way (ground truth = SECA scans)?
4. Cognition: are probe scores declining vs baseline? Are focus blocks ("the zone") getting shorter?
5. Longevity: long-run trends only; no daily decisions.

## Non-goals (until stated otherwise)
- No medical diagnosis or health claims.
- No multi-contributor storage, federation, real payouts, tokens, Buy Me a
  Coffee or cloud deploy (all Nymbus phase 2+).
- No gating training load on pre-session subjective feel.
- No dependency on Google Cloud or any hosted service for core function; the
  twin must work fully offline on local hardware (old phones, Raspberry Pi, a PC).

## Milestones (all inside Nymbus phase 1)
- **M1 Foundation + provenance** — Docker Compose (Django + PostgreSQL),
  contributor + CID-keyed immutable records, YAML ingest, tests, CI. *Done (v0.2.0 with M1.1, M2).*
- **M2 Probe log** — puzzle/game probe entry, baseline (mean/SD, rolling
  median of last 3), amber/red flags.
- **M3 Work + zone** — work blocks, discomfort scores, between-block mini-probes. *Current.*
- **M4 Phone-friendly app** — installable web app served by the user's own
  instance: 30-second daily check-in, today + trends pages (server-rendered
  SVG), offline queue, opt-in LAN mode, "my data" export (JSON Lines with
  CIDs). Works offline on old phones and a Raspberry Pi; no external requests.
  Flutter stays possible later via a read-only JSON API. The UI is modular:
  each feature (probes, zone, training, later pose, Rendez-Vous) is a module
  with a manifest declaring what it reads, writes and computes.
- **M4.5 Encrypted off-hours backup** — client-side encrypted backups (export +
  database dump) pushed during off-hours, bandwidth-limited, to a remote the
  user chooses (first target: the owner's Google Drive via rclone). The
  remote only ever holds ciphertext; restore yields identical CIDs.
- **M5 Simulated ledger** — usage events, simulated payout ledger keyed by CID,
  reconciliation report. *Closes the Nymbus phase 1 gate.* Must also include:
  per-module, per-category usage permissions the contributor controls (e.g. sleep, body
  composition, probes, work blocks, media), a periodic "deposit statement"
  (like a pay stub) showing which records/categories generated usage and the
  simulated units earned, and a test that revoking a category stops new usage
  events for it.
- **M6 Hardening** — security pipeline (Trivy, ZAP, signed images, automatic
  updates), multi-arch (ARM) images for Raspberry Pi, HTTPS for LAN mode,
  DB trigger for immutability, docs, stack-agnostic getting-started guide.
- **P1.5 OurData backup** (between Nymbus phase 1 and 2; owner approves
  start) — on-device encrypted export sent to the village OurData server,
  which stores ciphertext only and replicates to two peer servers; restore
  yields identical CIDs.

Each milestone gets its own spec in `.kiro/specs/<milestone>/` and must run
locally with green tests before the next one starts.
