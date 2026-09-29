#!/usr/bin/env python3
"""Build the D-100 evidence packets: the MECHANICAL half only.

Everything here is read from the tree, never inferred. What it does NOT do is
decide applicability -- no article-prefix heuristic, no keyword counting. It
produces, per decision: the operative Decision clause, every live ``ruling=``
site, and which public code ids can reach each site. The normative half (the
governing article in both editions, and the gem's realization) is fetched
separately, and the ruling is Sol's.
"""

from __future__ import annotations

import ast
import json
import re
import sys
from pathlib import Path

REPO = Path("/workspaces/openstudio-necb-gems")
PYTHON_ROOT = REPO / "python"
SOURCE_DIR = REPO / "docs" / "decisions"
sys.path.insert(0, str(PYTHON_ROOT / "scripts"))
import generate_decisions as G  # noqa: E402

ID_TOKEN = re.compile(r"\bD-\d{2}\b")
AUDIT_METHODS = frozenset({"decision", "info", "warn"})

#: A path under an edition's own package can be reached by that code id alone.
#: Everything else under btap/ is shared, so every registered code id reaches
#: it. This is the reachability fact Sol asked for -- and it is deliberately
#: only half an answer: a SHARED call site is implementation evidence that the
#: code path is common, never proof that the Code requirement is the same in
#: both editions.
EDITION_PACKAGE = re.compile(r"btap/codes/necb/editions/(necb\d{4})/")


def registered_code_ids():
    """Every code id the product actually accepts, from the manifests."""
    ids = []
    for manifest in sorted((PYTHON_ROOT / "btap" / "codes" / "necb" / "data").glob(
            "*/manifest.json")):
        data = json.loads(manifest.read_text(encoding="utf-8"))
        ids.append(data.get("code_id") or manifest.parent.name)
    return sorted(set(ids))


def citation_sites():
    """``{decision id: [(path, line, method)]}`` for every live ``ruling=``."""
    by_id = {}
    for path in sorted((PYTHON_ROOT / "btap").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            method = (node.func.attr if isinstance(node.func, ast.Attribute)
                      else getattr(node.func, "id", None))
            if method not in AUDIT_METHODS:
                continue
            for keyword in node.keywords:
                if keyword.arg != "ruling":
                    continue
                value = keyword.value
                if not (isinstance(value, ast.Constant)
                        and isinstance(value.value, str)):
                    continue
                rel = str(path.relative_to(PYTHON_ROOT))
                for decision_id in ID_TOKEN.findall(value.value):
                    by_id.setdefault(decision_id, []).append(
                        (rel, value.lineno, method))
    return by_id


def reachable_code_ids(sites, all_ids):
    """Which code ids can traverse these sites, and why."""
    if not sites:
        return [], "no live citation site"
    reach, notes = set(), []
    for rel, _line, _method in sites:
        match = EDITION_PACKAGE.search(rel)
        if match:
            reach.add(match.group(1))
            notes.append(f"{rel} is {match.group(1)}-only")
        else:
            reach.update(all_ids)
            notes.append(f"{rel} is shared")
    return sorted(reach), "; ".join(sorted(set(notes)))


DECISION_CLAUSE = re.compile(
    r"^-?\s*\*\*(?:Decision|Decided|What was decided|What)\b[^:]*:?\*\*:?\s*(.+)",
    re.IGNORECASE)


def operative_clause(body):
    """The authored Decision/Decided clause, or the first substantive line.

    Sol asked for the operative clause rather than title/summary keywords. The
    fallback is flagged so a packet never silently presents a heading as a
    ruling.
    """
    lines = body.split("\n")
    for index, line in enumerate(lines[1:], start=1):
        match = DECISION_CLAUSE.match(line.strip())
        if match:
            text = [match.group(1).strip()]
            for follow in lines[index + 1:]:
                if not follow.strip() or follow.lstrip().startswith(("- ", "* ", "#")):
                    break
                text.append(follow.strip())
            return " ".join(text), True
    # No machine-identifiable operative marker. Return the opening PARAGRAPH,
    # flagged, so the packet presents context rather than passing a first line
    # off as a ruling. 35 of the 97 are in this shape -- older entries with
    # topic-specific bold lead-ins and no **Decision:** clause.
    para = []
    for line in lines[1:]:
        if line.strip().startswith(("#", "<")):
            continue
        if not line.strip():
            if para:
                break
            continue
        para.append(line.strip())
    return " ".join(para), False


#: The domain a citation site sits in, taken from its module path -- a fact,
#: not a classification. Decisions with no live site carry no domain, and Sol
#: batches those himself rather than having me guess one.
def domain_of(sites):
    domains = set()
    for rel, _line, _method in sites:
        parts = rel.split("/")
        if "necb" in parts:
            tail = parts[parts.index("necb") + 1:]
            domains.add(tail[0].replace(".py", "") if tail else "necb")
        else:
            domains.add(parts[1] if len(parts) > 1 else parts[0])
    return sorted(domains)


def main():
    all_ids = registered_code_ids()
    sites = citation_sites()
    packets = []
    for path in sorted(SOURCE_DIR.glob("D-*.md")):
        meta, body = G.parse_source(path)
        clause, explicit = operative_clause(body)
        mine = sites.get(meta["id"], [])
        reach, why = reachable_code_ids(mine, all_ids)
        packets.append({
            "id": meta["id"],
            "kind": meta["kind"],
            "title": meta["title"],
            "articles_as_committed": meta["articles"],
            "operative_clause": clause,
            "clause_is_explicit": explicit,
            "citation_sites": [{"file": f, "line": n, "method": m} for f, n, m in mine],
            "reachable_code_ids": reach,
            "reachability_note": why,
            "domains": domain_of(mine),
        })
    out = Path("/home/vscode/.claude/jobs/a100f076/tmp/packets.json")
    out.write_text(json.dumps({"registered_code_ids": all_ids, "packets": packets},
                              indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print(f"registered code ids: {all_ids}")
    print(f"packets: {len(packets)}")
    print(f"  with an explicit Decision clause : "
          f"{sum(1 for p in packets if p['clause_is_explicit'])}")
    print(f"  with >=1 live ruling= site       : "
          f"{sum(1 for p in packets if p['citation_sites'])}")
    print(f"  edition-specific call sites      : "
          f"{sum(1 for p in packets if p['reachable_code_ids'] and len(p['reachable_code_ids']) < len(all_ids))}")
    print(f"  no live site (metadata only)     : "
          f"{sum(1 for p in packets if not p['citation_sites'])}")
    print(f"\nwritten: {out}")


if __name__ == "__main__":
    main()
