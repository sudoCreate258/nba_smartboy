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
   - `mini_puzzle`: about 5 puzzles taken between work blocks; `accuracy_pct` (lower is worse), `median_solve_s` (higher is worse).
   - `module` sessions are stored but not scored. Leave a metric empty if you do not have it; nothing is filled in.
   - To fix a session, use the "Save as correction" action. Superseded sessions are ignored.
2. Optionally set a baseline under Probe baselines: a kind plus a start and end. Without one, the baseline is the first 10 current sessions of that kind, but only if they fall within 42 days; otherwise the report says "insufficient baseline: set a ProbeBaseline". A baseline needs at least 10 sessions, and a metric needs at least 10 values and a non-zero spread, or it is skipped.
3. Read the report:

```powershell
docker compose exec web python manage.py probe_report
docker compose exec web python manage.py probe_report --kind rapid_game --json
```

Options: `--contributor mike` (default), `--kind puzzle_set|rapid_game|mini_puzzle` (default: all three), `--json`.

For each kind the report shows the baseline window and count, the latest rolling medians (median of the last 3 sessions) with z-scores where positive means worse, skipped metrics, the flag, and the sleep and work context.

- Amber: at the latest 3 scored sessions in a row, at least 2 metrics have z of 1.0 or more.
- Red: the same at z of 1.5 or more, or amber while sleep is falling or work load is rising.
- Sleep falling: mean sleep score of the last 3 nights is at least 1 SD below the baseline nights. Work rising: hours in the last 3 days are at least 1 SD above the baseline 3-day totals.
- Missing sleep or work data shows "insufficient data" and never raises a flag.

## Work and zone

The zone report shows how much of your work time is sustained high focus ("the zone") and what protects or erodes it. It is a load gauge, not a medical assessment.

Log these in the admin. Every record gets a CID and is never edited; use "Save as correction" to fix one.

- **Work blocks:** start, end, task type, and if you have them `location`, `posture` (sit, stand, mixed), `planned_length_min` (the Pomodoro length you planned, for example 25, 40 or 50), `interruptions`, `absorption` (1-5) and `effort` (1-5). Blocks of one contributor may not overlap (one may end exactly when the next starts); to change a block, correct it.
- **Discomfort checks:** time, area (neck, shoulder, wrist, hip, low_back, other), score 0-10, trigger (end_of_commute, end_of_meeting, end_of_block, standing_long, other), the countermove you did (or none), and `sharp_or_numb`. Sharp pain or numbness is a stop signal: stop the block and get it checked by a professional. The report lists these first.
- **Resets:** a short break between blocks (walk, cold_shower, dead_hang_mobility, breathing, nap, or none as the control). Take a `mini_puzzle` probe before and after, then enter the reset with the CIDs of both probes (copy them from the Probe sessions list). The before probe must start before the reset and the after probe after it.
- **Weekly checks:** once a week, the local Monday of the week, the name of the burnout questionnaire you used, your score and the scale maximum. Only the score is stored, never the questionnaire items.

Read the report:

```powershell
docker compose exec web python manage.py zone_report
docker compose exec web python manage.py zone_report --weeks 8 --json
```

Options: `--contributor mike` (default), `--weeks 4` (default), `--until YYYY-MM-DD` (last day shown; default today), `--json`.

- Weeks are local weeks starting Monday, in the contributor's time zone. A block that crosses midnight counts in the week it started.
- High focus: absorption of 4 or more and at most 1 interruption. A block with either value missing is not counted as high focus.
- Per week: total hours, high-focus minutes, focus share (high-focus minutes / all minutes), the median and interquartile range of high-focus block lengths (the "theta" band), and the same split by location, posture and planned length.
- Zone amber: the focus share is at least 20% below the mean of the 3 weeks before, while total hours stay within 10% of their mean. You are working as much but with less flow. If any of those 3 weeks has no work blocks, it shows "insufficient data".
- Reset effect: for each reset kind, the number of resets and the mean change (after minus before) in mini-probe accuracy and solve time, compared with `none`. Kinds with fewer than 5 resets are shown but marked "not interpretable yet".
- Discomfort: per week, the mean score per area, how many checks scored 3 or more per trigger, and how often a countermove followed them.
- The weekly check and the probe flags are shown next to these, never combined into one score.

## Stop

```powershell
docker compose down      # keeps the pgdata volume
docker compose down -v   # also deletes the database
```

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for the branching model, commit style, and PR process. Security reports: [SECURITY.md](SECURITY.md).

## Layout

See `.kiro/steering/tech.md`. Decisions are logged in `docs/DECISIONS.md`.
