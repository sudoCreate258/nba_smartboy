---
inclusion: always
---

# Nymbus — the architecture this repo implements

Source of truth: "Nymbus — Reference Architecture" (owner's doc,
https://claude.ai/artifact/LBJGwb5S85eo7Hp9S12SS3). Kiro cannot open it; this
file carries the parts that constrain code. If this file and the doc disagree,
the doc wins — log the conflict in `docs/DECISIONS.md` and stop.

## Relationship
Nymbus is the shared architecture. This repo (the Digital Twin / fitness AI
venture) is its first use case and its reference implementation for one person.

## Six shared layers (one data path, top to bottom)
1. **Capture** — ingestion adapters (today: YAML from the screenshot parser;
   next: direct exports/APIs).
2. **Storage and compliance** — HIPAA-style data lake; decorator → facade →
   Clean Architecture over Thrift RPC (phase 2+).
3. **Integrity** — SipHash-2-4 for exact duplicates; pHash for re-encoded
   near-duplicates (media).
4. **Provenance** — every record gets a content ID (CID) linking it to its contributor.
5. **Shared learning** — FedAvg + DP-SGD, no pooling of raw member data (phase 3).
6. **Ownership and payout** — usage events metered and paid to contributors
   via the cooperative (Rakuteen lineage).

**One CID per record is the key across every layer** (Redis key, SDN flow key,
Nginx hash key, audit log ID, proposed payout-ledger key). Never introduce a
second record identifier that other layers would have to join on.

## What a use case must supply
An ingestion adapter, a domain schema, and a definition of "usage" for payout.

## Nymbus phases and gates
1. **One person** — Digital Twin with direct data import, CID provenance,
   simulated payout ledger. *Gate: every record traceable; payout math reconciles.*
2. **First use case, central storage** — few contributors, HIPAA-style controls.
   *Gate: dedup + provenance hold with several contributors; real usage events trigger payouts.*
3. **Federation** — FedAvg + DP-SGD. *Gate: recall loss vs phase 2 measured and accepted.*
4. **Cooperative and crypto settlement** — *Gate: legal/regulatory review done.*
5. **More use cases** via adapters.

This repo is in **Nymbus phase 1**. Do not build phase 2+ features.

## Rules for code now
- Domain logic (canonicalization, CID, ledger math) lives in plain Python
  modules with no Django imports, so it can move behind the Nymbus storage
  layer later.
- Records are immutable once they have a CID. Corrections are new records.
- Every record has a contributor, even with one contributor.
- Payout is simulated only: units, not money or tokens.
