#!/usr/bin/env bash
# Called by s7bb-export.service after export. Commits and pushes data/latest.json to main.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_DIR"

git add data/latest.json
if git diff --cached --quiet; then
  exit 0  # nothing changed
fi

git commit -m "chore: update latest.json $(date -u +%Y-%m-%dT%H:%M:%SZ)"
git push origin main
