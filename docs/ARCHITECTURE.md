# Architecture

This describes what the code does today (after M6, the end of Nymbus phase 1). Items marked "planned" are not built.

## Components

| Component | Where | What it does |
|---|---|---|
| Web + admin | `twin/` (settings, URLs), `core/admin.py` | Django 5.2 project. The Django admin adds and corrects records; the phone app (`ui`) is the everyday interface. |
| Records | `core/models.py` | Contributor, the eight record types (see `docs/DATA_MODEL.md`), Supersession events, ProbeBaseline settings, the `Lineage` helper for correction chains. |
| Write paths | `core/services/records.py` (`save_record`), `core/services/snapshots.py`, ingest commands | All writes go through model validation and the record's `save()`, which computes the CID. |
| Ingest adapters | `core/management/commands/ingest_yaml.py`, `ingest_training_csv.py` | YAML DailySnapshots (screenshot-parser output) and training CSV. One transaction per file; identical rows are skipped by CID. |
| Report services | `core/services/probe_report.py`, `zone_report.py`, `training_report.py` | Load current records for one contributor and a time window, call the statistics modules. Read-only. |
| Statistics | `twin_metrics/probes.py`, `zone.py`, `training.py` | Plain Python, no Django imports: baselines, rolling z-scores, flags, zone and reset statistics, training volume. |
| Provenance | `nymbus/provenance.py` | Canonical JSON bytes and CIDv1 (raw, sha2-256). Plain Python, no Django imports. |
| Phone app | `ui/` | Login, Today, Check in, Trends (server-rendered SVG), Recent, Modules, Permissions, Statement, My data download, read-only `/api/v0/`, offline queue and service worker (M4). |
| Modules | `modules/*/module.json`, `ui/modules.py` | Probes, zone and training as switchable modules. Each manifest declares the record kinds it reads and writes by data category; the registry derives the data categories and their owners (M5). |
| Export | `core/services/export.py` | nymbus-jsonl v1: every record, correction and ledger record, self-verifying by CID; import into a fresh database. |
| Backup | `backup/` | Encrypted off-hours backup through an rclone crypt remote: dump, exports, manifest, verify in a scratch database, retention, restore (M4.5). |
| Ledger | `ledger/`, `nymbus/ledger.py` | Grants, revocations and hash-chained access events; the only read path for simulated recipients; `verify_ledger`; deposit statement (M5). |
| Database | PostgreSQL 16 (`docker-compose.yml`, volume `pgdata`) | The only live store. Ledger tables refuse UPDATE and DELETE (triggers). |
| Security | `ui/security.py`, `twin/settings.py`, `scripts/scan.*`, `tools/scan_report.py`, `scripts/sign-image.ps1`, `scripts/lan-cert.*` | CSP and security headers, HTTPS mode, vulnerability gate (osv-scanner from Alpine 3.20), image signing (cosign), the owner's local CA for LAN HTTPS (M6). |
| Porting contract | `docs/PORTING.md`, `tools/porting_vectors.py` | Record format, CID, corrections, ledger chain, export and statement formats, with test vectors (M6). |
| Local CI gate | `scripts/ci-local.ps1`, `scripts/ci-local.sh`, `scripts/pre-push` | `pytest`, `makemigrations --check` and a JavaScript syntax check in Docker; the pre-push hook refuses a push unless they pass. GitHub Actions (`.github/workflows/ci.yml`) runs the same checks as a second gate. |

## Data flow

```
adapter (admin form | phone check-in | ingest_yaml | ingest_training_csv)
  -> model validation (field bounds, cross-field rules, references, overlap/order checks)
  -> canonical content (domain fields, OMIT_IF_NULL) -> CID (nymbus/provenance.py)
  -> insert (immutable row; identical CID = skip)
  -> correction? append Supersession(old_cid -> new_cid)
  -> reports and pages read current records (latest Supersession wins; references follow Lineage)

simulated recipient -> ledger.service.simulated_read
  -> active grant for (recipient, category)?  no -> refused, nothing written
  -> current records of the category's kinds -> AccessEvent (record CIDs, units, prev_hash) -> data
```

- Times are stored in UTC. Offset-less input is read in the contributor's time zone; DST-ambiguous or skipped local times are rejected. Reports bucket by local ISO week (Monday start), local day or local month.
- Writes that check other rows first (DailySnapshot one-per-date, WorkBlock overlap, TrainingSet order, grants, revocations and reads) take a row lock on the contributor, so two writers cannot both pass the check.
- Reports never write. Free-text notes are never part of report output.

## Nymbus layer mapping

| Nymbus layer (`.kiro/steering/nymbus.md`) | Status in this repo |
|---|---|
| 1 Capture | Built: admin forms, phone check-ins, YAML and CSV adapters. Camera pose adapter: planned (M7). |
| 2 Storage and compliance | Local PostgreSQL, one instance per person, with client-side encrypted backups (M4.5). Central or shared storage: deferred (Nymbus phase 2). |
| 3 Integrity | Exact duplicates are caught by CID equality (sha2-256), not SipHash. Media near-duplicates (pHash): deferred (no media yet). |
| 4 Provenance | Built: one CID per record, contributor on every record, append-only Supersession events. |
| 5 Shared learning | Deferred (Nymbus phase 3). |
| 6 Ownership and payout | Simulated (M5): per-category grants and revocations, hash-chained access events keyed by CID, monthly deposit statement in simulated credits. Simulated recipients only; no money, tokens or network sharing. |

## Trust boundaries

- **Network:** the web port is bound to `127.0.0.1:8000` unless LAN mode is switched on (plain HTTP). LAN HTTPS (M6): an opt-in TLS server on `TWIN_HTTPS_HOST:8443` with a certificate from the owner's local CA, secure cookies and HSTS. The app makes no outbound requests; the backup talks only to the rclone remote the owner configured.
- **Configuration:** settings come from `.env` (gitignored). `DJANGO_SECRET_KEY` is required unless `DJANGO_DEBUG=1`; Compose refuses to start without `POSTGRES_PASSWORD`.
- **Access:** one login per instance, rate-limited; the app acts as the single contributor `TWIN_CONTRIBUTOR`.
- **Repository:** public. Test fixtures are synthetic. Real exports stay in `data/inbox/` (gitignored). The CI token is read-only.
- **Immutability:** records, Supersession and the ledger are immutable in the model layer and in the database (row triggers refuse UPDATE and DELETE, M6). The database owner can still TRUNCATE, DROP or switch a trigger off; the CID checks and `verify_ledger` show such edits.
- **Not yet:** encryption at rest on the local disk (the owner's disk encryption), multi-arch (ARM) images (deferred, see DECISIONS).
