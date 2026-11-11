# M1.1 Fixes — Design notes

- No production data exists yet, so schema changes may be a fresh migration
  set (squash or reset) instead of data migrations. Say which in the commit.
- `Supersession` lives in `core`; the "current" lookup is one queryset helper
  shared by all three record types. Index on (contributor, new_cid, created_at).
- The current-per-date check and the lock move from `record_snapshot` into
  `DailySnapshot.save()` (or a manager method `save()` always calls), so there
  is exactly one write path. `record_snapshot` calls it.
- Time zone conversion happens in the ingest adapter and in model `clean()`;
  `nymbus/provenance.py` only receives aware UTC datetimes and raises on naive ones.
- Validation wraps Decimal conversion (`InvalidOperation`, non-finite) into
  `ValidationError({field: ...})`.
- CID algorithm itself does not change.
