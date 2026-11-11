# M1 Foundation + Provenance — Design

## Components
- `db`: postgres:16, named volume `pgdata`, healthcheck `pg_isready`.
- `web`: python:3.12-slim, Django dev server on 8000 for M1; depends_on db
  (healthy). Bind-mounts the repo.

## Plain-Python domain module: `nymbus/provenance.py`
No Django imports (it moves behind the Nymbus storage layer later).
- `canonical_bytes(kind, contributor, fields) -> bytes`
  - JSON, keys sorted, separators `(",", ":")`, UTF-8, `ensure_ascii=False`.
  - Values normalized: dates/times ISO 8601 strings; Decimal → string;
    None kept as null; enum values as their stored string.
- `compute_cid(data: bytes) -> str` — CIDv1:
  `bytes = 0x01 (version) + 0x55 (codec: raw) + 0x12 0x20 (sha2-256, 32 bytes) + sha256(data)`;
  string = `"b"` + lowercase RFC 4648 base32 of those bytes, no padding.
  (Implement directly with `hashlib` + `base64.b32encode`; no extra dependency.)
- Unit tests use fixed inputs with expected CIDs committed in the test.

## Django app `core`
- `Contributor(handle unique)`.
- Abstract `ProvenancedRecord`: `cid` (char, unique, indexed),
  `contributor` FK, `supersedes` (self FK, null), `created_at`.
  - `save()`: on insert compute `cid` from the subclass's `domain_fields()`;
    if the row already exists raise `ImmutableRecordError`.
  - `current()` queryset helper: records with no successor.
- `DailySnapshot(ProvenancedRecord)` — fields per R4; `clean()` enforces the
  post-sauna rule; partial unique constraint on (contributor, date) among
  current records is enforced in the ingest/service layer (and tested).
- `ProbeSession(ProvenancedRecord)`, `WorkBlock(ProvenancedRecord)` — fields
  per R5/R6.
- Admin: list views with filters; existing records read-only; a "Save as
  correction" action creates a new record with `supersedes` set.

## YAML ingest format
```yaml
date: 2026-11-11
source: samsung_health
bia_timing: pre_session
sleep_score: 86
bedtime: "22:54"
resting_hr_sleep: 52
hrv: 41
weight_kg: 97.8
body_fat_pct: 24.0
skeletal_muscle_kg: 40.6
```
A file holds one mapping or a list. One transaction per file.

## CI
`.github/workflows/ci.yml`: ubuntu-latest, postgres service container,
install requirements, run `pytest`.

## Deliberately deferred
- SipHash-2-4 dedup keys (integrity layer): CID uniqueness covers exact
  duplicates for structured records in M1.
- Usage events and the simulated payout ledger (M5).
- Dashboards, baselines/flags, screenshots, network egress.
