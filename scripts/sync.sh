#!/usr/bin/env bash
# Push local work up to GitHub so web/phone sessions can see it.
# Safe to run any time: does nothing when there is nothing to sync.

set -uo pipefail

root=$(git rev-parse --show-toplevel 2>/dev/null) || { echo "sync: not inside a git repo"; exit 0; }
cd "$root" || exit 0

if [ -z "$(git status --porcelain)" ]; then
  exit 0   # nothing changed
fi

branch=$(git rev-parse --abbrev-ref HEAD)

git add -A
git commit -q -m "sync from local — $(date '+%Y-%m-%d %H:%M')" || exit 0

if git push -q -u origin "$branch" 2>/dev/null; then
  echo "sync: pushed to $branch"
else
  echo "sync: saved locally, but push failed (offline, or this branch changed on GitHub too)"
fi
