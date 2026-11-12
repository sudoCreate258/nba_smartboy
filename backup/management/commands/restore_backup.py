# SPDX-License-Identifier: AGPL-3.0-or-later
"""Restore a backup set into this instance's database (M4.5 R10), then prove it.

    python manage.py restore_backup --set latest --yes        # download through the crypt remote
    python manage.py restore_backup backups/2026-11-12T073000Z  # an already downloaded set

Order of work, so a bad set never damages the live database:
  1. check every file against the manifest (SHA-256);
  2. restore into a scratch database and compare every record and correction with the export;
  3. only then replace the live database, in one transaction (all or nothing);
  4. compare the live database with the export once more.
Stop the web and backup services first (see docs/OPERATIONS.md), so nothing writes while it is replaced.
"""
import json
import shutil
import tempfile
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import connection

from backup.runner import (DUMP, MANIFEST, BackupError, check_files, compare_with_exports, download_set,
                           restore_dump, verify_restore)


def live_row_counts():
    """Rows in every table of the live database (not only records): what a restore would replace.

    The one row a fresh `migrate` creates itself (the seeded 'mike' contributor) is not data, so a
    freshly migrated database counts as empty."""
    with connection.cursor() as cur:
        cur.execute("SELECT relname FROM pg_stat_user_tables ORDER BY relname")
        tables = [r[0] for r in cur.fetchall()]
        counts = {}
        for table in tables:
            cur.execute(f'SELECT count(*) FROM "{table}"')
            counts[table] = cur.fetchone()[0]
        cur.execute("SELECT handle FROM core_contributor")
        handles = [r[0] for r in cur.fetchall()]
    if handles == ["mike"]:
        counts["core_contributor"] = 0
    return counts


class Command(BaseCommand):
    help = "Restore a backup set (checks SHA-256, proves it in a scratch database, then replaces the live data)."

    def add_arguments(self, parser):
        parser.add_argument("folder", nargs="?", help="a downloaded set folder")
        parser.add_argument("--set", dest="set_name", help='verified set name on BACKUP_REMOTE, or "latest"')
        parser.add_argument("--yes", action="store_true", help="replace a database that already has data")

    def handle(self, *args, folder, set_name, yes, **options):
        if bool(folder) == bool(set_name):
            raise CommandError("Give either a downloaded set folder or --set NAME|latest.")
        temp = None
        try:
            if set_name:
                temp = Path(tempfile.mkdtemp(prefix="twin-restore-"))
                set_name = download_set(set_name, temp)
                folder = temp
                self.stdout.write(f"Downloaded {set_name} (a verified set) through the crypt remote.")
            folder = Path(folder)
            manifest = json.loads((folder / MANIFEST).read_text(encoding="utf-8"))
            check_files(folder, manifest)
            self.stdout.write(f"Files match the manifest (created {manifest['created_at']}, "
                              f"app {manifest['app_version']}, commit {manifest['git_commit'][:12]}).")
            n = verify_restore(folder, manifest, scratch="twin_restore_check", check_schema=True)
            self.stdout.write(f"Checked in a scratch database first: {n} records and all corrections match the export.")
            counts = live_row_counts()
            used = {t: c for t, c in counts.items() if c and t not in ("django_migrations", "django_content_type",
                                                                       "auth_permission")}
            if used and not yes:
                summary = ", ".join(f"{t} {c}" for t, c in sorted(used.items())[:6])
                raise CommandError(f"This database already has data ({summary}{', ...' if len(used) > 6 else ''}); "
                                   "restoring replaces all of it, including users and settings. "
                                   "Stop the web and backup services, then run again with --yes.")
            dbname = connection.settings_dict["NAME"]
            connection.close()  # do not hold the database while it is replaced
            restore_dump(dbname, folder / DUMP, clean=True)  # one transaction: all or nothing
            n = compare_with_exports(dbname, folder, manifest)
        except (BackupError, OSError, KeyError, json.JSONDecodeError) as exc:
            raise CommandError(f"Restore failed: {exc}")
        finally:
            if temp is not None:
                shutil.rmtree(temp, ignore_errors=True)
        self.stdout.write(f"Restored {n} records; every CID matches the export. Run `manage.py migrate` next "
                          "(a no-op when the code matches the backup), then start the services again.")
