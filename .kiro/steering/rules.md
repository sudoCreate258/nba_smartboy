---
inclusion: always
---

# Operating rules

## Data rules (domain)
- Data enters only through an ingestion adapter: today YAML from the owner's
  screenshot parser; direct exports/APIs are added as new adapters. Never
  invent, interpolate or "fill in" missing values; store null.
- Do not use Gemini-parsed data. Every record keeps its `source`, its
  contributor and its CID (see `nymbus.md`).
- BIA body-composition readings taken post-sauna are invalid. Only
  pre-session readings are stored; reject records flagged post-sauna.
- SECA scans are ground truth for body composition; watch BIA is a trend proxy.
- Pre-session subjective feel is never used to gate load decisions.
- Records are immutable; a correction is a new record with a new CID that
  supersedes the old one. Never overwrite history.
- Health data stays local. No external network calls from the app in M1–M4.

## Workflow (planner / builder loop)
- **Planner** = the owner's Claude chat. Owns steering files, specs and
  `docs/DECISIONS.md`.
- **Builder** = Kiro. Implements tasks from the active spec, runs Docker,
  tests and git locally.
- Loop:
  1. Builder works the active spec's `tasks.md` top to bottom, one task at a time.
  2. After each task: tests green, commit with message `M<n>-T<k>: <summary>`.
  3. If a task needs a design decision not covered by the spec, stop and add
     an entry to `docs/DECISIONS.md` under "Open" — do not guess.
  4. At milestone end: update `docs/DECISIONS.md` "Status" with what shipped,
     what failed, and open questions. Owner brings it to the planner, who
     writes the next spec.
- Do not edit files in `.kiro/steering/` without the owner's approval.
