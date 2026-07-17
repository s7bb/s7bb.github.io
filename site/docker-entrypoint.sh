#!/bin/sh
# Writes config.json from the environment, then hands off to nginx.
#
# The data source is a runtime setting so users switch it with a restart
# instead of a rebuild. Writing bad JSON here would make the site silently
# fall back to its build-time default, so validate and fail fast instead.
set -eu

WEB_ROOT="${WEB_ROOT:-/usr/share/nginx/html}"
CONFIG="$WEB_ROOT/config.json"

if [ -z "${S7BB_DATA_BASE_URL:-}" ] || [ -z "$(printf '%s' "${S7BB_DATA_BASE_URL}" | tr -d ' \t')" ]; then
  echo "FATAL: S7BB_DATA_BASE_URL is unset or blank." >&2
  echo "       Set it in .env, for example:" >&2
  echo "         S7BB_DATA_BASE_URL=https://raw.githubusercontent.com/s7bb/s7bb-data/main" >&2
  exit 1
fi

# jq, not printf: a value containing a quote or backslash would otherwise
# produce invalid JSON and the site would quietly use the wrong data source.
# -c keeps it on one line, which is what the docs and tests assert.
mkdir -p "$WEB_ROOT"
jq -nc --arg u "$S7BB_DATA_BASE_URL" '{dataBaseUrl: $u}' > "$CONFIG"

echo "config: dataBaseUrl=$S7BB_DATA_BASE_URL"

# Exact match on /data or a /data/... path. A bare /data* glob would also
# match https://database.example/... and misfire the warning.
case "$S7BB_DATA_BASE_URL" in
  /data|/data/*)
    if [ ! -r "$WEB_ROOT/data/latest.json" ]; then
      echo "WARN: S7BB_DATA_BASE_URL is '$S7BB_DATA_BASE_URL' but $WEB_ROOT/data/latest.json" >&2
      echo "WARN: is missing. The site will show 'Fehler beim Laden der Daten'." >&2
      echo "WARN: Local data comes from the fetcher. Either start it, or switch to" >&2
      echo "WARN: remote data:" >&2
      echo "WARN:   S7BB_DATA_BASE_URL=https://raw.githubusercontent.com/s7bb/s7bb-data/main" >&2
    fi
    ;;
esac

# Chain to the nginx image's own entrypoint when it is there, so its
# /docker-entrypoint.d/ init scripts still run. Absent on a host running the
# tests, in which case exec the command directly.
if [ -x /docker-entrypoint.sh ]; then
  exec /docker-entrypoint.sh "$@"
fi
exec "$@"
