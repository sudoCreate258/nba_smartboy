# Operations

Running the twin on Windows with Docker Desktop. Commands are PowerShell, from the repository folder.

## First setup

1. Install Docker Desktop and Git for Windows.
2. Clone the repository and create `.env` from the example:

   ```powershell
   copy .env.example .env
   ```

   Set your own values in `.env` (it is gitignored):
   - `POSTGRES_PASSWORD`: a password of your own (Compose refuses to start without it).
   - `DJANGO_SECRET_KEY`: required when `DJANGO_DEBUG` is not `1`. Generate one with:
     `docker compose run --rm web python -c "from django.core.management.utils import get_random_secret_key as k; print(k())"`
   - `DJANGO_DEBUG=1` is for local development only.
3. Start, migrate and create the admin user:

   ```powershell
   docker compose up -d --build
   docker compose exec web python manage.py migrate
   docker compose exec web python manage.py createsuperuser
   ```

4. Open http://localhost:8000/admin/. The port is bound to this computer only.
5. Optional, for contributors: `powershell -File scripts/install-hooks.ps1` installs the pre-push hook (local CI gate).

The database lives in the Docker volume `<folder>_pgdata`, where `<folder>` is the name of the repository folder (Compose names the project after it; `docker volume ls` shows it). `docker compose down` keeps it; `docker compose down -v` deletes it.

## Importing data

Put real files in `data/inbox/` (gitignored; the folder is mounted at `/app/data/inbox` in the container).

```powershell
docker compose exec web python manage.py ingest_yaml data/inbox/snapshots.yaml
docker compose exec web python manage.py ingest_training_csv data/inbox/training.csv
```

Each file is imported in one transaction; an error names the record or line and nothing is written. Re-importing a file only adds what is new. Formats: README sections "Probe log", "Work and zone", "Training log".

## My data export

```powershell
docker compose exec web python manage.py export_my_data --out data/inbox/my-data.jsonl
docker compose exec web python manage.py import_my_data data/inbox/my-data.jsonl   # on a fresh instance
```

JSON Lines with every record and correction (format: `docs/DATA_MODEL.md`, "Export format"). The app's Recent page has the same "Download my data" button. Import refuses a database that already has records for the contributor, and checks every CID.

## Phone checklist (manual)

The test suite checks the server side of the phone app and that the scripts parse; it does not run them in a browser. After changes to `ui/static/ui/offline.js` or `ui/templates/ui/sw.js`, check on a real phone (target: Chrome on Android 8+, Safari on iOS 14+) and on the computer's browser:

1. Log in. Today, Check in, Trends, Recent and Modules load; the page is readable without zooming.
2. Submit a discomfort check: you return to Today with "saved".
3. Stop the instance (`docker compose stop web`), submit a check-in: "saved on this phone" appears and the status line counts it. Start the instance (`docker compose start web`) and reopen the app (or wait a minute): the count drops to zero and Recent shows the check-in once.
4. Repeat step 3, then log out and log in again before restarting the instance: the queued check-in is still sent once (fresh CSRF token).
5. Queue a correction of a record, correct the same record online, then let the queue send: the queued item is listed as "could not be saved: ... already corrected" and later items still send.
6. On `http://localhost:8000/` only: install to the home screen, view Trends, go offline, reopen Trends (cached copy), log out, go offline again: Trends is no longer available offline.
7. In LAN mode (`http://<address>:8000/` on the phone): steps 1-5 work; install and offline pages are not offered (plain HTTP; HTTPS is M6).

## Encrypted backup

Off-hours backups push an encrypted copy of your data to a remote you choose (first target: Google Drive). The remote only ever holds ciphertext; the key stays on this computer. rclone's `crypt` encrypts file names and contents before upload. Losing the key means losing the backup, so keep a copy of the crypt password and salt somewhere safe (a password manager).

### Connect a remote (once; you do this, not the app)

