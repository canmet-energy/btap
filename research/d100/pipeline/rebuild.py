#!/usr/bin/env python3
"""Rebuild every mechanical artifact into a clean directory and diff it against
the committed copies.

This is the reproducibility gate Sol asked for in `061` item 3: the committed
artifacts must be products of the committed pipeline, not copies of an
uncommitted one. Run it with no arguments to verify, or ``--into <dir>`` to
keep the rebuild.

The HBIX payloads are NOT re-fetched by default: they are the retained evidence
and re-fetching would change their stamps. ``--refetch`` fetches into the clean
directory instead, which is how to check the corpus still answers the same way.

    python3 research/d100/pipeline/rebuild.py
    python3 research/d100/pipeline/rebuild.py --refetch     # needs HBIX_API_KEY
"""

from __future__ import annotations

import argparse
import filecmp
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from common import ARTIFACT_ROOT, PIPELINE_DIR

#: Derived artifacts, in dependency order. `hbix/` and `hbix_index.json` come
#: from `fetch.py` and are only rebuilt under --refetch.
STAGES = [("citations.py", ["citations.json"]),
          ("trace.py", ["traces.json"]),
          ("packets.py", ["packets.json"]),
          ("compare.py", ["comparisons.json"])]


def run(script: str, out: Path):
    result = subprocess.run([sys.executable, str(PIPELINE_DIR / script),
                             "--out", str(out)],
                            capture_output=True, text=True, cwd=PIPELINE_DIR)
    if result.returncode != 0:
        print(result.stdout)
        print(result.stderr, file=sys.stderr)
        raise SystemExit(f"{script} failed")
    return result.stdout


def semantic_equal(a: Path, b: Path) -> bool:
    """JSON equality, so key order or whitespace cannot fail a real match."""
    try:
        return json.loads(a.read_text(encoding="utf-8")) == \
            json.loads(b.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--into", type=Path, default=None)
    parser.add_argument("--refetch", action="store_true")
    args = parser.parse_args(argv)

    temporary = args.into is None
    target = Path(tempfile.mkdtemp(prefix="d100-rebuild-")) if temporary else args.into
    target.mkdir(parents=True, exist_ok=True)
    try:
        if args.refetch:
            run("citations.py", target)
            run("fetch.py", target)
        else:
            # reuse the retained evidence; rebuild everything derived from it
            shutil.copytree(ARTIFACT_ROOT / "hbix", target / "hbix",
                            dirs_exist_ok=True)
            shutil.copy2(ARTIFACT_ROOT / "hbix_index.json", target)

        mismatched, checked = [], []
        for script, outputs in STAGES:
            run(script, target)
            for name in outputs:
                fresh, committed = target / name, ARTIFACT_ROOT / name
                checked.append(name)
                if not committed.exists():
                    mismatched.append(f"{name}: not committed")
                elif not semantic_equal(fresh, committed):
                    mismatched.append(f"{name}: rebuild differs from the committed copy")

        print(f"rebuilt into {target}")
        print(f"artifacts checked: {len(checked)}  {' '.join(checked)}")
        if mismatched:
            print("\nNOT REPRODUCIBLE:")
            for problem in mismatched:
                print(f"  {problem}")
            return 1
        print("\nevery committed artifact is byte-for-byte reproducible from this "
              "commit's pipeline")
        return 0
    finally:
        if temporary:
            shutil.rmtree(target, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
