# M6 Hardening — Requirements

Source: planner message 023 (2026-11-12). Last milestone of Nymbus phase 1; after it, STOP for an owner review
before any phase 2 work.

- **R1 Database immutability:** PostgreSQL triggers refuse UPDATE and DELETE on every record table and on
  Supersession, Grant, Revocation and AccessEvent. Migrations create them; a test proves a raw SQL update fails.
  Document the one supported bypass (none for normal use).
- **R2 Ledger anchoring:** ledger head (hash + count) in each backup manifest and on the Statement page;
  verify_ledger compares the live head with the newest backup and reports a shorter or different chain.
- **R3 Dependency and image scanning (as corrected by the planner, 2026-11-12):** scanners from Alpine 3.20
  stable only (grype or osv-scanner; no edge or testing packages; Trivy is not in 3.20), never mounting the Docker
  socket. Scan dependencies from requirements.txt, and scan the web image from a `docker save` tar mounted
  read-only. A local script and the CI job fail on HIGH/CRITICAL with a reviewed ignore file. No third-party
  namespaced images. Record the substitution for Trivy in DECISIONS.
- **R4 Web scan:** ZAP is only available as a namespaced image (zaproxy/...), which our rule excludes. Do NOT use
  it. Instead add Django's `check --deploy`, a header test (CSP, HSTS when HTTPS, X-Content-Type-Options,
  Referrer-Policy, frame-ancestors) and a CSRF/session test pass. Write in DECISIONS that ZAP awaits an owner
  decision.
- **R5 LAN HTTPS (fixes the M4 limit):** opt-in HTTPS for LAN mode with a local certificate authority created by
  the owner (mkcert from Alpine packages, or openssl); the builder never handles the CA private key beyond
  generating it into a gitignored folder on the owner's machine; README steps to trust the CA on a phone. Service
  worker and install work over HTTPS; test with a self-signed cert in CI.
- **R6 Signed images:** build the web image locally with a version label; sign and verify with cosign (Alpine
  package) using a key the owner creates and keeps outside the repo; document verify steps. If no key is present,
  the step is skipped with a clear message, never fails silently.
- **R7 Updates:** Dependabot (or Renovate config) for pip and GitHub Actions, weekly, PRs into develop only; an
  `update.ps1` that pulls, rebuilds, migrates and runs the gate.
- **R8 ARM images:** document only; building multi-arch needs a non-official binfmt image, so defer and record in
  DECISIONS.
- **R9 Stack-agnostic guide:** docs/PORTING.md describing the record format (canonical JSON, CIDv1),
  supersession, ledger chain and export format well enough to reimplement in another stack, with test vectors
  (3 records + their CIDs, a 3-event chain + head hash).
- **R10 Done when** R1-R9 pass the local gate, DECISIONS updated, PR merged into develop on green, report 013
  written.
