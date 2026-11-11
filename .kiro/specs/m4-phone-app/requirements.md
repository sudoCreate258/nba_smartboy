# M4 Phone-friendly app — Requirements

## Goal
Replace the Django admin as the daily interface with a simple, installable,
phone-friendly web app served by the user's own instance. Works offline on
the home network, on older phones, with no cloud and no app store.

### R1 Daily check-in (one screen, under 30 seconds)
- Quick forms for: daily snapshot (manual entry of sleep score, bedtime,
  wake time, resting HR, HRV; body composition optional with bia_timing),
  probe session, work block, discomfort check, reset.
- Large tap targets; forms work without JavaScript.
- Validation errors show next to the field in plain words (reuse model validation).
- Saving uses the same write path as ingest/admin (CID, supersession, locks).
- "Correct this" on any recent record creates a correction (Supersession), never an edit.

### R2 Today and trends
- Home screen: today's check-ins done/missing; latest probe flag (none/amber/red)
  and zone flag with their reasons; stop signals (sharp_or_numb) at the top.
- Trends page, last 4/12 weeks: sleep score, bedtime, resting HR, HRV,
  weight/body fat (pre-session only), probe rolling medians vs baseline,
  weekly work hours and focus share, discomfort by area.
- Charts are server-rendered SVG (no JS charting library, no CDN). Each chart
  shows its data source and "Load gauge, not a medical assessment."

### R3 Installable and offline
- Web app manifest + service worker: installable to the home screen; the
  shell and last-viewed pages load without a connection; check-ins made
  offline queue locally and submit when the instance is reachable (no data
  lost; duplicates rejected by CID).
- All assets vendored in the repo; zero external requests (verified by a test
  that scans templates/static for http(s) URLs to other hosts).
- Target: Chrome on Android 8+ and Safari on iOS 14+; must be usable on a
  small, slow phone (pages under 200 KB, no build step required).

### R4 Access from a phone on the home network
- Default stays `127.0.0.1` (fail-closed). Opt-in LAN mode via
  `TWIN_LAN_HOST` in `.env`; README explains it is for a trusted home network.
- Login required for every page (Django auth); session cookies HttpOnly,
  SameSite=Lax; CSRF on all forms; login rate-limited.
- HTTPS on the LAN is M6; until then the README warns not to use LAN mode on
  shared or public Wi-Fi.
- Debug off works: static files (admin and app) are served with debug off (WhiteNoise or equivalent, vendored, no CDN); `.env.example` defaults to `DJANGO_DEBUG=0` with instructions to generate a secret key; the README explains `DJANGO_DEBUG=1` is for local development only. LAN mode refuses to start while debug is on.

### R5 "My data" export
- `python manage.py export_my_data [--contributor mike] [--out file]` and a
  button in the app: all records as JSON Lines with kind, CID, contributor,
  fields, and supersession events, so any stack can import it.
- Export → fresh DB import reproduces identical CIDs (round-trip test).

### R6 Quality gate
- View tests for every form (valid, invalid, correction, offline-duplicate).
- External-request scan test; export round-trip test; LAN mode off by default test.
- Full suite green in Docker and on GitHub Actions.
