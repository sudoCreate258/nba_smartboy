# M5 Simulated ownership ledger — Design

- **Plain-Python core (`nymbus/ledger.py`, no Django imports):** recipients, units rule (1 simulated
  credit per record read), grant activity (`start <= at < end`, and before any revocation), chain
  digest (SHA-256 hex of an event's canonical bytes; genesis = 64 zeros), chain check, statement
  rows and the statement CID. Moves behind the Nymbus storage layer later.
- **Categories (R1):** a category is owned by whoever writes its record kinds: a module (its manifest
  `writes`) or the core (`daily_snapshot` -> `daily_metrics`, `weekly_check` -> `wellbeing`). Every
  data kind has exactly one category; the registry refuses a manifest that files a kind under another
  category or a category written by two owners. The probes manifest reads `daily_snapshot` as
  `daily_metrics` (was `sleep`). Record counts are current records of the category's kinds.
- **New Django app `ledger`:** `Grant`, `Revocation` and `AccessEvent` are `ProvenancedRecord`s
  (contributor, CID, immutable at the model level), so they share the one-CID rule, the export
  format and the backup verify.
  - `Grant`: category, recipient, purpose (required), start, end (optional).
  - `Revocation`: grant_cid (unique: one per grant), at, reason. It supersedes the grant by
    reference; no `Supersession` row (those are same-kind corrections).
  - `AccessEvent`: seq (1, 2, ... per contributor), at, grant_cid, recipient, category, purpose,
    record_cids (list), units, prev_hash. Its CID is the CIDv1 of its canonical bytes, so the hash
    the next event stores is the digest inside that CID (no second identifier). Unique
    (contributor, seq) and (contributor, prev_hash): no forks.
  - Model validation replays the rules (grant exists, same contributor, matching recipient,
    category and purpose, active at `at`; seq and prev_hash continue the chain; units = rule), so an
    import validates exactly like a live write.
- **Immutability (R4):** PostgreSQL `BEFORE UPDATE OR DELETE` row triggers on the three ledger tables
  raise. TRUNCATE/DROP stay possible for the database owner (test flush, `pg_restore --clean`); the
  backups and exports are the defence there.
- **Service (`ledger/service.py`, R3, R5):** `grant`, `revoke`, `simulated_read`. Each takes the
  contributor row lock, so a revocation and a read are serialized: a read after a revoke commits is
  refused. A refused read writes nothing. A read returns the current records of the category's kinds
  (kind, CID, canonical fields). `manage.py ledger_read --recipient --category` runs a simulated read.
- **`manage.py verify_ledger` (R4):** recomputes every grant, revocation and event CID, the chain
  (seq contiguous, prev_hash links), grant activity at each event, units, and for every record CID
  read: the record exists, belongs to the event's category and its stored content still hashes to
  its CID. Non-zero exit with every problem listed.
- **Statement (R6):** per local month, rows by (category, recipient, purpose): reads, records
  accessed, distinct records, simulated credits; totals per category. Page `/statement/?month=` and
  download `/statement/download/?month=` as `nymbus-statement-jsonl` v1: header line with the
  statement CID (CIDv1 over the canonical month, time zone, unit and rows), then one line per row.
- **UI (R7):** `/permissions/`: categories grouped by owner (core, then modules), each with its
  record count, active grants, a grant form (recipient, purpose, optional end) and past grants;
  revoke goes through a confirmation page (`/permissions/revoke/<cid>/`, POST to confirm, no
  JavaScript needed). `/statement/`. Both in the nav, server-rendered, no offline queue (permission
  changes need the server), and in the M4 no-external/200 KB tests.
- **Export (R8):** export and import cover the ledger kinds as ordinary record lines (format v1);
  import checks each event's chain link as it replays and then the whole chain. The backup counts and
  compares them too; sets made before M5 (no ledger counts in the manifest) still verify.
- **No network (R9):** a source scan of `ledger/` and `nymbus/ledger.py` for network modules, and a
  runtime test with socket connections patched to fail across grant, read, revoke, statement and
  verify.
