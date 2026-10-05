#!/usr/bin/env bash
# Publish the counter and PROVE what went live is what is in the repository
# (audit 2026-09-02). One command, refuses to guess:
#   - only from a clean main (what is live must be a commit anyone can read);
#   - builds the pages fresh, stamped with that commit;
#   - deploys with the pinned wrangler;
#   - then asks the live site, from outside, which commit it serves, and that
#     the door is closed to a stranger and honest to a wrong password.
set -euo pipefail
cd "$(dirname "$0")/.."

# Credentials come from the environment (or an untracked local file); none are in the repository.
[ -f secrets/keys.env ] && { set -a; source secrets/keys.env; set +a; }
: "${SITE_ORIGIN:?DEPLOY: set SITE_ORIGIN, e.g. https://scheinman.example.com}"
: "${SITE_PASSWORD:?DEPLOY: set SITE_PASSWORD (used to prove the gate from outside)}"
SITE="$SITE_ORIGIN"

branch=$(git rev-parse --abbrev-ref HEAD)
if [ "$branch" != "main" ] && [ "${DEPLOY_FROM_BRANCH:-}" != "yes" ]; then
  echo "DEPLOY: refusing to publish from '$branch'; merge to main first (or DEPLOY_FROM_BRANCH=yes for a test deploy)" >&2
  exit 1
fi
if [ -n "$(git status --porcelain)" ]; then
  echo "DEPLOY: the working tree is not clean; commit or stash first, the live site must match a commit" >&2
  exit 1
fi
# The engine always runs `main` on GitHub. A local main ahead of or behind the
# remote would publish pages from one commit and run parts on another.
if [ "$branch" = "main" ]; then
  git fetch -q origin main
  if [ "$(git rev-parse HEAD)" != "$(git rev-parse origin/main)" ]; then
    echo "DEPLOY: local main ($(git rev-parse --short HEAD)) is not origin/main ($(git rev-parse --short origin/main)); push or pull first" >&2
    exit 1
  fi
fi

# The stamp on every page proves WHICH commit is live; this proves it was green.
echo "DEPLOY: running ./check.sh on $(git rev-parse --short=12 HEAD) before anything goes live"
./check.sh >/tmp/scheinman-deploy-check.log 2>&1 || {
  echo "DEPLOY: ./check.sh is red on this commit; nothing was published (log: /tmp/scheinman-deploy-check.log)" >&2
  exit 1
}

echo "DEPLOY: building the pages from $(git rev-parse --short=12 HEAD)"
uv run --locked python -m scheinman.webbuild >/dev/null
commit=$(python3 -c "import json; print(json.load(open('web/public/build.json'))['commit'])")

echo "DEPLOY: publishing with the pinned wrangler"
( cd web && npm ci --silent && npx wrangler deploy 2>&1 | tail -3 )

echo "DEPLOY: proving from outside"
jar=$(mktemp)
trap 'rm -f "$jar"' EXIT
# 1. The right password opens the door, and the ticket it hands back is what
#    the version route needs.
body=$(python3 -c "import json,os; print(json.dumps({'password': os.environ['SITE_PASSWORD']}))")
curl -sS --max-time 30 -c "$jar" -o /dev/null -X POST -H 'content-type: application/json' -d "$body" "$SITE/api/gate"
# 2. A fresh version takes seconds to reach every colo, so ask the site which
#    commit it serves until it names the one just built, up to 90 s. Wait on
#    THIS, never on a sentence that was already live before the deploy: the
#    first version of this wait watched the door's attempts-left message, which
#    shipped a day earlier, so it broke on the first try and judged a site that
#    had not switched yet (lesson 021). Polling the version costs nothing;
#    polling the door with a wrong password would burn the ten attempts an hour
#    the gate allows and could lock this proof out of the site.
live=""
for _ in $(seq 1 18); do
  live=$(curl -sS --max-time 30 -b "$jar" "$SITE/api/version" | python3 -c "import json,sys; print(json.load(sys.stdin).get('commit',''))")
  [ "$live" = "$commit" ] && break
  sleep 5
done
# 3. A stranger meets the door, on a page and on the API.
gate=$(curl -sS --max-time 30 -o /dev/null -w '%{http_code}' "$SITE/inspect")
api=$(curl -sS --max-time 30 -o /dev/null -w '%{http_code}' "$SITE/api/archive")
# 4. A wrong password is told how many attempts are left.
wrong=$(curl -sS --max-time 30 -X POST -H 'content-type: application/json' -d '{"password":"not-the-password"}' "$SITE/api/gate")
# 4. The human check is configured and enforced: a part with no token is
#    refused (403), never accepted and never "not configured" (503).
robot=$(curl -sS --max-time 60 -b "$jar" -o /dev/null -w '%{http_code}' -F part=@web/public/samples/cover-sample.step -F material_series=7xxx -F loading=cyclic -F turnstile_token= "$SITE/api/jobs")
curl -sS --max-time 30 -b "$jar" -o /dev/null -X POST "$SITE/api/gate/lock"

ok=yes
[ "$gate" = "200" ] && curl -sS --max-time 30 "$SITE/inspect" | grep -q 'role">Admin' || { echo "FAIL: a stranger did not meet the door on /inspect (got $gate)"; ok=no; }
[ "$api" = "401" ] || { echo "FAIL: the API answered a stranger with $api, not 401"; ok=no; }
echo "$wrong" | grep -q 'attempts left' || { echo "FAIL: the door did not say how many attempts are left: $wrong"; ok=no; }
[ "$live" = "$commit" ] || { echo "FAIL: the live site serves commit '$live', this build is '$commit'"; ok=no; }
[ "$robot" = "403" ] || { echo "FAIL: a part with no human-check token got $robot, not 403 (503 means TURNSTILE_SECRET is missing on the Worker)"; ok=no; }
if [ "$ok" = yes ]; then
  echo "DEPLOY: LIVE = $commit (door closed to strangers, honest to a wrong password, version proven)"
else
  echo "DEPLOY: NOT PROVEN, see the FAIL lines above" >&2
  exit 1
fi
