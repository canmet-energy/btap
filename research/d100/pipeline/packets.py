#!/usr/bin/env python3
"""Stage 4 — assemble the mechanical half of one packet per decision.

What this stage will NOT do:

* put a fallback paragraph in `operative_clause`. Where no explicit current
  clause is found it emits `null`, an `opening_context` for orientation, and
  `requires_human_resolution: true`. D-19's opening paragraph states an OPEN
  problem and its ruling is three subsections later; promoting the opening
  would have described the problem as the decision (Sol, `058`, `061` item 6).
* assign code ids from a file's directory. The field is named
  `path_based_candidates` so it cannot be read as reachability (Sol, `061`
  item 5).

It also surfaces every decision whose body carries an amendment, correction or
resolution subsection, since for those the first clause is by construction not
the current one.
"""

from __future__ import annotations

import re
from collections import defaultdict

from common import (DECISION_ID, PYTHON_ROOT, decision_sources, out_dir,
                    read_json, write_json)

#: An explicit operative marker. Anything else is context, not a ruling.
CLAUSE_RE = re.compile(
    r"^-?\s*\*\*(Decision|Decided|Ruling|Resolution|Adopted)\b[^:*]*:?\*\*:?\s*(.+)",
    re.IGNORECASE)
#: A later layer that supersedes or qualifies what came before.
LAYER_RE = re.compile(
    r"^###\s+(.*(?:amend|correction|resolution|supersed|withdraw|reopen|closed"
    r"|verdict|update|revisit).*)$", re.IGNORECASE | re.MULTILINE)
EDITION_PACKAGE = re.compile(r"btap/codes/necb/editions/(necb\d{4})/")


def layers(body):
    return [m.group(1).strip() for m in LAYER_RE.finditer(body)]


def operative(body):
    """``(clause, source_span, needs_human)``.

    A clause is returned only from an explicit marker, and only from the LAST
    such marker, because a later Decision supersedes an earlier one.
    """
    lines = body.split("\n")
    found = None
    for index, line in enumerate(lines):
        match = CLAUSE_RE.match(line.strip())
        if match:
            text = [match.group(2).strip()]
            for follow in lines[index + 1:]:
                if not follow.strip() or follow.lstrip().startswith(("- ", "* ", "#")):
                    break
                text.append(follow.strip())
            found = (" ".join(text), f"line {index + 1}")
    if found:
        return found[0], found[1], False
    context = []
    for line in lines[1:]:
        if line.strip().startswith(("#", "<")):
            continue
        if not line.strip():
            if context:
                break
            continue
        context.append(line.strip())
    return None, None, True


def path_candidates(sites):
    """Which code ids a site's DIRECTORY would permit -- evidence about the
    file, never a reachability claim."""
    out = set()
    for site in sites:
        match = EDITION_PACKAGE.search(site["module"])
        out.add(match.group(1) if match else "shared-module:any-registered-id")
    return sorted(out)


def main(argv=None):
    out = out_dir(argv, __doc__)
    citations = read_json(out / "citations.json")["citations"]
    traces = read_json(out / "traces.json")
    by_citation = defaultdict(list)
    for citation, entry in citations.items():
        for decision_id in entry["cited_by"]:
            by_citation[decision_id].append(citation)

    packets = []
    for decision_id, meta, body in decision_sources():
        clause, span, needs_human = operative(body)
        sites = traces.get(decision_id, [])
        context = None
        if needs_human:
            _c, _s, _n = None, None, None
            lines = [ln.strip() for ln in body.split("\n")[1:] if ln.strip()]
            context = " ".join(lines[:6])[:600] if lines else None
        packets.append({
            "id": decision_id,
            "kind": meta["kind"],
            "title": meta["title"],
            "citations_as_committed": sorted(by_citation.get(decision_id, [])),
            "operative_clause": clause,
            "operative_source_span": span,
            "opening_context": context,
            "requires_human_resolution": needs_human,
            "superseding_layers": layers(body),
            "ruling_sites": [{"module": s["module"], "line": s["line"],
                              "function": s["function"], "guards": s["guards"],
                              "unverified_candidate_chains":
                                  s["unverified_candidate_chains"],
                              "chain_corroborated": s["chain_corroborated"],
                              "per_code_chain": s["per_code_chain"],
                              "requires_human_resolution":
                                  s["requires_human_resolution"]}
                             for s in sites],
            "path_based_candidates": path_candidates(sites),
            "scope": None,
            "code_ids": None,
            "audiences": None,
            "articles": None,
        })

    write_json(out / "packets.json", {"packet_count": len(packets),
                                      "packets": packets})
    needs = [p["id"] for p in packets if p["requires_human_resolution"]]
    layered = [p["id"] for p in packets if p["superseding_layers"]]
    print(f"packets: {len(packets)}")
    print(f"  with an explicit operative clause        : "
          f"{len(packets) - len(needs)}")
    print(f"  operative_clause null, human required    : {len(needs)}")
    print(f"  carrying a superseding layer            : {len(layered)}")
    print(f"    {' '.join(layered)}")
    print(f"  with at least one ruling site           : "
          f"{sum(1 for p in packets if p['ruling_sites'])}")
    print("  scope/code_ids/audiences/articles are null in every packet: they "
          "are Sol's to rule, and nothing here proposes them.")
    print(f"written: {out / 'packets.json'}")


if __name__ == "__main__":
    main()
