# M5 Simulated ownership ledger — Tasks

Branch `feature/m5-simulated-ledger` from `develop`, after M4.5 (PR #11) is merged.

- [x] T1. Categories: core + manifest owners, one category per kind, registry validation; probes manifest `daily_metrics`. Tests. _(R1)_
- [x] T2. `nymbus/ledger.py` and the `ledger` app: Grant, Revocation, AccessEvent with validation, migrations with immutability triggers. Tests (lifecycle rules, immutability). _(R2, R3, R4)_
- [x] T3. Service: grant, revoke, simulated_read (contributor lock), `ledger_read` command. Tests (refusal without grant, expired, revocation immediate, other categories still work). _(R3, R5)_
- [x] T4. `verify_ledger`: CIDs, chain, activity, units, record CIDs. Tamper tests. _(R4)_
- [x] T5. Statement: rows and totals, CID, page and JSONL download; no currency field. Tests. _(R6)_
- [x] T6. UI: Permissions page (categories with counts, grant, revoke with confirmation), Statement page, nav; budget and no-external tests. _(R1, R7)_
- [x] T7. Export/import with chain check, backup counts (old sets still verify), DATA_MODEL; round-trip and no-network tests. _(R8, R9)_
- [ ] T8. DECISIONS, docs, local gate, PR into `develop`, one review, merge, report 012. _(R11)_
