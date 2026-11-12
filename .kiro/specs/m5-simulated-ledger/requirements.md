# M5 Simulated ownership ledger — Requirements

Nymbus layer 6, simulated. Source: planner message 022 (2026-11-12). M5 closes Nymbus phase 1.

Goal: prove that the owner controls who may use each category of his data, and that every use is
recorded and verifiable, before any real party or money is involved.

- **R1 Categories:** each module manifest (M4) declares the data categories it owns (e.g.
  body_composition, cognitive_probes, work_focus, training_load, backup_meta). A category list page
  shows them, with record counts.
- **R2 Grants:** a Grant is an immutable, CID-addressed record: category, recipient (simulated only:
  "self-analysis", "sim-research-partner"), purpose (free text, required), start, optional end.
  Revocation writes a Revocation record that supersedes the grant; nothing is edited or deleted.
- **R3 Access events:** a simulated recipient reads data only through an internal service that checks
  an active grant first. Each read writes an append-only AccessEvent: grant CID, recipient, purpose,
  list of record CIDs read, timestamp, units.
- **R4 Tamper evidence:** each AccessEvent stores the SHA-256 of the previous event (hash chain).
  `manage.py verify_ledger` recomputes the chain and every record CID; any break fails loudly. A DB
  constraint or trigger stops AccessEvent rows from being updated or deleted.
- **R5 Revocation works immediately:** a test revokes one category and proves that the very next
  simulated read is refused and writes no event, while other categories still work and old events
  stay readable.
- **R6 Deposit statement:** per month, per category: records accessed, by which recipient, for what
  purpose, simulated units. Shown as a page and downloadable as JSON Lines with its own CID. Units are
  labelled "simulated credits"; there is no currency field anywhere.
- **R7 UI:** a Permissions page with per-module, per-category grant and revoke controls (confirmation
  on revoke), and a Statement page. Phone-friendly, same budgets and no-external-request rules as M4.
- **R8 Export:** export_my_data includes grants, revocations and access events; import verifies the
  hash chain.
- **R9 Out of scope (owner gate):** real recipients, real money or payouts, multi-person data, any
  network sharing. A test asserts there is no outbound network call in the ledger code.
- **R10 Tests:** grant/revoke lifecycle; refusal without grant; expired grant; hash-chain break
  detection; statement totals; export/import round trip; immutability constraint; no-network
  assertion.
- **R11 Done when** R1-R10 pass the local gate, DECISIONS records the choices, the PR is merged into
  develop on green, and report 012 is written.
