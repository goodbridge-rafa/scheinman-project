#!/usr/bin/env bash
# If a local, untracked secrets/keys.env exists, none of its values may appear
# anywhere in the repository. Added after an audit (2026-09-01) found the site
# password written into a versioned test file. Runs in ./check.sh; silent when
# there is no keys file (CI, fresh clones).
#
# Identifiers are not secrets and are skipped by name: an account, zone or
# namespace id is useless without a token and has to live in configuration; the
# Turnstile sitekey is public by design and is printed on the page itself.
set -euo pipefail
cd "$(dirname "$0")/.."
[ -f secrets/keys.env ] || { echo "secrets: no keys file here, nothing to check"; exit 0; }
leaked=0
while IFS='=' read -r name value; do
  case "$name" in
    ''|\#*) continue ;;
    *_ID|*_NAMESPACE_ID|*SITEKEY|*_REPO) continue ;;
  esac
  [ ${#value} -lt 8 ] && continue
  hits=$(git grep -l -F --untracked -- "$value" -- . 2>/dev/null | grep -v '^secrets/' || true)
  if [ -n "$hits" ]; then
    echo "LEAK: the value of $name appears in: $hits" >&2
    leaked=1
  fi
done < secrets/keys.env
[ "$leaked" = "0" ] && echo "secrets: no stored secret appears anywhere else in the repository"
exit "$leaked"
