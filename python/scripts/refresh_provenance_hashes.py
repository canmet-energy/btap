#!/usr/bin/env python3
"""Refresh every edition manifest's provenance ``result_sha256`` from the
shipped bytes (and ``source_sha256`` for the self-archived caches, whose
retained artifact IS the shipped file). Stdlib only. Prints what moved.

Usage: python3 python/scripts/refresh_provenance_hashes.py [--check]
"""
import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2] / "python" / "btap" / "codes" / "necb" / "data"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main(argv) -> int:
    check = "--check" in argv
    moved = []
    for manifest in sorted(ROOT.glob("*/manifest.json")):
        data = json.loads(manifest.read_text(encoding="utf-8"))
        for name, entry in data.get("provenance", {}).items():
            shipped = manifest.parent / name
            if not shipped.is_file():
                continue
            digest = sha256(shipped)
            if entry.get("result_sha256") != digest:
                moved.append(f"{manifest.parent.name}/{name}")
                if entry.get("source_verification") == "archived" and entry.get("source_sha256") == entry.get("result_sha256"):
                    entry["source_sha256"] = digest  # self-archived cache
                entry["result_sha256"] = digest
        if moved and not check:
            text = manifest.read_text(encoding="utf-8")
            match = re.match(r"\{\n( +)", text)
            indent = len(match.group(1)) if match else 2
            manifest.write_text(json.dumps(data, indent=indent, ensure_ascii=False) + "\n", encoding="utf-8")
    for m in moved:
        print(("STALE " if check else "refreshed ") + m)
    if not moved:
        print("provenance hashes: up to date")
    return 1 if (check and moved) else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
