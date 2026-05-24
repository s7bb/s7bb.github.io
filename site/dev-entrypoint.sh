#!/bin/sh
# Container-only entrypoint for the s7bb-site-dev compose service.
#
# 1. Copies /repo/data/latest.json (live s7bb-data tip, mounted read-only
#    via s7bb-data-init) into /repo/site/data/ so Vite serves it at
#    /data/latest.json.
#
# 2. Exports VITE_DEV_NOW from the file's generated_at so the today-page
#    filters (which key off Europe/Berlin "today") treat the bundled data
#    as live.
set -e

SRC=/repo/data/latest.json
DEST_DIR=/repo/site/data
DEST=$DEST_DIR/latest.json

mkdir -p "$DEST_DIR"

if [ -r "$SRC" ]; then
  cp "$SRC" "$DEST"
  GEN=$(sed -n 's/.*"generated_at": "\([^"]*\)".*/\1/p' "$SRC" | head -1)
  if [ -n "$GEN" ]; then
    export VITE_DEV_NOW="$GEN"
    echo "dev-entrypoint: VITE_DEV_NOW=$VITE_DEV_NOW"
  fi
  echo "dev-entrypoint: wrote $DEST (verbatim copy of live data tip)"
else
  echo "dev-entrypoint: $SRC not readable; skipping data prep"
fi

npm ci
exec npm run dev -- --host 0.0.0.0 --port 5173
