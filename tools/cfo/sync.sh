#!/usr/bin/env bash
# CFO sync — git add data/ + commit + push. Idempotent.
# Usage: sync.sh "Commit message"  (default: "CFO: data update")

set -euo pipefail
cd "$(dirname "$0")/../.."   # repo root

MSG="${1:-CFO: data update}"

# Only commit if data/ has changes
if ! git status --porcelain data/ tools/cfo/ | grep -q .; then
  echo "[sync] no changes in data/ or tools/cfo/"
  exit 0
fi

git add data/ tools/cfo/
git commit -m "$MSG" --quiet
git push origin main --quiet
echo "[sync] pushed: $MSG"
