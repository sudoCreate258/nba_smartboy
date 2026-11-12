# M4.5 Encrypted off-hours backup — Tasks

Branch `feature/m4-5-encrypted-backup` from `develop`, after M4 (PR #10) is merged.

- [ ] T1. Tooling: rclone and pg_dump/pg_restore 16 in the image; `backup` Compose profile; `.env.example` variables; `.gitignore` rclone.conf; hygiene test. _(R3, R4, R6)_
- [ ] T2. `backup/schedule.py` (window, catch-up) and `backup/retention.py` (7 daily, 4 weekly) in plain Python + unit tests incl. DST. _(R6, R7, R11)_
- [ ] T3. Runner: dump, export, optional inbox, manifest, upload through crypt, verify (download, SHA-256, scratch restore, CIDs), prune, `BackupRun` log. Round-trip tests with a local crypt remote; hash mismatch detected. _(R1, R2, R7, R8, R11)_
- [ ] T4. `backup_now` and `backup_loop` commands. Tests. _(R6)_
- [ ] T5. Status on the home page and in `/api/v0/today` (amber > 48 h, red > 7 days or failed verify). Tests. _(R9)_
- [ ] T6. OPERATIONS.md: owner remote setup (drive + crypt) and restore runbook; builder end-to-end restore test with a local crypt remote. _(R5, R10)_
- [ ] T7. DECISIONS, local gate, PR into `develop`, one review, merge, report 011. _(R12)_
