#!/usr/bin/env python3
"""Decision-registry sync gate: keep the GENERATED Ruby copy byte-identical
to the CANONICAL Python registry.

    python3 scripts/sync_decisions_registry.py            # generate the Ruby copy from the canonical Python registry
    python3 scripts/sync_decisions_registry.py --check     # CI: assert identity

Why this exists: ``python/btap/necb/data/decisions.json`` is the one registry
of D-NN decisions. ``btap-necb/lib/btap_necb/data/decisions.json`` is a
GENERATED copy the Ruby gem carries so it never imports across the
package/gem boundary at runtime. The two files must stay byte-identical
through the verification window (see the repo-root CLAUDE.md). Hand-editing
the RUBY copy is FORBIDDEN — this script is the only thing allowed to write
it, and ``--check`` is what CI runs to prove nobody bypassed it.

History: the copy relationship used to run the other way (Ruby canonical,
Python generated), and because the Python copy was once a one-time hand
export rather than a generated artifact, it silently drifted — D-79 was
added to the Ruby registry (79 entries) and never propagated, leaving the
Python copy at 78. That drift is why generation-by-machinery exists at all
rather than by discipline. The direction reversed at R3 (D-81), when the
Python implementation became primary: the Python registry is now canonical
and the Ruby copy is what gets generated.
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

PYTHON_ROOT = Path(__file__).resolve().parent.parent
REPO_ROOT = PYTHON_ROOT.parent

RUBY_REGISTRY = REPO_ROOT / "btap-necb" / "lib" / "btap_necb" / "data" / "decisions.json"
PYTHON_REGISTRY = PYTHON_ROOT / "btap" / "necb" / "data" / "decisions.json"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true",
                         help="exit 1 if the two files are not byte-identical; do not write")
    args = parser.parse_args()

    if not PYTHON_REGISTRY.exists():
        print(f"MISSING: {PYTHON_REGISTRY} — the canonical Python registry does not exist.",
              file=sys.stderr)
        return 1

    canonical_bytes = PYTHON_REGISTRY.read_bytes()

    if args.check:
        if not RUBY_REGISTRY.exists():
            print(f"MISSING: {RUBY_REGISTRY} — the generated Ruby copy does not exist.\n"
                  f"Fix: python3 {Path(__file__).resolve()}", file=sys.stderr)
            return 1
        ruby_bytes = RUBY_REGISTRY.read_bytes()
        if ruby_bytes != canonical_bytes:
            print(f"DRIFT: {RUBY_REGISTRY} is GENERATED from {PYTHON_REGISTRY} and has drifted.\n"
                  f"Fix: python3 {Path(__file__).resolve()}", file=sys.stderr)
            return 1
        print(f"OK: generated {RUBY_REGISTRY} matches canonical {PYTHON_REGISTRY}")
        return 0

    RUBY_REGISTRY.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(PYTHON_REGISTRY, RUBY_REGISTRY)
    print(f"generated {RUBY_REGISTRY} from {PYTHON_REGISTRY} ({len(canonical_bytes)} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
