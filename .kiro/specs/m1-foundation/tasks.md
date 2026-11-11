# M1 Foundation + Provenance — Tasks

- [ ] T0. Owner decision: choose license (Apache-2.0 or AGPL-3.0). Builder adds `LICENSE` only after the owner decides.
- [x] T1. Init repo: `git init`, `.gitignore` (Python, `.env`, `data/inbox/`), `.gitattributes` (`* text=auto eol=lf`), `README.md` with run steps.
- [x] T2. `requirements.txt`, `Dockerfile`, `docker-compose.yml` (web + db with healthcheck), `.env.example`. Verify `docker compose up -d --build` starts both. _(R1)_
- [x] T3. Django project `twin` + app `core`; settings from env; `migrate` runs clean; superuser steps in README. _(R1)_
- [x] T4. `nymbus/provenance.py` (canonical bytes + CIDv1) with unit tests: determinism, change-sensitivity, fixed expected CIDs, format (`b` prefix, base32). _(R3)_
- [x] T5. `Contributor` + data migration for `mike`; abstract `ProvenancedRecord` with immutability and supersede chain. Tests. _(R2, R3)_
- [x] T6. `DailySnapshot` + admin (read-only, "Save as correction") + post-sauna validation. Tests. _(R4)_
- [x] T7. `ProbeSession`, `WorkBlock` + admin; WorkBlock validation. Tests. _(R5, R6)_
- [ ] T8. `ingest_yaml` command: atomic, unknown-key rollback, CID skip, supersede on change, summary output. Tests with a sample YAML fixture. _(R7)_
- [ ] T9. GitHub Actions CI with postgres service; badge in README. _(R8)_
- [ ] T10. Write the M1 status into `docs/DECISIONS.md` (shipped / issues / open questions) for the planner.
