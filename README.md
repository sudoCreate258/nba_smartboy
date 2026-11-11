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

## Probe log (cognitive-load gauge)

The probe report turns logged probe sessions into a load gauge. It is a load gauge, not a medical assessment.

1. Log probes in the admin under Probe sessions. Two kinds are scored:
   - `puzzle_set`: `accuracy_pct` (lower is worse), `median_solve_s` (higher is worse).
   - `rapid_game`: `accuracy_pct` (lower is worse), `late_blunders`, `fast_blunders`, `move_time_cv` (higher is worse). `move_time_cv` is the coefficient of variation of time per move, 2 decimals, 0 or more.
   - `module` sessions are stored but not scored. Leave a metric empty if you do not have it; nothing is filled in.
   - To fix a session, use the "Save as correction" action. Superseded sessions are ignored.
2. Optionally set a baseline under Probe baselines: a kind plus a start and end. Without one, the baseline is the first 10 current sessions of that kind. A baseline needs at least 10 sessions, and a metric needs at least 10 values and a non-zero spread, or it is skipped.
3. Read the report:

```powershell
docker compose exec web python manage.py probe_report
docker compose exec web python manage.py probe_report --kind rapid_game --json
```

Options: `--contributor mike` (default), `--kind puzzle_set|rapid_game` (default: both), `--json`.

For each kind the report shows the baseline window and count, the latest rolling medians (median of the last 3 sessions) with z-scores where positive means worse, skipped metrics, the flag, and the sleep and work context.

- Amber: at the latest 3 scored sessions in a row, at least 2 metrics have z of 1.0 or more.
- Red: the same at z of 1.5 or more, or amber while sleep is falling or work load is rising.
- Sleep falling: mean sleep score of the last 3 nights is at least 1 SD below the baseline nights. Work rising: hours in the last 3 days are at least 1 SD above the baseline 3-day totals.
- Missing sleep or work data shows "insufficient data" and never raises a flag.

## Stop

```powershell
docker compose down      # keeps the pgdata volume
docker compose down -v   # also deletes the database
```

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for the branching model, commit style, and PR process. Security reports: [SECURITY.md](SECURITY.md).

## Layout

See `.kiro/steering/tech.md`. Decisions are logged in `docs/DECISIONS.md`.
# nba_smartboy
