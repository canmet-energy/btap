#!/usr/bin/env python3
"""Shared roots, states and IO for the D-100 research pipeline.

Roots are derived from this file's own location, never hard-coded, so every
stage is reproducible from the commit rather than from one machine's scratch
directory (Sol, `061` item 3).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

#: pipeline/common.py -> d100 -> research -> repository root
PIPELINE_DIR = Path(__file__).resolve().parent
ARTIFACT_ROOT = PIPELINE_DIR.parent
REPO_ROOT = ARTIFACT_ROOT.parents[1]
PYTHON_ROOT = REPO_ROOT / "python"
SOURCE_DIR = REPO_ROOT / "docs" / "decisions"

#: The binding successor grammar (Sol, `061` item 7). `D-\d{2}` would not match
#: D-100 at all, so every stage would silently drop the decisions this research
#: exists to classify the moment they are allocated.
DECISION_ID = r"D-(?:0[1-9]|[1-9][0-9]+)"
DECISION_ID_RE = re.compile(r"\b" + DECISION_ID + r"\b")
DECISION_ID_FULL_RE = re.compile(r"\A" + DECISION_ID + r"\Z")

#: How a request resolved. NEVER collapsed onto a boolean `exists`: a server
#: returning nothing is not the same claim as an article being absent from the
#: edition, and neither is a transport failure (Sol, `061` item 1).
PRESENT = "present"
MCP_EMPTY = "mcp_empty"
HIERARCHY_ABSENT = "hierarchy_absent"
#: The server answered, but with a DIFFERENT number or edition than requested.
#: HBIX answers the 2020 request for `8.4.4.1` with Table `8.4.4.12`, so a
#: non-empty payload is not success unless it identifies itself as the thing
#: asked for (Sol, `065` item 1). Not folded into `present`, and not folded into
#: `error` either: the corpus stays complete and inspectable, and the RUN exits
#: non-zero so it cannot be mistaken for a clean one.
RETURNED_MISMATCH = "returned_mismatch"
ERROR = "error"
STATES = (PRESENT, MCP_EMPTY, HIERARCHY_ABSENT, RETURNED_MISMATCH, ERROR)


class ResearchError(RuntimeError):
    """A transport/auth/protocol failure. Fails the run rather than producing a
    successful-looking corpus with a hole in it."""


def out_dir(argv=None, description=""):
    """``--out`` for every stage, defaulting to the committed artifact root."""
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("--out", type=Path, default=ARTIFACT_ROOT,
                        help="where to write artifacts (default: the committed "
                             "research/d100/)")
    args = parser.parse_args(argv)
    args.out.mkdir(parents=True, exist_ok=True)
    return args.out


def write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False,
                               sort_keys=True) + "\n", encoding="utf-8")


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def request_key(request: dict) -> str:
    """A stable filename-safe key for ONE exact request.

    Keyed on the tool as well as the number and edition, because an article and
    a table of the same number are different requests and collapsing them onto
    a base number is what let a table be "fetched" as a section (Sol, `061`
    item 4).
    """
    parts = [request["tool"], request.get("code", "necb"),
             str(request.get("section_number") or request.get("table_number")),
             str(request.get("edition"))]
    return "__".join(re.sub(r"[^A-Za-z0-9.-]", "_", p) for p in parts)


REGISTRY = PYTHON_ROOT / "btap" / "codes" / "data" / "decisions.json"
AGGREGATE = REPO_ROOT / "docs" / "necb_decisions.md"


def decision_sources():
    """``[(id, meta, body)]`` for every decision, from whichever layout exists.

    Per-decision sources (`docs/decisions/D-NN.md`) are canonical once that
    migration lands; until then the same content lives in the registry plus the
    aggregate document. Reading both shapes keeps this pipeline reproducible on
    either, rather than only on the branch it was written against.
    """
    if SOURCE_DIR.is_dir() and any(SOURCE_DIR.glob("D-*.md")):
        import sys
        sys.path.insert(0, str(PYTHON_ROOT / "scripts"))
        import generate_decisions as G

        return [(m["id"], m, b) for m, b in
                (G.parse_source(p) for p in sorted(SOURCE_DIR.glob("D-*.md")))]

    entries = {e["id"]: e for e in read_json(REGISTRY)["decisions"]}
    text = AGGREGATE.read_text(encoding="utf-8")
    lines = text.split("\n")
    heads = [i for i, line in enumerate(lines)
             if re.match(r"^## (" + DECISION_ID + r")\b", line)]
    out = []
    for position, head in enumerate(heads):
        decision_id = re.match(r"^## (" + DECISION_ID + r")", lines[head]).group(1)
        stop = heads[position + 1] if position + 1 < len(heads) else len(lines)
        body = "\n".join(lines[head:stop]).rstrip("\n") + "\n"
        if decision_id in entries:
            out.append((decision_id, entries[decision_id], body))
    missing = sorted(set(entries) - {i for i, _m, _b in out})
    if missing:
        raise ResearchError(f"registry entries with no document section: {missing}")
    return out
