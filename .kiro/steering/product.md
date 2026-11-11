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

## Milestones (all inside Nymbus phase 1)
- **M1 Foundation + provenance** — Docker Compose (Django + PostgreSQL),
  contributor + CID-keyed immutable records, YAML ingest, tests, CI. *Current.*
- **M2 Probe log** — puzzle/game probe entry, baseline (mean/SD, rolling
  median of last 3), amber/red flags.
- **M3 Work + zone** — work blocks, discomfort scores, between-block mini-probes.
- **M4 Dashboard** — trends joining sleep, HR/HRV, probes, work hours.
- **M5 Simulated ledger** — usage events, simulated payout ledger keyed by CID,
  reconciliation report. *Closes the Nymbus phase 1 gate.*
- **M6 Hardening** — security pipeline (Trivy, ZAP, signed images, automatic
  updates), docs, getting-started guide.

Each milestone gets its own spec in `.kiro/specs/<milestone>/` and must run
locally with green tests before the next one starts.
