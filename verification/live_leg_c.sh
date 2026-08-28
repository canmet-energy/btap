#!/usr/bin/env bash
# Live Leg C (D-78/D-80): Python vs the LIVE pinned oracle, end to end.
#
#   verification/live_leg_c.sh [WORK_DIR]
#
# Stages (python-prep / ruby-probe):
#   1. python/scripts/oracle_prep.py       — Python builds the prep models
#   2. verification/oracle/export_goldens.rb (pin bundle) — Ruby probes the
#      pinned oracle into a FRESH goldens directory (never touches committed)
#   3. verification/oracle/compare_goldens.py — committed goldens ≡ live oracle
#   4. pytest over the goldens test files with BTAP_ORACLE_GOLDENS=<fresh>
#      and BTAP_GOLDENS_REQUIRED=1         — Python ≡ live oracle
#
# The test-file list and the expected collected count come from
# request_manifest.json (one source of truth — adding a goldens test updates
# the manifest, not this script). The pytest stage must finish with ZERO
# skips: passed == collected is asserted, because a dependency-based skip
# inside a required oracle gate is the green-but-vacuous failure this repo
# documents.
#
# Requires: the pin bundle (BUNDLE_GEMFILE=legacy_pin/Gemfile bundle check),
# python/.venv, and the OpenStudio SDK in both runtimes.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORK="${1:-$(mktemp -d)}"
PREP="$WORK/prep"
FRESH="$WORK/goldens"
MANIFEST="$ROOT/verification/oracle/request_manifest.json"
PY="${BTAP_PYTHON:-$ROOT/python/.venv/bin/python}"

echo "== live Leg C — work dir $WORK"

echo "== 1/4 python prep"
"$PY" "$ROOT/python/scripts/oracle_prep.py" --out "$PREP"

echo "== 2/4 oracle export (pin bundle)"
BUNDLE_GEMFILE="$ROOT/legacy_pin/Gemfile" bundle exec \
  ruby "$ROOT/verification/oracle/export_goldens.rb" --prep "$PREP" --out "$FRESH"

echo "== 3/4 committed goldens ≡ live oracle"
python3 "$ROOT/verification/oracle/compare_goldens.py" "$FRESH"

echo "== 4/4 python ≡ live oracle (zero skips required)"
mapfile -t FILES < <("$PY" -c "
import json
m = json.load(open('$MANIFEST'))
print('\n'.join(m['pytest']['files']))
")
EXPECTED=$("$PY" -c "
import json
print(json.load(open('$MANIFEST'))['pytest']['collected'])
")
REPORT="$WORK/pytest"
(cd "$ROOT/python" && BTAP_ORACLE_GOLDENS="$FRESH" BTAP_GOLDENS_REQUIRED=1 \
  "$PY" -m pytest -q -p no:cacheprovider "${FILES[@]}" \
  --junitxml="$REPORT.xml" | tail -3)

"$PY" - "$REPORT.xml" "$EXPECTED" <<'PYEOF'
import sys
import xml.etree.ElementTree as ET
suite = ET.parse(sys.argv[1]).getroot().find("testsuite")
run = int(suite.get("tests")); expected = int(sys.argv[2])
bad = {k: int(suite.get(k)) for k in ("failures", "errors", "skipped")}
if any(bad.values()):
    sys.exit(f"live Leg C NOT green: {bad} — a skip here is green-but-vacuous")
if run != expected:
    sys.exit(f"collected/ran {run} tests but the request manifest expects {expected} — "
             "update request_manifest.json['pytest'] via an adjudicated change")
print(f"live Leg C green: {run}/{expected} tests, 0 skips — "
      "Python ≡ live oracle AND committed ≡ live oracle")
PYEOF
