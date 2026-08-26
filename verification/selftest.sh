#!/usr/bin/env bash
# Leg-B harness SELF-TEST (D-78): run the corpus TWICE with the Ruby CLI and
# diff every pair — must be zero-diff. Proves two things before any Python
# exists: the pipeline's outputs are deterministic, and the differ works.
#
#   bash verification/selftest.sh [WORK_DIR]
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(dirname "$HERE")"
WORK="${1:-$(mktemp -d)}"
TIER="${TIER:-none}"

echo "== pass A =="
ruby "$HERE/run_corpus.rb" "$WORK/a" --tier "$TIER"
echo "== pass B =="
# share the generated samples so both passes run the SAME models
mkdir -p "$WORK/b"
[ -e "$WORK/b/_samples" ] || ln -s "$WORK/a/_samples" "$WORK/b/_samples"
ruby "$HERE/run_corpus.rb" "$WORK/b" --tier "$TIER"

echo "== diff every pair =="
status=0
for run_a in "$WORK/a/$TIER"/*/; do
  name="$(basename "$run_a")"
  run_b="$WORK/b/$TIER/$name"
  python3 "$HERE/compare_runs.py" "$run_a" "$run_b" || status=1
done
if [ "$status" -ne 0 ]; then
  echo "SELF-TEST FAILED: nondeterminism in the pipeline or a differ bug" >&2
  exit 1
fi
echo "SELF-TEST OK: every pair equivalent"
