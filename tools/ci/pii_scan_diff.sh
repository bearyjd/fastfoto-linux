#!/bin/sh
# Scans the lines a branch adds for text that must not be published: private network addresses
# and personal paths. Usage: tools/ci/pii_scan_diff.sh BASE   (BASE is a tag or commit; it scans
# `git diff BASE...HEAD`). Exits 1 and prints the hits when there is one, 0 when there is none.
#
# Patterns that name this project's own private values (scanner serial numbers, e-mail addresses,
# host names) are not kept in this public repository. Put them, one extended regular expression
# per line, in a file outside the checkout and name it in FASTFOTO_PII_EXTRA_FILE. The release
# checklist (docs/release-process.md) requires that file to exist.
#
# This script is left out of its own scan, as is its test, because they contain the patterns.
set -eu

[ "$#" -eq 1 ] || { echo "usage: $0 BASE" >&2; exit 64; }
base=$1

patterns='192\.168\.|/var/home|/home/user'
if [ -n "${FASTFOTO_PII_EXTRA_FILE:-}" ]; then
  [ -r "$FASTFOTO_PII_EXTRA_FILE" ] || { echo "cannot read FASTFOTO_PII_EXTRA_FILE" >&2; exit 66; }
  extra=$(grep -v '^[[:space:]]*$' "$FASTFOTO_PII_EXTRA_FILE" | paste -sd '|' -)
  [ -z "$extra" ] || patterns="$patterns|$extra"
fi

added=$(git diff "$base"...HEAD -U0 --no-color -- . \
  ':(exclude)tools/ci/pii_scan_diff.sh' ':(exclude)tests/ci/test_pii_scan_diff.py' |
  grep '^+' | grep -v '^+++' || true)

hits=$(printf '%s\n' "$added" | grep -n -E "$patterns" || true)
if [ -n "$hits" ]; then
  echo "PII scan: added lines match a forbidden pattern:" >&2
  printf '%s\n' "$hits" >&2
  exit 1
fi
echo "PII scan: no hits in $(printf '%s\n' "$added" | grep -c .) added lines"
