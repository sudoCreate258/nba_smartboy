# M4 Phone-friendly app — Design

- New Django app `app` (or `ui`): server-rendered templates, plain CSS, a few
  lines of vanilla JS only for the service worker and offline queue.
- Reuse services: `core/services` write paths, `probe_report`, `zone_report`.
  No business logic in views.
- Charts: a small `twin_metrics/svg.py` (plain Python) that turns series into
  SVG line/bar charts; tested on string output.
- Offline queue: service worker caches the app shell; forms submitted offline
  are stored in IndexedDB and replayed; the server answers duplicates (same
  CID) with "already saved".
- Export format documented in `docs/DATA_MODEL.md` (from the docs task) as
  the first draft of the Nymbus interchange contract.
- Keep Flutter possible: every page's data also available as JSON at a
  `/api/v0/...` read-only endpoint behind the same login (no write API yet).
- Module registry: each UI feature is a Django app with a `module.json` manifest (id, version, reads, writes, compute, shares). M4 ships the registry, a Modules page (enable/disable per module) and wraps probes, zone and training as the first three modules. Permission enforcement per category arrives in M5; in M4 a disabled module's pages and jobs are simply off.
