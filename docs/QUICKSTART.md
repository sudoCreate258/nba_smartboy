# Quickstart

Needs Docker Desktop and Git. All commands are PowerShell, from the repository folder.

**First time:** copy `.env.example` to `.env` and set `DJANGO_SECRET_KEY` and `POSTGRES_PASSWORD`
(the file explains how).

**Start** (builds, starts, migrates, adds the DEMO profile, prints the URLs):

```powershell
powershell -File scripts/up.ps1
docker compose exec web python manage.py createsuperuser   # once, for your login
```

Open http://localhost:8000/. Your own data and the DEMO profile are separate: the app shows yours;
the Provenance page can switch to the DEMO profile (`/provenance/?who=demo`): pick a record to see its
CID, corrections, reads and the grants behind them. For the phone, set up LAN HTTPS (README) and run
`scripts/up.ps1` again; it prints the phone URL.

**Prove the round trip** (export, import into an empty scratch database, compare every CID, every
correction and the ledger head; exit 0 or 1):

```powershell
docker compose exec web python manage.py demo_roundtrip               # DEMO profile
docker compose exec web python manage.py demo_roundtrip --contributor mike
```

**Back up:** encrypted off-hours backup, see `docs/OPERATIONS.md` ("Encrypted backup"). A quick
copy of your records: `docker compose exec web python manage.py export_my_data --out data/inbox/my-data.jsonl`.

**Reset the demo data:** records cannot be deleted (that is the point), so the DEMO profile is reset
by starting from an empty database. This deletes **all** data in this instance, yours included, so
export or back up first:

```powershell
docker compose down -v
powershell -File scripts/up.ps1
```

**Stop:** `docker compose down` (keeps the data). **Update:** `powershell -File scripts/update.ps1`.
