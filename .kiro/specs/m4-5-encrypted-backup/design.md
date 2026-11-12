# M4.5 Encrypted off-hours backup — Design

- **Tooling in the web image (R3):** `python:3.12-slim` (official, Debian 13) gets `rclone` from Debian and
  `pg_dump`/`pg_restore` 16 copied from the official `postgres:16` image (same Debian release), so dumps
  match the 16 server exactly (Debian's client is 17, whose dumps can carry settings a 16 server rejects).
  The backup needs Django anyway (export, CID verification), so one image does it all; no second Python
  environment on alpine.
- **New Django app `backup`:** plain-Python schedule and retention logic (no Django imports), a runner
  (dump, export, manifest, upload, verify, prune), a `BackupRun` log table (configuration/log, no CID),
  `backup_now` and `backup_loop` commands.
- **Remote:** `BACKUP_REMOTE` names an rclone crypt remote (e.g. `twin-crypt:`); sets go to
  `<remote>sets/<UTC timestamp>/`. rclone config is mounted read-only from `RCLONE_CONFIG_HOST`
  into the `backup` service only (`RCLONE_CONFIG=/run/secrets/rclone.conf`).
- **Compose profile `backup`:** a `backup` service from the same image runs `manage.py backup_loop`
  (checks every few minutes; `docker compose --profile backup up -d backup`).
- **Schedule (R6):** a night starts at the window start (local). A run is due when the last attempt is
  before the most recent window start, so a missed window runs once on the next wake, never twice a
  night. Window times are local; DST handled with zoneinfo.
- **Retention (R7):** keep the newest set of each of the last 7 local days with sets, and the newest
  set of each of the last 4 ISO weeks with sets; prune only after the new set verified.
- **Verify (R8):** fresh download through crypt into a temp dir, SHA-256 against the downloaded
  manifest, `pg_restore` into a scratch database, every export line self-verifies and the set of CIDs
  in the export equals the set of CIDs in the restored database, scratch database dropped.
- **Status (R9):** home page and `/api/v0/today` read the latest `BackupRun` rows.
