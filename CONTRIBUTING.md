# Contributing

Thanks for helping with nba_smartboy. This project handles personal health data, so keep real data out of commits, issues, and PRs.

## Who can contribute
Outside code contributions are not open until the worker co-op stage. Until then, please do not send code PRs.

Any code contributed before then needs a Developer Certificate of Origin (DCO) sign-off. Add it with `git commit -s`, which appends a `Signed-off-by: Your Name <you@example.com>` line to each commit. By signing off you agree to the DCO, whose full text is in [DCO](DCO).

## Branching model

- `main`: stable, released state.
- `develop`: integration branch. All work lands here first.
- Feature branches: branch from `develop`, named by type, for example `feat/probe-log`, `fix/validator`, `chore/community-docs`.

Flow: feature -> develop -> main. Open PRs against `develop`. Only `develop` is merged into `main`.

## Commit style

Use a short summary. Milestone work uses the task id as a prefix:

```
M2-T1: add Probe model and migration
```

Other changes use a type prefix: `feat:`, `fix:`, `chore:`, `docs:`, `refactor:`, `test:`.

## Local setup and tests

Requires Docker Desktop.

```powershell
copy .env.example .env
docker compose up -d --build
docker compose exec web python manage.py migrate
docker compose exec web pytest
```

Tests must pass before you open a PR. CI runs the same suite (`.github/workflows/ci.yml`).

## Pull request process

1. Branch from `develop` and keep the change focused.
2. Add or update tests for behavior changes.
3. Run `docker compose exec web pytest` and confirm it passes.
4. Open a PR against `develop` and fill in the template.
5. Wait for CI and review from a code owner (see `.github/CODEOWNERS`).
6. Record notable design choices in `docs/DECISIONS.md`.

## Conduct and security

By participating you agree to the [Code of Conduct](CODE_OF_CONDUCT.md). Report vulnerabilities privately as described in [SECURITY.md](SECURITY.md).

## License

Contributions are licensed under AGPL-3.0.
