#!/usr/bin/env python3
"""Decision-registry sync gate: keep the packaged Python copy byte-identical
to the AUTHORITATIVE Ruby registry.

    python3 scripts/sync_decisions_registry.py            # copy Ruby -> Python
    python3 scripts/sync_decisions_registry.py --check     # CI: assert identity

Why this exists: ``btap-necb/lib/btap_necb/data/decisions.json`` is the one
registry of D-NN decisions, maintained by hand through the Ruby support
window (see the repo-root CLAUDE.md). ``python/btap/necb/data/decisions.json``
is a packaged runtime COPY the Python port ships so it never imports across
the gem/package boundary at runtime. Because the copy was a one-time
hand-export rather than a generated artifact, it silently drifted: D-79 was
added to the Ruby registry (79 entries) and never propagated, leaving the
Python copy at 78. Hand-editing the Python copy is FORBIDDEN — the two files
must be identical by construction, not by discipline, so this script is the
only thing allowed to write the Python side, and ``--check`` is what CI runs
to prove nobody bypassed it.
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

    ruby_bytes = RUBY_REGISTRY.read_bytes()

    if args.check:
        if not PYTHON_REGISTRY.exists():
            print(f"MISSING: {PYTHON_REGISTRY}\n"
                  f"Fix: python3 {Path(__file__).resolve()}", file=sys.stderr)
            return 1
        python_bytes = PYTHON_REGISTRY.read_bytes()
        if ruby_bytes != python_bytes:
            print(f"DRIFT: {RUBY_REGISTRY} and {PYTHON_REGISTRY} are not byte-identical.\n"
                  f"Fix: python3 {Path(__file__).resolve()}", file=sys.stderr)
            return 1
        print(f"OK: {PYTHON_REGISTRY} matches {RUBY_REGISTRY}")
        return 0

    PYTHON_REGISTRY.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(RUBY_REGISTRY, PYTHON_REGISTRY)
    print(f"synced {RUBY_REGISTRY} -> {PYTHON_REGISTRY} ({len(ruby_bytes)} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
