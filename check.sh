#!/usr/bin/env bash
# The single verification command (see README).
# Runs everything: format, lint, types, tests. Needs no secrets. Used locally and in CI.
set -euo pipefail
cd "$(dirname "$0")"

uv run --locked ruff format --check src tests
uv run --locked ruff check src tests
uv run --locked mypy src tests
uv run --locked pytest -q

# No stored secret may appear anywhere else in the repository (lesson 011).
# Silent where there is no secrets file, so CI runs it too.
./tools/no-secret-leaks.sh

# The counter's own rules (web/src/logic.mjs) run in Node, so they are tested in
# Node. node --test ships with the runtime: no test framework, no dependency.
if command -v node >/dev/null 2>&1; then
  node --test --test-reporter=dot 'web/test/*.test.mjs'
else
  echo "CHECK: node is missing, so the counter's tests did not run" >&2
  exit 1
fi

echo "CHECK: ALL GREEN"
