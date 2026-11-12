# nymbus_v1510

SPDX-License-Identifier: AGPL-3.0-or-later

![CI](https://github.com/sudoCreate258/nymbus_v1510/actions/workflows/ci.yml/badge.svg)


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

Options: `--contributor mike` (default), `--weeks 4` (default), `--until YYYY-MM-DD` (the last reported week is the whole local week containing this date; default today), `--json`.

- Weeks are local weeks starting Monday, in the contributor's time zone. A block that crosses midnight counts in the week it started.
- High focus: absorption of 4 or more and at most 1 interruption. A block with either value missing is not counted as high focus.
- Per week: total hours, high-focus minutes, focus share (high-focus minutes / all minutes), the median and interquartile range of high-focus block lengths (the "theta" band), and the same split by location, posture and planned length.
- Zone amber: the focus share is at least 20% below the mean of the 3 weeks before, while total hours stay within 10% of their mean. You are working as much but with less flow. If any of those 3 weeks has no work blocks, it shows "insufficient data".
- Reset effect: for each reset kind and metric, the number of usable before/after pairs (both probes recorded that metric) and the mean change (after minus before) in mini-probe accuracy and solve time, compared with `none`. A metric with fewer than 5 pairs is marked "not interpretable yet", and the comparison with `none` is marked "underpowered" unless both sides have 5 or more. If a probe was corrected later, the current version is used; a reset whose corrected probes are no longer mini-puzzles or no longer bracket it is listed as excluded.
- Stop signals before the reported weeks are counted on one line, so they do not disappear when they fall out of the window.
- The JSON output never includes free-text notes.
- Discomfort: per week, the mean score per area, how many checks scored 3 or more per trigger, and how often a countermove followed them.
- The weekly check and the probe flags are shown next to these, never combined into one score.

## Training log

Log strength and conditioning sessions (RP-style programming) so training load can be read next to sleep, probes and the zone. It is a load gauge, not a medical assessment.

**In the admin:** add a Training session (start time, program, mesocycle, mesocycle week, deload, location, session RPE 0-10, optional end time and notes). Its page lists its sets and has an "Add a set to this session" link, which fills in the session CID. Each set has an order number (unique within the session), exercise, muscle group, load in kg (empty for bodyweight), reps, and optionally RIR (reps in reserve, 0-10), pump, soreness before and joint pain (each 0-3), the joint-pain area and notes. Exercise names are stored in lower case with extra spaces removed, so "Bench  Press" and "bench press" are the same. To fix a session or set, use "Save as correction"; sets of a corrected session follow it to the new version.

**From a spreadsheet:** one row per set, with the session columns repeated on every row. Use this header:

```
started_at,program,mesocycle,meso_week,is_deload,location,session_rpe,order,exercise,muscle_group,load_kg,reps,rir,pump,soreness_before,joint_pain,joint_pain_area,notes
```

- Required: `started_at`, `order`, `exercise`, `muscle_group`, `reps`. Other cells may be empty, and other columns may be left out. Columns may come in any order; unknown columns are rejected.
- `started_at`: `2026-11-10 18:00` (local time in your time zone) or with an offset, `2026-11-10T18:00:00-05:00`. Local times that fall in a daylight-saving change (ambiguous or skipped) are rejected; give an offset for those.
- Rows with the same `started_at` and `program` form one session, and their session columns must match.
- `is_deload`: `yes`/`no` or `true`/`false` (any case); empty means no.
- `location`: gym, home or other. `muscle_group`: chest, back, shoulders, biceps, triceps, quads, hamstrings, glutes, calves, abs, forearms, full_body, other. `joint_pain_area`: neck, shoulder, wrist, hip, low_back, other.
- `notes` is the set's notes. Session notes and the end time are added in the admin.
- See `tests/fixtures/sample_training.csv` for an example.

Import (save the CSV under `data/inbox/`, which is not committed):

```powershell
docker compose exec web python manage.py ingest_training_csv data/inbox/training.csv
```

The whole file is imported or nothing is (the error names the line and column). Importing the same file again, or the same file with new rows added at the end, only adds the new sets.

**Read the report:**

```powershell
docker compose exec web python manage.py training_report
docker compose exec web python manage.py training_report --weeks 8 --json
```

Options: `--contributor mike` (default), `--weeks 4` (default), `--until YYYY-MM-DD` (the last reported week is the whole local week containing this date; default today), `--json`.

- Stop signals first: any set with joint pain of 2 or more ("stop the block; get it checked by a professional"). Earlier ones are counted on one line.
- Per local week (by session start): sessions, sets, hard sets per muscle group (RIR 3 or less, or RIR not recorded), tonnage (load x reps; bodyweight sets add 0), mean RIR and how many sets recorded it, deload weeks marked, and joint-pain sets (joint pain 1 or more) by area.
- The JSON output never includes free-text notes.

## Phone app

Open http://localhost:8000/ and log in with your Django user. It has these pages:
- **Today:** stop signals first, then the day's check-ins (done or missing) and the probe and zone flags.
- **Check in:** quick forms for the daily snapshot, probe, work block, discomfort check and reset.
- **Trends:** charts for the last 4 or 12 weeks.
- **Recent:** "Correct this" on any record from the last 14 days. A correction saves a new version; nothing is edited or deleted.

The app works without JavaScript. With it, check-ins you make while the instance is unreachable are kept on the phone and sent when it is reachable again; a check-in sent twice is stored once.

Installing to the home screen and opening viewed pages offline need a service worker, which browsers only allow on `https://` or on `localhost`. So:
- **On this computer** (`http://localhost:8000/`): install and offline pages work.
- **On a phone in LAN mode** (plain `http://<address>:8000/`): the offline check-in queue works, but the browser will not install the app or keep pages offline. That arrives with HTTPS in M6.

Logging out deletes the pages saved on the device. Check-ins not yet sent stay on the device and are sent after the next login. A manual phone checklist is in `docs/OPERATIONS.md`.

**Debug:** `DJANGO_DEBUG=1` is for local development only (detailed error pages). Normal use is `DJANGO_DEBUG=0`, which needs a `DJANGO_SECRET_KEY`; `.env.example` shows how to generate one.

**LAN mode (phone on your home Wi-Fi):** off by default; the app only listens on this computer. To open it from a phone on the same network, set `TWIN_LAN_HOST` in `.env` to this computer's address (for example `192.168.1.20`, from `ipconfig`), then `docker compose up -d` and open `http://192.168.1.20:8000/` on the phone.
- Use LAN mode only on a trusted home network, never on shared or public Wi-Fi: it is plain HTTP until HTTPS arrives (M6).
- LAN mode refuses to start while `DJANGO_DEBUG=1`.
- Logins are rate-limited (5 failed attempts per username or address, then a 15-minute wait).

## Stop

```powershell
docker compose down      # keeps the pgdata volume
docker compose down -v   # also deletes the database
```

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for the branching model, commit style, and PR process. Security reports: [SECURITY.md](SECURITY.md).

## Layout

See `.kiro/steering/tech.md`. Decisions are logged in `docs/DECISIONS.md`.

- `docs/ARCHITECTURE.md`: components, data flow, Nymbus layer mapping, trust boundaries.
- `docs/DATA_MODEL.md`: every record type, its fields, bounds and CID rules (generated: `python manage.py data_model_doc`).
- `docs/OPERATIONS.md`: setup, imports, reports, backup and restore, upgrades.
