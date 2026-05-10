#!/bin/sh
# Container-only entrypoint for the s7bb-site-dev compose service.
#
# 1. Copies /repo/data/latest.json into /repo/site/data/, shifting every
#    scheduled / actual / expected-slot time by +1 minute. This simulates
#    the parser fix that switched scheduled_time from arrival (e.g. :19,
#    :39, :59) to departure (:20, :40, :00). The committed data file in
#    the repo was produced by the pre-fix fetcher; without this shift the
#    dev site keeps showing :19 / :39 / :59.
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
  node -e "
    const fs = require('fs');
    const j = JSON.parse(fs.readFileSync('$SRC', 'utf8'));
    const shift = (iso) => iso ? new Date(new Date(iso).getTime() + 60000).toISOString() : iso;
    for (const a of (j.arrivals || [])) {
      a.scheduled_time = shift(a.scheduled_time);
      a.actual_time = shift(a.actual_time);
    }
    const slots = (j.expected_slots && j.expected_slots.today) || {};
    for (const k of Object.keys(slots)) slots[k] = slots[k].map(shift);
    fs.writeFileSync('$DEST', JSON.stringify(j, null, 2));
  "
  GEN=$(sed -n 's/.*"generated_at": "\([^"]*\)".*/\1/p' "$SRC" | head -1)
  if [ -n "$GEN" ]; then
    export VITE_DEV_NOW="$GEN"
    echo "dev-entrypoint: VITE_DEV_NOW=$VITE_DEV_NOW"
  fi
  echo "dev-entrypoint: wrote $DEST with +1min time shift (arrival -> departure)"
else
  echo "dev-entrypoint: $SRC not readable; skipping data prep"
fi

npm ci
exec npm run dev -- --host 0.0.0.0 --port 5173
