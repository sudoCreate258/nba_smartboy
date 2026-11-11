#!/bin/sh
# SPDX-License-Identifier: AGPL-3.0-or-later
# Local CI gate: the same checks as GitHub Actions, run in Docker.
#   pytest -q  and  makemigrations --check --dry-run
# Usage: sh scripts/ci-local.sh   (from the repo root; needs Docker and a .env)
# Writes the result (commit, date, test summary) to .agents/ci-local-last.txt.
set -u
cd "$(git rev-parse --show-toplevel)" || exit 1

commit=$(git rev-parse --short HEAD)
dirty=""
if ! git diff --quiet HEAD -- 2>/dev/null; then
  dirty=" (with uncommitted changes)"
fi
echo "Local CI gate on $commit$dirty"

out=$(docker compose run --rm -T web sh -c "pytest -q -p no:cacheprovider && python manage.py makemigrations --check --dry-run" 2>&1)
status=$?
echo "$out" | tail -n 5
summary=$(echo "$out" | grep -E "[0-9]+ (passed|failed)" | tail -n 1)

mkdir -p .agents
result=$([ $status -eq 0 ] && echo PASS || echo FAIL)
printf '%s %s %s%s: %s\n' "$result" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$commit" "$dirty" "$summary" > .agents/ci-local-last.txt
echo "Local CI gate: $result ($summary)"
exit $status
