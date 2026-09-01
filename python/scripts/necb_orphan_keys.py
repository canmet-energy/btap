#!/usr/bin/env python3
"""Fail when top-level NECB rule keys are not consumed by Python source."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

PYTHON_ROOT = Path(__file__).resolve().parents[1]
PACKAGE_ROOT = PYTHON_ROOT / "btap"
META_KEYS = {"provenance", "article_coverage", "non_rule_keys"}


def _consumed(key: str, source: str) -> bool:
    escaped = re.escape(key)
    return bool(re.search(rf"(?:['\"]{escaped}['\"])", source))


def findings(package_root: Path = PACKAGE_ROOT) -> tuple[list[dict], int, int]:
    manifests = sorted(package_root.glob("**/data/**/*_rules_*.json"))
    sources = sorted(path for path in package_root.glob("**/*.py")
                     if "data" not in path.parts)
    if not manifests:
        raise RuntimeError("necb_orphan_keys scanned no manifests")
    if not sources:
        raise RuntimeError("necb_orphan_keys scanned no Python source")
    source = "\n".join(path.read_text(encoding="utf-8", errors="replace")
                       for path in sources)
    declared: dict[str, list[str]] = {}
    for path in manifests:
        data = json.loads(path.read_text(encoding="utf-8"))
        exempt = set(data.get("non_rule_keys", []))
        for key in data.keys() - META_KEYS - exempt:
            declared.setdefault(key, []).append(path.name)
    result = [
        {"key": key, "files": sorted(set(files))}
        for key, files in sorted(declared.items())
        if not _consumed(key, source)
    ]
    return result, len(manifests), len(declared)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--quiet", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    result, manifest_count, key_count = findings()
    if args.json:
        print(json.dumps({"findings": result, "manifests": manifest_count,
                          "keys": key_count}, sort_keys=True))
    elif not args.quiet:
        if result:
            print(f"necb_orphan_keys: {len(result)} unconsumed rule key(s)")
            for finding in result:
                print(f"  {finding['key']}: {', '.join(finding['files'])}")
        else:
            print("necb_orphan_keys: OK - every rule key is read by Python source")
    return 1 if result else 0


if __name__ == "__main__":
    raise SystemExit(main())