# Architecture

This describes what the code does today (after M3.5). Items marked "planned" are not built.

## Components

| Component | Where | What it does |
|---|---|---|
| Web + admin | `twin/` (settings, URLs), `core/admin.py` | Django 5.2 project. The Django admin is the only user interface: add records, "Save as correction", read-only views of stored records. |
| Records | `core/models.py` | Contributor, the eight record types (see `docs/DATA_MODEL.md`), Supersession events, ProbeBaseline settings, the `Lineage` helper for correction chains. |
| Write paths | `core/services/snapshots.py` (`record_snapshot`), `core/admin.py`, ingest commands | All writes go through model validation and the record's `save()`, which computes the CID. |
| Ingest adapters | `core/management/commands/ingest_yaml.py`, `ingest_training_csv.py` | YAML DailySnapshots (screenshot-parser output) and training CSV. One transaction per file; identical rows are skipped by CID. |
| Report services | `core/services/probe_report.py`, `zone_report.py`, `training_report.py` | Load current records for one contributor and a time window, call the statistics modules. Read-only. |
| Statistics | `twin_metrics/probes.py`, `zone.py`, `training.py` | Plain Python, no Django imports: baselines, rolling z-scores, flags, zone and reset statistics, training volume. Unit-tested on synthetic data. |
| Provenance | `nymbus/provenance.py` | Canonical JSON bytes and CIDv1 (raw, sha2-256). Plain Python, no Django imports. |
| Report commands | `core/management/commands/probe_report.py`, `zone_report.py`, `training_report.py` | Text or `--json`. Every report says "Load gauge, not a medical assessment." and puts stop signals first. |
| Database | PostgreSQL 16 (`docker-compose.yml`, volume `pgdata`) | The only store. |
| Local CI gate | `scripts/ci-local.ps1`, `scripts/ci-local.sh`, `scripts/pre-push` | `pytest` and `makemigrations --check` in Docker; the pre-push hook refuses a push unless they pass. GitHub Actions (`.github/workflows/ci.yml`) runs the same checks as a second gate. |

## Data flow

```
adapter (admin form | ingest_yaml | ingest_training_csv)
  -> model validation (field bounds, cross-field rules, references, overlap/order checks)
  -> canonical content (domain fields, OMIT_IF_NULL) -> CID (nymbus/provenance.py)
  -> insert (immutable row; identical CID = skip)
  -> correction? append Supersession(old_cid -> new_cid)
  -> reports read current records (latest Supersession wins; references follow Lineage)
  -> twin_metrics statistics -> text / JSON
```

- Times are stored in UTC. Offset-less input is read in the contributor's time zone; DST-ambiguous or skipped local times are rejected on import. Reports bucket by local ISO week (Monday start) or local day.
- Writes that check other rows first (DailySnapshot one-per-date, WorkBlock overlap, TrainingSet order) take a row lock on the contributor, so two writers cannot both pass the check.
- Reports never write. Free-text notes are never part of report output.

## Nymbus layer mapping

| Nymbus layer (`.kiro/steering/nymbus.md`) | Status in this repo |
|---|---|
| 1 Capture | Built: admin forms, YAML and CSV adapters. Phone app: planned (M4). Camera pose adapter: planned (M7). |
| 2 Storage and compliance | Local PostgreSQL only, one instance per person. Central or shared storage: deferred (Nymbus phase 2). Encrypted off-hours backup: planned (M4.5). |
| 3 Integrity | Exact duplicates are caught by CID equality (sha2-256), not SipHash. Media near-duplicates (pHash): deferred (no media yet). |
| 4 Provenance | Built: one CID per record, contributor on every record, append-only Supersession events. |
| 5 Shared learning | Deferred (Nymbus phase 3). |
| 6 Ownership and payout | Simulated ledger, usage events and per-category permissions: planned (M5). No money or tokens. |

Module registry and Modules page: planned (M4). Per-module, per-category grants: planned (M5).

## Trust boundaries

- **Network:** the web port is bound to `127.0.0.1:8000` (`docker-compose.yml`). The app makes no outbound requests. LAN mode: planned (M4); HTTPS for it: planned (M6).
- **Configuration:** settings come from `.env` (gitignored). `DJANGO_SECRET_KEY` is required unless `DJANGO_DEBUG=1`; Compose refuses to start without `POSTGRES_PASSWORD`.
- **Access:** Django admin login. Debug mode is for local development.
- **Repository:** public. Test fixtures are synthetic. Real exports stay in `data/inbox/` (gitignored). The CI token is read-only.
- **Not yet:** encryption at rest, automated backups (manual steps in `docs/OPERATIONS.md`), a database-level immutability trigger (planned (M6)).
