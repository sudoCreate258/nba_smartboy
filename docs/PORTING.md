# Porting guide: the record format in any stack

This is what another implementation (any language, any database) must do to read, write and verify
the same data as this one: same bytes, same CIDs, same history, same ledger. Field lists and per-type
rules are in `docs/DATA_MODEL.md` (generated from the code); this guide is the cross-cutting contract.
The test vectors at the end are checked against the code by `tests/test_porting.py`.

## 1. Canonical bytes

A record is hashed as one JSON object:

```json
{"contributor": "<handle>", "fields": {...}, "kind": "<record kind>"}
```

- Keys sorted (at every level), separators `,` and `:` with no spaces, UTF-8, non-ASCII characters
  written as themselves (not `\u` escapes). In Python: `json.dumps(payload, sort_keys=True,
  separators=(",", ":"), ensure_ascii=False).encode("utf-8")`.
- `fields` holds every content field of the record. Not content: `id`, `cid`, `contributor` (its
  handle is in the envelope), `created_at`, `created_seq`.
- Values before hashing:
  - date-times: converted to UTC, ISO 8601 with offset `+00:00` (`2026-11-10T12:00:00+00:00`;
    microseconds appear when non-zero). A date-time without a time zone is an error, never guessed.
  - dates: `YYYY-MM-DD`; times: `HH:MM:SS`.
  - decimals: a string with exactly the field's decimal places (`"96.5"` for one place, `"0.40"` for
    two, `"2.40"`): `97.8`, `"97.8"` and `97.80` must all give `"97.8"`.
  - integers and booleans as JSON numbers/booleans; empty text as `""`; missing values as `null`.
  - `OMIT_IF_NULL` fields (listed per type in DATA_MODEL) are left out entirely while null, so
    records made before the field existed keep their CID. Every other null is written as `null`.
  - Type-specific normalisation happens before hashing (e.g. a training set's `exercise` is
    lower-cased, trimmed and inner whitespace collapsed).

## 2. CID

`CID = "b" + base32lower_nopad(0x01 0x55 0x12 0x20 || sha256(canonical bytes))`: CIDv1, raw codec
(0x55), sha2-256 multihash (0x12, length 0x20). Identical content always gives the same CID, so a
duplicate is detected by CID equality, and the CID is the only identifier other layers may use.

## 3. Immutability and corrections

- A stored record never changes. A correction is a new record plus a `supersession` event
  `{old_cid, new_cid, reason}` (same kind, same contributor, `old_cid != new_cid`).
- A record is **current** when the most recent supersession touching its CID (as old or new) has it
  as `new_cid`, or when no supersession touches it. So a revert A -> B -> A makes A current again
  without a new record.
- References by CID (a reset's probes, a set's session) follow correction chains: a CID that was
  corrected resolves to the current end of its chain (follow `old_cid -> new_cid`, latest event per
  `old_cid`, at most 50 steps).
- Order of creation is a single counter across all record types, corrections and the ledger; never
  derive it from wall-clock times (a clock can step back).

## 4. Ledger (simulated ownership, layer 6)

Three more record kinds, hashed and identified exactly like data records:

