#!/bin/sh
# Tests for docker-entrypoint.sh. Run: sh site/test-entrypoint.sh
# Requires: jq (same dependency the entrypoint itself has).
#
# Note: `set -e` is deliberately NOT enabled. Every case runs the entrypoint
# expecting it to fail sometimes, and captures $? by hand.
set -u

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
ENTRYPOINT="$SCRIPT_DIR/docker-entrypoint.sh"
FAILED=0

pass() { echo "ok   - $1"; }
fail() { echo "FAIL - $1"; FAILED=1; }

# Each case runs the entrypoint with a throwaway web root and a no-op command,
# so it writes config.json and exits instead of execing nginx.
run_case() {
  WEB_ROOT=$(mktemp -d)
  export WEB_ROOT
  S7BB_DATA_BASE_URL="$1"
  export S7BB_DATA_BASE_URL
  OUT=$(sh "$ENTRYPOINT" true 2>&1)
  RC=$?
  CONFIG="$WEB_ROOT/config.json"
}

# 1. Happy path: writes valid JSON with the URL
run_case "https://raw.githubusercontent.com/s7bb/s7bb-data/main"
if [ "$RC" -eq 0 ] && [ "$(jq -r '.dataBaseUrl' "$CONFIG")" = "https://raw.githubusercontent.com/s7bb/s7bb-data/main" ]; then
  pass "writes dataBaseUrl for a normal URL"
else
  fail "writes dataBaseUrl for a normal URL (rc=$RC out=$OUT)"
fi

# 1b. Output is compact single-line JSON, which is what the docs assert
if [ "$(wc -l < "$CONFIG")" -eq 1 ]; then
  pass "writes compact single-line JSON"
else
  fail "writes compact single-line JSON (got $(wc -l < "$CONFIG") lines)"
fi

# 2. JSON-escaping: a quote in the value must not corrupt the file
run_case 'https://evil.example/"x'
if [ "$RC" -eq 0 ] && jq -e . "$CONFIG" >/dev/null 2>&1 \
   && [ "$(jq -r '.dataBaseUrl' "$CONFIG")" = 'https://evil.example/"x' ]; then
  pass "JSON-escapes a value containing a quote"
else
  fail "JSON-escapes a value containing a quote (rc=$RC out=$OUT)"
fi

# 3. Backslash is escaped too
run_case 'https://evil.example/\x'
if [ "$RC" -eq 0 ] && jq -e . "$CONFIG" >/dev/null 2>&1; then
  pass "JSON-escapes a value containing a backslash"
else
  fail "JSON-escapes a value containing a backslash (rc=$RC out=$OUT)"
fi

# 4. Unset variable fails fast, with a FATAL message.
# Assert on the message, not just rc: a missing or broken script also exits
# non-zero, and a bare rc check would pass against it.
WEB_ROOT=$(mktemp -d); export WEB_ROOT
unset S7BB_DATA_BASE_URL
OUT=$(sh "$ENTRYPOINT" true 2>&1); RC=$?
if [ "$RC" -ne 0 ] && echo "$OUT" | grep -q "FATAL: S7BB_DATA_BASE_URL"; then
  pass "fails fast with FATAL when S7BB_DATA_BASE_URL is unset"
else
  fail "fails fast with FATAL when S7BB_DATA_BASE_URL is unset (rc=$RC out=$OUT)"
fi

# 5. Blank value fails fast, with a FATAL message
run_case "   "
if [ "$RC" -ne 0 ] && echo "$OUT" | grep -q "FATAL: S7BB_DATA_BASE_URL"; then
  pass "fails fast with FATAL when S7BB_DATA_BASE_URL is blank"
else
  fail "fails fast with FATAL when S7BB_DATA_BASE_URL is blank (rc=$RC out=$OUT)"
fi

# 6. Local mode with no data warns but still starts
run_case "/data"
if [ "$RC" -eq 0 ] && echo "$OUT" | grep -q "WARN"; then
  pass "warns when base is /data but latest.json is absent"
else
  fail "warns when base is /data but latest.json is absent (rc=$RC out=$OUT)"
fi

# 7. Local mode with data present does not warn
run_case "/data"
mkdir -p "$WEB_ROOT/data" && echo '{}' > "$WEB_ROOT/data/latest.json"
OUT=$(sh "$ENTRYPOINT" true 2>&1); RC=$?
if [ "$RC" -eq 0 ] && ! echo "$OUT" | grep -q "WARN"; then
  pass "does not warn when /data/latest.json exists"
else
  fail "does not warn when /data/latest.json exists (rc=$RC out=$OUT)"
fi

# 8. A path that merely starts with /data must not be treated as local mode
run_case "https://database.example/feed"
if [ "$RC" -eq 0 ] && ! echo "$OUT" | grep -q "WARN"; then
  pass "does not treat a lookalike URL as local mode"
else
  fail "does not treat a lookalike URL as local mode (rc=$RC out=$OUT)"
fi

exit "$FAILED"
