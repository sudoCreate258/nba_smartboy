# nba_smartboy

SPDX-License-Identifier: AGPL-3.0-or-later

![CI](https://github.com/sudoCreate258/nba_smartboy/actions/workflows/ci.yml/badge.svg)


Local-first personal health digital twin (Nymbus phase 1). Django 5 + PostgreSQL 16 in Docker Compose. Health data stays local.

## Run

Requires Docker Desktop. A .env file is required (fail-closed, no built-in password fallbacks): copy .env.example to .env and set your own values before starting. Compose refuses to start without it.

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
# nba_smartboy
