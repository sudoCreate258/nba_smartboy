# M6 Hardening — Tasks

Branch `feature/m6-hardening` from `develop`, after M5 (PR #12) is merged.

- [ ] T1. Database immutability triggers on every record table and Supersession; tests switch to TRUNCATE; bypass documented. _(R1)_
- [ ] T2. Ledger head in backup manifests, BackupRun and the Statement page; verify_ledger compares (newest backup, `--manifest`). Tests. _(R2)_
- [ ] T3. Vulnerability gate: osv-scanner from Alpine 3.20, image read from a `docker save` tar, `scan_report.py`, ignore file, local script and CI job; Dockerfile upgrades packages. Tests for the stdlib tools. _(R3)_
- [ ] T4. Security headers (CSP middleware), HTTPS settings, `check --deploy`, CSRF/session tests; ZAP note. _(R4)_
- [ ] T5. LAN HTTPS: `https` profile with gunicorn TLS, `lan-cert.ps1`, README phone steps, TLS test with a self-signed cert. _(R5)_
- [ ] T6. Signed images (cosign, skip without a key), Dependabot, `update.ps1`, ARM note. _(R6, R7, R8)_
- [ ] T7. docs/PORTING.md with test vectors and a test that recomputes them. _(R9)_
- [ ] T8. DECISIONS, docs, local gate, PR into `develop`, one review, merge, report 013. _(R10)_