- `grant`: `{category, recipient, purpose, start, end}`. Recipients (phase 1): `self-analysis`,
  `sim-research-partner`. Active when `start <= t < end` (no `end` = open) and `t <` its revocation's
  `at`. At most one grant in force per (contributor, recipient, category): grants may not overlap in
  time (each one's time runs until its `end` or revocation).
- `revocation`: `{grant_cid, at, reason}`, at most one per grant.
- `access_event`: `{seq, at, grant_cid, recipient, category, purpose, record_cids, units, prev_hash}`.
  `recipient`, `category` and `purpose` equal the grant's; the grant is active at `at`;
  `units = len(record_cids)` (one simulated credit per record read; never money);
  `record_cids` are CIDs of existing records of the category's kinds.
- **Chain:** per contributor, `seq` is 1, 2, 3, ...; `prev_hash` of event 1 is 64 zeros; of event n
  it is the lowercase hex SHA-256 of event n-1's canonical bytes (the same digest its CID carries).
- **Head:** `{"events": n, "last_hash": <sha256 of event n, or 64 zeros>}` (backups add grant and
  revocation counts). A later ledger must extend an earlier head: at least as many events, and event
  `events` must hash to `last_hash`.
- A refused read (no active grant) writes nothing.

Category of each kind (phase 1): `daily_snapshot` -> `daily_metrics`, `weekly_check` -> `wellbeing`,
`probe_session` -> `probes`, `work_block` and `reset` -> `work`, `discomfort_check` -> `discomfort`,
`training_session` and `training_set` -> `training`.

## 5. Export / import (nymbus-jsonl v1)

One JSON object per line, UTF-8. Line 1 is the header `{"type": "export", "format": "nymbus-jsonl",
"version": 1, "contributor", "timezone", "exported_at"}`; then records
`{"type": "record", "kind", "cid", "contributor", "fields", "created_at"}` and corrections
`{"type": "supersession", "old_cid", "new_cid", "reason", "created_at"}` in creation order, then the
ledger records in replay order (events by `seq`; before each event every grant and revocation whose
`start`/`at` is not after the event's `at`, a revocation before a grant at equal times).

An importer must: refuse a destination that already has records for the contributor; check every
line's CID against its own `fields`; replay lines in file order with the same validation as a live
write (so references and corrections resolve as they did); check each access event's `seq` and
`prev_hash` against the previous one; after the last line, verify the whole ledger (activity at each
read, record references, overlaps); and commit nothing if anything fails. `created_at` is
informational.

## 6. Deposit statement (nymbus-statement-jsonl v1)

For one local month (the contributor's time zone): header `{"type": "statement", "format":
"nymbus-statement-jsonl", "version": 1, "contributor", "timezone", "month", "unit": "simulated
credits", "cid"}`, then rows `{"type": "row", "category", "recipient", "purpose", "reads",
"records_accessed", "distinct_records", "units"}` sorted by (category, recipient, purpose), then
per-category totals. `cid` is the CID of `canonical("deposit_statement", contributor, {"month",
"timezone", "unit", "rows"})` with the rows as listed (without `type`).

## 7. Checklist for a port

1. Reproduce the record CIDs below byte for byte (canonical bytes first, then the CID).
2. Reproduce the grant CID, the three event hashes and the head.
3. Import an export from this implementation and export it again: every CID and supersession pair
   must be unchanged.
4. Run the ledger checks (chain, activity, units, record references) on the imported data.

## Test vectors

<!-- vectors: generated by `python tools/porting_vectors.py`; tests/test_porting.py checks them -->

### Records

**daily_snapshot** (contributor `mike`)

Canonical bytes (UTF-8):

```json
{"contributor":"mike","fields":{"bedtime":null,"bia_timing":"unknown","bmr_kcal":null,"body_fat_pct":null,"date":"2026-11-10","hrv":61,"notes":"","resting_hr_sleep":52,"skeletal_muscle_kg":null,"sleep_duration_min":450,"sleep_score":80,"source":"manual","spo2":"96.5","wake_time":"2026-11-10T12:00:00+00:00","weight_kg":null},"kind":"daily_snapshot"}
```

CID: `bafkreiawramgpvre3be2wcrg326x7mfnxyfzcntq3efmrbmca6mpy7rrqa`

**probe_session** (contributor `mike`)

Canonical bytes (UTF-8):

```json
{"contributor":"mike","fields":{"accuracy_pct":"80.0","blunders":1,"fast_blunders":1,"kind":"mini_puzzle","late_blunders":0,"location":"office","median_solve_s":"12.5","move_time_cv":"0.40","n_items":5,"notes":"","opponent_rating":null,"own_rating":null,"started_at":"2026-11-10T13:50:00+00:00","time_control":null},"kind":"probe_session"}
```

CID: `bafkreidmwikeayfhnmkebxr2ua2xqagc6khmpkw4anqkqonkfluxkq73fi`

**weekly_check** (contributor `mike`)

Canonical bytes (UTF-8):

```json
{"contributor":"mike","fields":{"instrument":"OLBI","notes":"","scale_max":"4.00","score":"2.40","week_start":"2026-11-09"},"kind":"weekly_check"}
```

CID: `bafkreigfid2pmd64vvob3fcxafm5g7lmzf322kbfuw3miqhbxpyl7yetiu`

### Grant and a 3-event chain

Grant canonical bytes:

```json
{"contributor":"mike","fields":{"category":"probes","end":null,"purpose":"fatigue study","recipient":"sim-research-partner","start":"2026-11-10T14:00:00+00:00"},"kind":"grant"}
```

Grant CID: `bafkreiatsorh4icmkq6xqu3ibupjpmayhhwnjfgz7ghoaqam5jbzlkb3z4`

Event 1 canonical bytes:

```json
{"contributor":"mike","fields":{"at":"2026-11-10T15:00:00+00:00","category":"probes","grant_cid":"bafkreiatsorh4icmkq6xqu3ibupjpmayhhwnjfgz7ghoaqam5jbzlkb3z4","prev_hash":"0000000000000000000000000000000000000000000000000000000000000000","purpose":"fatigue study","recipient":"sim-research-partner","record_cids":["bafkreidmwikeayfhnmkebxr2ua2xqagc6khmpkw4anqkqonkfluxkq73fi"],"seq":1,"units":1},"kind":"access_event"}
```

SHA-256: `df69516ec841bb8ec2913b498d83adbf6177980439e0f63fd66ba4cfaffedf55`  
CID: `bafkreig7nfiw5scbxohmfej3jggyhln7mf3zqbbz4d3d7vtluth277w7ku`

Event 2 canonical bytes:

```json
{"contributor":"mike","fields":{"at":"2026-11-11T15:00:00+00:00","category":"probes","grant_cid":"bafkreiatsorh4icmkq6xqu3ibupjpmayhhwnjfgz7ghoaqam5jbzlkb3z4","prev_hash":"df69516ec841bb8ec2913b498d83adbf6177980439e0f63fd66ba4cfaffedf55","purpose":"fatigue study","recipient":"sim-research-partner","record_cids":["bafkreidmwikeayfhnmkebxr2ua2xqagc6khmpkw4anqkqonkfluxkq73fi"],"seq":2,"units":1},"kind":"access_event"}
```

SHA-256: `bd930518054666d553f6a11f6bb57d237943bc7d116dff10b3532672fc4e04b0`  
CID: `bafkreif5smcrqbkgm3kvh5vbd5v3k7jdpfb3y7irnx7rbm2tezzpytqewa`

Event 3 canonical bytes:

```json
{"contributor":"mike","fields":{"at":"2026-11-12T15:00:00+00:00","category":"probes","grant_cid":"bafkreiatsorh4icmkq6xqu3ibupjpmayhhwnjfgz7ghoaqam5jbzlkb3z4","prev_hash":"bd930518054666d553f6a11f6bb57d237943bc7d116dff10b3532672fc4e04b0","purpose":"fatigue study","recipient":"sim-research-partner","record_cids":[],"seq":3,"units":0},"kind":"access_event"}
```

SHA-256: `7732f0ec2cc4b76efa844818838fb65a90f34b62bbf66314717bb0d140d737f9`  
CID: `bafkreidxglyoylgew5xpvbcidcby7ns2sdzuwyv36zrri4l3wdiubvzx7e`

Head after the three events:

```json
{"events": 3, "last_hash": "7732f0ec2cc4b76efa844818838fb65a90f34b62bbf66314717bb0d140d737f9"}
```
<!-- /vectors -->
