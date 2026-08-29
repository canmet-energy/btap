#!/usr/bin/env bash
# The D-80 R2 generator/CLI matrix: sample GENERATOR (ruby|python) x
# compliance CLI (ruby|python), separating "the generators build equivalent
# corpora" from "the CLIs judge a corpus equivalently".
#
#   bash verification/matrix.sh [WORK_DIR]        # TIER=none (default) | sizing | annual
#
# Tiers none and sizing run ALL FOUR cells and diff:
#   - CLI parity on each corpus:      (R,ruby)~(R,python), (P,ruby)~(P,python)
#   - generator equivalence per CLI:  (R,ruby)~(P,ruby),   (R,python)~(P,python)
# Tier annual is the REDUCED generator check (adjudicated in D-80: a full
# four-cell annual matrix is explicitly not required): the PYTHON CLI runs
# the annual subset over BOTH corpora and results are compared across
# generators — the shared-corpus Ruby-vs-Python annual gate stays in
# selftest.sh (TIER=annual CLI_B=python).
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
WORK="${1:-$(mktemp -d)}"
TIER="${TIER:-none}"

cell() { # cell NAME SAMPLES_GEN CLI
  echo "== cell $1 (samples-gen=$2, cli=$3) =="
  ruby "$HERE/run_corpus.rb" "$WORK/$1" --tier "$TIER" --cli "$3" --samples-gen "$2"
}

diff_pair() { # diff_pair LABEL DIR_A DIR_B
  echo "== $1 =="
  local status=0
  for run_a in "$WORK/$2/$TIER"/*/; do
    local name; name="$(basename "$run_a")"
    python3 "$HERE/compare_runs.py" "$run_a" "$WORK/$3/$TIER/$name" || status=1
  done
  [ "$status" -eq 0 ] || { echo "MATRIX FAILED: $1 diverges" >&2; exit 1; }
}

# Generate each corpus ONCE, then share it into every cell that uses it.
share() { mkdir -p "$WORK/$1"; ln -sfn "$WORK/$2/_samples" "$WORK/$1/_samples"; }

if [ "$TIER" = "annual" ]; then
  cell rp ruby python
  cell pp python python
  diff_pair "generator equivalence, python CLI (annual reduced)" rp pp
  echo "MATRIX OK: tier=annual reduced generator check"
  exit 0
fi

cell rr ruby ruby
share rp rr
cell rp ruby python
cell pr python ruby
share pp pr
cell pp python python

diff_pair "CLI parity on the ruby corpus" rr rp
diff_pair "CLI parity on the python corpus" pr pp
diff_pair "generator equivalence, ruby CLI" rr pr
diff_pair "generator equivalence, python CLI" rp pp
echo "MATRIX OK: all four cells equivalent (tier=$TIER)"