rclone runs OAuth and holds the key, so set it up yourself. Install rclone (https://rclone.org/downloads/) and:

1. `rclone config` -> `n` -> name it `gdrive` -> type `drive` -> follow the browser sign-in. This is the storage remote.
2. `rclone config` -> `n` -> name it `twin-crypt` -> type `crypt`:
   - `remote`: `gdrive:twin-backup` (a folder on the drive remote),
   - `Encrypt the filenames`: `standard`,
   - choose `Encrypt directory names`,
   - enter your own password, and a salt (password2). **Write both down**; they are not stored in the repo.
3. Note where rclone saved its config: `rclone config file`.
4. In `.env`:
   - `RCLONE_CONFIG_HOST=` that config file's full path (e.g. `C:/Users/you/AppData/Roaming/rclone/rclone.conf`),
   - `BACKUP_REMOTE=twin-crypt:`
5. Start the backup service: `docker compose --profile backup up -d backup`. It backs up once a night inside `BACKUP_WINDOW` (default 02:00-05:00 local), catching up after the machine was asleep.

Back up on demand: `docker compose run --rm backup python manage.py backup_now`. Today (and `/api/v0/today`) show the last backup time, size and verify result.

Each run uploads a set (database dump, your data export, a manifest), then verifies it by downloading it again, checking SHA-256, restoring the dump into a scratch database and confirming every CID matches the export. It keeps the last 7 daily and 4 weekly sets, deleting older ones only after the new set verifies. `data/inbox/` is not backed up unless `BACKUP_INCLUDE_INBOX=1`.

### Restore onto a fresh machine

1. Set up the twin (First setup above) and the same `twin-crypt` remote with the same password and salt, in `.env`.
2. `docker compose up -d --build` and `docker compose exec web python manage.py migrate` (an empty database).
3. Restore the latest set:

   ```powershell
   docker compose run --rm backup python manage.py restore_backup --set latest --yes
   ```

   It downloads and decrypts the set, checks the hashes, restores the dump over the database, and confirms every record's CID matches the export. Then `docker compose exec web python manage.py migrate` (a no-op when the code matches the backup).
4. Check: `docker compose exec web python manage.py probe_report` runs and the records are there.

To restore a specific set, use its name (from `docker compose run --rm backup rclone --config /run/secrets/rclone.conf lsf twin-crypt:sets/`) instead of `latest`.

## Running reports

```powershell
docker compose exec web python manage.py probe_report
docker compose exec web python manage.py zone_report --weeks 4
docker compose exec web python manage.py training_report --weeks 4 --json
```

All take `--contributor` (default `mike`) and `--json`; `zone_report` and `training_report` also take `--weeks` and `--until YYYY-MM-DD` (the whole local week containing that date is the last one shown). Reports only read.

## Backup and restore

Backups are manual today; encrypted off-hours backups are planned (M4.5).

The dump is written inside the database container and copied out with `docker compose cp`, so the file is byte-exact (PowerShell redirection would re-encode it).

Back up (a plain SQL dump; it contains your health data, so store it like the database itself):

```powershell
$name = "twin-$(Get-Date -Format yyyy-MM-dd).sql"
docker compose exec -T db sh -c "pg_dump -U `$POSTGRES_USER -d `$POSTGRES_DB --clean --if-exists -f /tmp/$name"
New-Item -ItemType Directory -Force backups | Out-Null
docker compose cp "db:/tmp/$name" "backups/$name"
docker compose exec -T db rm "/tmp/$name"
```

Restore into the running database (this replaces its contents):

```powershell
$name = "twin-YYYY-MM-DD.sql"
docker compose stop web
docker compose cp "backups/$name" "db:/tmp/$name"
docker compose exec -T db sh -c "psql -U `$POSTGRES_USER -d `$POSTGRES_DB -v ON_ERROR_STOP=1 -q -o /dev/null -f /tmp/$name && rm /tmp/$name"
docker compose start web
```

`backups/` is gitignored. Restoring a dump keeps every CID, because CIDs are stored values computed from content.

Check a restore: `docker compose exec web python manage.py showmigrations core` lists every migration as applied, and the reports show the expected records. To test a backup without touching the live data, restore it into a scratch database (`createdb -U twin twin_restore_check`, the `psql -f` step with `-d twin_restore_check`, compare row counts, then `dropdb -U twin twin_restore_check`).

## Upgrading

```powershell
git pull
docker compose up -d --build
docker compose exec web python manage.py migrate
```

- Take a backup before migrating.
- Migrations 0006 (Supersession) cannot be reversed, and 0007 dropped earlier `bedtime`/`wake_time` values; both are long applied on existing installs. Migrations since 0008 add fields or tables only.
- New nullable fields on existing record types are in `OMIT_IF_NULL`, so upgrades never change stored CIDs.
- After changing a model (contributors): `python manage.py makemigrations`, then `python manage.py data_model_doc` to regenerate `docs/DATA_MODEL.md`.

## Checks

```powershell
powershell -File scripts/ci-local.ps1
```

Runs the test suite and `makemigrations --check` in Docker and writes the result to `.agents/ci-local-last.txt`.

## Stopping

```powershell
docker compose down      # keeps the database volume
```
