# M4.5 Encrypted off-hours backup — Requirements

(Planner message 021.)

## Goal
The owner's data survives loss of this machine, and nothing readable leaves it.

### R1 What is backed up, per run, in one dated set
- `pg_dump -Fc` of the twin database;
- `export_my_data` JSON Lines (self-verifying, from M4-T6);
- `data/inbox/` is NOT included by default; opt-in flag `BACKUP_INCLUDE_INBOX=1`;
- a `manifest.json`: timestamp (UTC), git commit, app version, file names, byte sizes, SHA-256 of each file, record counts per type.

### R2 Encryption
Client-side with rclone crypt (file names and contents encrypted). Plain bytes never reach the remote.

### R3 Tooling
Official images only: `alpine:3.20` with `apk add rclone postgresql16-client`, or the existing `postgres:16` image for pg_dump. No third-party namespaced images.

### R4 Secrets stay out of git
The rclone config lives outside the repo and is mounted read-only (path from `RCLONE_CONFIG_HOST` in `.env`). `.gitignore` covers `rclone.conf` and `backups/`. A hygiene test fails if any rclone.conf, crypt password or token is tracked.

### R5 The owner connects the remote
Google Drive first, but any rclone remote works. The builder never runs OAuth or `rclone config` and never handles the crypt password; OPERATIONS.md gives the owner the exact steps (create the drive remote, then a crypt remote on top of it, with password and salt).

### R6 Off-hours
An opt-in Compose profile `backup` runs a small loop that does one backup per night inside `BACKUP_WINDOW` (default 02:00-05:00 local). Also `manage.py backup_now` for a manual run. If the machine is asleep through the window, the next wake inside or after the window runs it once (catch-up), never twice a night.

### R7 Retention on the remote
Keep the last 7 daily and last 4 weekly sets; delete older sets only after the new set is uploaded and verified.

### R8 Verify every run
Download the new set from the remote, decrypt, check SHA-256 against the manifest, restore the dump into a scratch database, run import_my_data verification (CIDs recompute identically), drop the scratch database. A failed verify keeps the previous sets untouched and is reported.

### R9 Status in the app
Home page shows last successful backup time, set size and verify result; amber when older than 48 h, red when older than 7 days or the last verify failed. Read-only API field in `/api/v0/today`.

### R10 Restore runbook
In OPERATIONS.md: fresh machine to running twin from the latest set, tested once end to end by the builder using a local rclone crypt remote.

### R11 Tests (no network)
rclone `local` backend wrapped in crypt inside the test container; round trip backup, verify, restore; retention selection unit tests (daily/weekly edges, DST change); window and catch-up logic; manifest hash mismatch detected; hygiene test from R4.

### R12 Done when
All of R1-R11 pass the local gate, DECISIONS records the choices, PR merged into develop on green, report 011 written.

## Out of scope
Multi-person backup, P1.5 OurData shared storage, any cloud API other than through rclone.
