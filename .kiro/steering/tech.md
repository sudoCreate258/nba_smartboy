---
inclusion: always
---

# Tech stack and conventions

## Stack
- Python 3.12, Django 5.x (admin used as the M1 data-entry UI)
- PostgreSQL 16
- Docker Compose for local runtime (host: Windows + Docker Desktop)
- pytest + pytest-django for tests
- GitHub Actions for CI
- PyYAML for ingest

## Layout
```
nba_smartboy/
  docker-compose.yml
  Dockerfile
  .env.example          # never commit .env
  requirements.txt
  manage.py
  twin/                 # Django project settings
  core/                 # models, admin, ingest command
  tests/
  data/inbox/           # YAML files to ingest (gitignored)
  docs/DECISIONS.md     # planner <-> builder decision log
```

## Conventions
- Keep it simple: a concise main path and small helpers; no abstractions
  until a second use exists.
- Settings from environment variables; no secrets in code or git.
- Every model change ships with a migration and a test.
- Dates/times stored timezone-aware; owner timezone America/New_York.
- Windows host: add `.gitattributes` with `* text=auto eol=lf` so shell
  scripts and Dockerfiles work in Linux containers.
- Commands Kiro should use:
  - `docker compose up -d --build`
  - `docker compose exec web python manage.py migrate`
  - `docker compose exec web pytest`
