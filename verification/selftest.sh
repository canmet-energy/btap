#!/usr/bin/env bash
# Leg-B harness SELF-TEST (D-78): run the corpus TWICE and diff every pair —
# must be zero-diff.
#
#   bash verification/selftest.sh [WORK_DIR]
#
# CLI_B selects pass B's implementation:
#   CLI_B=ruby   (default) both passes use the Ruby CLI — proves the
#                pipeline's outputs are deterministic and the differ works.
#   CLI_B=python (M6) pass B uses the PYTHON CLI — the Leg-B cross-language
#                convergence gate: Ruby vs Python over the whole corpus.
set -euo pipefail
# D-80 R4 (D-82): DORMANT — replaced by the frozen scenario suite
# (verification/scenarios/). BTAP_LEGB=1 runs it anyway; deleted at R6.
if [ "${BTAP_LEGB:-}" != "1" ]; then
  echo "DORMANT since R4 (D-82): live Leg B was replaced by the frozen" >&2
  echo "scenario suite — see verification/scenarios/ and" >&2
  echo "python/tests/necb/test_frozen_scenarios.py. BTAP_LEGB=1 overrides." >&2
  exit 2
fi

HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(dirname "$HERE")"
WORK="${1:-$(mktemp -d)}"
TIER="${TIER:-none}"
CLI_B="${CLI_B:-ruby}"

echo "== pass A (ruby) =="
ruby "$HERE/run_corpus.rb" "$WORK/a" --tier "$TIER" --cli ruby
echo "== pass B ($CLI_B) =="
# share the generated samples so both passes run the SAME models
mkdir -p "$WORK/b"
[ -e "$WORK/b/_samples" ] || ln -s "$WORK/a/_samples" "$WORK/b/_samples"
ruby "$HERE/run_corpus.rb" "$WORK/b" --tier "$TIER" --cli "$CLI_B"

echo "== diff every pair =="
status=0
for run_a in "$WORK/a/$TIER"/*/; do
  name="$(basename "$run_a")"
  run_b="$WORK/b/$TIER/$name"
  python3 "$HERE/compare_runs.py" "$run_a" "$run_b" || status=1
done
if [ "$status" -ne 0 ]; then
  if [ "$CLI_B" = "python" ]; then
    echo "SELF-TEST FAILED: Ruby and Python runs diverge under the Leg-B rules" >&2
  else
    echo "SELF-TEST FAILED: nondeterminism in the pipeline or a differ bug" >&2
  fi
  exit 1
fi
echo "SELF-TEST OK: every pair equivalent (A=ruby, B=$CLI_B, tier=$TIER)"
