# nba_smartboy
![CI](https://github.com/OWNER/REPO/actions/workflows/ci.yml/badge.svg)
<!-- Badge uses placeholder OWNER/REPO. Replace with the real GitHub path once the remote exists. -->


Local-first personal health digital twin (Nymbus phase 1). Django 5 + PostgreSQL 16 in Docker Compose. Health data stays local.

## Run

Requires Docker Desktop.

```powershell
copy .env.example .env
docker compose up -d --build
docker compose exec web python manage.py migrate
docker compose exec web python manage.py createsuperuser
```

Open http://localhost:8000/admin/ and log in with the superuser.

## Test

```powershell
docker compose exec web pytest
```

## Stop

```powershell
docker compose down      # keeps the pgdata volume
docker compose down -v   # also deletes the database
```

## Layout

See `.kiro/steering/tech.md`. Decisions are logged in `docs/DECISIONS.md`.
