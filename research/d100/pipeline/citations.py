#!/usr/bin/env python3
"""Stage 1 — extract every citation from the decision sources, TYPED.

A citation's type decides which tool can answer it: an article or an Appendix
note is a `get_section`, a table's values are a `get_table`. Collapsing all
three onto a base number and calling `get_section` for everything is what let a
table be reported as fetched when the payload held only table metadata (Sol,
`061` item 4).

Writes `citations.json`: every citation as authored, its type, the decisions
citing it, and the exact request(s) needed to answer it in one edition.
"""

from __future__ import annotations

import re

from common import ARTIFACT_ROOT, decision_sources, out_dir, write_json  # noqa: E402

EDITIONS = ("necb2020", "necb2025")

#: `Note A-8.4.4.13.` / `A-8.4.4.13.(2)` — an Appendix note, fetched as a
#: section under its own printed number.
NOTE_RE = re.compile(r"^(?:Note\s+)?(A-[\d.]+(?:\(\d+\))*[a-z)(]*)\.?$")
#: `Table 8.4.4.7.-B` / `Table 3.2.2.2.` — structured values.
TABLE_RE = re.compile(r"^Table\s+([\d.]+(?:-[A-Z])?)\.?(?:\s+Note\s*\((\d+)\))?$")
#: `8.4.4.14.(2)(a)` — an article, optionally down to clause, and optionally a
#: sentence RANGE (`5.2.2.8.(4)-(5)`), which the record does use.
ARTICLE_RE = re.compile(
    r"^([\d.]+?)\.?((?:\(\d+\))*(?:-\(\d+\))?(?:\([a-z]\))*)$")
#: `8.4.5.5.-C` — a table by its designator, cited without the `Table` prefix.
BARE_TABLE_RE = re.compile(r"^([\d.]+?\.?-[A-Z])\.?$")


def classify(citation: str):
    """``(kind, base, fragment)`` for one authored citation string."""
    text = citation.strip()
    note = NOTE_RE.match(text)
    if note:
        return "note", note.group(1).rstrip("."), ""
    table = TABLE_RE.match(text)
    if table:
        return "table", table.group(1), (f"Note ({table.group(2)})"
                                         if table.group(2) else "")
    # A trailing `-A`/`-B`/`-C` is the NRC table designator; no article carries
    # one. D-03 cites two tables in exactly this form WITHOUT the `Table`
    # prefix, so the type is unambiguous but the record's style is not.
    bare_table = BARE_TABLE_RE.match(text)
    if bare_table:
        return "table_prefix_omitted", bare_table.group(1), ""
    article = ARTICLE_RE.match(text)
    if article:
        return "article", article.group(1), article.group(2)
    return "unclassified", text, ""


def requests_for(kind: str, base: str, edition: str):
    """The exact request(s) that answer this citation in ``edition``.

    A table Note needs BOTH the structured table and the enclosing section's
    note text, so it yields two requests rather than one (Sol, `061` item 4).
    """
    year = edition.replace("necb", "")
    if kind.startswith("table"):
        yield {"tool": "get_table", "code": "necb", "table_number": base,
               "edition": year}
        yield {"tool": "get_section", "code": "necb", "section_number": base,
               "edition": year}
    else:
        yield {"tool": "get_section", "code": "necb", "section_number": base,
               "edition": year}


def main(argv=None):
    out = out_dir(argv, __doc__)
    citations, unclassified = {}, []
    for decision_id, meta, _body in decision_sources():
        for citation in meta["articles"]:
            kind, base, fragment = classify(citation)
            if kind == "unclassified":
                unclassified.append((decision_id, citation))
            entry = citations.setdefault(citation, {
                "kind": kind, "base": base, "fragment": fragment,
                "cited_by": [], "requests": {},
            })
            if decision_id not in entry["cited_by"]:
                entry["cited_by"].append(decision_id)
            for edition in EDITIONS:
                entry["requests"][edition] = list(requests_for(kind, base, edition))

    # one flat, de-duplicated request list — every count downstream is derived
    # from this, so no stage can report a number the corpus does not contain
    # (Sol, `061` item 2)
    flat = {}
    for citation, entry in citations.items():
        for edition, requests in entry["requests"].items():
            for request in requests:
                flat.setdefault(str(sorted(request.items())), request)

    payload = {"editions": list(EDITIONS), "citations": citations,
               "requests": list(flat.values()),
               "unclassified": [{"decision": d, "citation": c}
                                for d, c in unclassified]}
    write_json(out / "citations.json", payload)

    kinds = {}
    for entry in citations.values():
        kinds[entry["kind"]] = kinds.get(entry["kind"], 0) + 1
    print(f"citations: {len(citations)}  kinds: {kinds}")
    print(f"distinct requests (both editions, typed): {len(flat)}")
    if unclassified:
        print(f"UNCLASSIFIED ({len(unclassified)}) — these need a human:")
        for decision_id, citation in unclassified:
            print(f"  {decision_id}: {citation!r}")
    print(f"written: {out / 'citations.json'}")


if __name__ == "__main__":
    main()
