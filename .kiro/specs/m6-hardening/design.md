# M6 Hardening — Design

- **Immutability (R1):** migration `core/0011` adds `BEFORE UPDATE OR DELETE` row triggers (function
  `core_refuse_change`) on the eight record tables and `core_supersession`; the ledger tables already have theirs
  (`ledger/0002`). Tests that simulate a fresh database use TRUNCATE (the database owner's tool, not a row change).
  Supported bypass: none for normal use; restore replaces tables (`pg_restore --clean` drops and recreates them).
  An emergency repair by the database owner (`ALTER TABLE ... DISABLE TRIGGER` in one transaction) is documented
  as outside normal use, and `verify_ledger` and the CID checks show its traces.
- **Ledger anchoring (R2):** `ledger.verify.head(contributor)` = events count, SHA-256 of the last event (64 zeros
  when none), plus grant and revocation counts. Every backup manifest carries `ledger_heads` per contributor; the
  `BackupRun` row of a published set keeps a copy (migration `backup/0003`). `verify_ledger` compares the live head
  with the newest published backup's head, and with a downloaded manifest given by `--manifest` (the copy outside
  the database): fewer events, a different event at the anchored position, or fewer grants/revocations fail. The
  Statement page shows the live head and the newest anchor.
- **Scanning (R3, changed by the planner):** Trivy is not in Alpine 3.20 stable, so `osv-scanner` 1.6 from Alpine
  3.20 runs in `alpine:3.20` (no edge/testing packages, no Docker socket). `scripts/scan.sh`: requirements.txt, and
  the web image read from a `docker save` tar mounted read-only (`tools/image_packages.py` reads the Debian package
  database and installed Python distributions out of the layers). `tools/scan_report.py` (stdlib) decides: Debian
  advisories for the image's release only, dpkg version order, severity from GitHub / CVSS v3 / Debian urgency,
  fails on fixable HIGH/CRITICAL not in the reviewed `scan-ignore.txt`; unfixed ones are listed. `scripts/scan.ps1`
  locally, a `scan` job in CI. The Dockerfile upgrades Debian packages at build time.
- **Web checks (R4):** a small CSP middleware (`default-src 'self'`, `frame-ancestors 'none'`, `base-uri`,
  `form-action`, `object-src 'none'`), `X-Content-Type-Options`, `Referrer-Policy`, `X-Frame-Options DENY`;
  secure cookies, HSTS and `check --deploy` cleanliness when HTTPS is on. Tests: headers on every page,
  `check --deploy` in an HTTPS environment (subprocess), CSRF refusal and session-cookie flags. DECISIONS: ZAP awaits
  an owner decision.
- **LAN HTTPS (R5):** opt-in Compose profile `https`: service `web-https` runs gunicorn with TLS (pinned pip
  package) on `${TWIN_HTTPS_HOST}:8443`, with `TWIN_HTTPS=1` (secure cookies, HSTS, CSRF trusted origin). The owner
  runs `scripts/lan-cert.ps1` (openssl from `alpine:3.20`), which creates a local CA and a server certificate for the
  LAN address into the gitignored `certs/` folder; the builder never sees the owner's CA key. README: trust the CA on
  Android and iOS. Test: gunicorn with a throwaway self-signed certificate serves the pages, the service worker
  and the manifest over TLS with HSTS.
- **Signed images (R6):** `scripts/sign-image.ps1` builds the web image with an OCI version label, writes the image
  ID and version to a statement file and signs it with cosign 2.2 (`alpine:3.20`) using the owner's key from
  `COSIGN_KEY_DIR` (outside the repo), offline (no transparency-log upload). `-Verify` checks a statement against
  the image present. No key: prints "SKIPPED: no signing key" and exits 0.
- **Updates (R7):** `.github/dependabot.yml` (pip and GitHub Actions, weekly, target `develop`);
  `scripts/update.ps1` (pull --ff-only, rebuild, migrate, gate).
- **ARM (R8):** documented and deferred in DECISIONS.
- **PORTING.md (R9):** the record format, CID, supersession, ledger chain, export and statement formats, with test
  vectors (3 records + CIDs, a 3-event chain + head) that a test recomputes.
