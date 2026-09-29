#!/usr/bin/env python3
"""Stage 5 — compare each cited provision across editions.

Normalises exactly two things and says so:

1. **Both subsection renumberings**, in ONE edition-keyed pass. The reference
   subsection moved 8.4.4 -> 8.4.5 and the prescriptive subsection moved
   8.4.5 -> 8.4.6, so a sequential rewrite can move one reference twice. A
   token matching neither the edition's reference nor its prescriptive digit is
   left alone -- which matters because NECB 2025's Subsection 8.4.4 is live and
   holds the archetype-EUI path (Sol, `060`).
2. **Observed subscript glyphs**, from an explicit allowlist. NOT global NFKD,
   which also folds superscripts and would erase the exponent in `(5/75)^n`
   and the `m^2` in a units string (Sol, `059` item 1).

Nothing else. A difference that survives is reported as a span, not scored:
`similarity 1.000` hid four real changes behind a rounded float.

Comparison is at the CITED FRAGMENT where the payload exposes sentences, and
whole-article otherwise -- with which one it used recorded per comparison, so a
whole-article verdict is never read as a fragment verdict (Sol, `059`).
"""

from __future__ import annotations

import difflib
import re

from common import MCP_EMPTY, PRESENT, out_dir, read_json, request_key, write_json

SUBSCRIPTS = {"ₚ": "p", "ₐ": "a", "ᵣ": "r", "ₜ": "t", "ₑ": "e", "ₒ": "o",
              "ₓ": "x", "ᵢ": "i", "ₙ": "n", "ₛ": "s", "ₘ": "m", "ₗ": "l",
              "ₖ": "k", "ₕ": "h", "ᵤ": "u", "ᵥ": "v", "ⱼ": "j",
              "₀": "0", "₁": "1", "₂": "2", "₃": "3", "₄": "4", "₅": "5",
              "₆": "6", "₇": "7", "₈": "8", "₉": "9"}
SUPERSCRIPTS = set("⁰¹²³⁴⁵⁶⁷⁸⁹ⁿᵐ")
CITE_RE = re.compile(r"(A-)?8\.4\.(4|5|6)\.")
#: Which subsection is the reference path and which the prescriptive one, per
#: edition. Keyed explicitly rather than derived, so the mapping is readable.
SUBSECTIONS = {"2020": {"4": "REF", "5": "PRE"},
               "2025": {"5": "REF", "6": "PRE"}}


def rewrite_citations(text: str, edition: str) -> str:
    mapping = SUBSECTIONS[edition]

    def sub(match):
        prefix, digit = match.group(1) or "", match.group(2)
        role = mapping.get(digit)
        return f"{prefix}8.4.{role}." if role else match.group(0)

    return CITE_RE.sub(sub, text)


def normalise(text: str, edition: str) -> str:
    text = rewrite_citations(text, edition)
    text = "".join(SUBSCRIPTS.get(c, c) for c in text)
    return " ".join(text.split())


SENTENCE_RE = re.compile(r"(?m)^(\d+)\)\s")


def fragment_of(full_text: str, fragment: str):
    """The cited sentence's text, or None when it cannot be isolated."""
    match = re.match(r"^\((\d+)\)", fragment or "")
    if not match or not full_text:
        return None
    wanted = match.group(1)
    marks = [(m.group(1), m.start()) for m in SENTENCE_RE.finditer(full_text)]
    for index, (number, start) in enumerate(marks):
        if number == wanted:
            end = marks[index + 1][1] if index + 1 < len(marks) else len(full_text)
            return full_text[start:end]
    return None


def payload_for(out, request):
    path = out / "hbix" / f"{request_key(request)}.json"
    return read_json(path) if path.exists() else None


def main(argv=None):
    out = out_dir(argv, __doc__)
    citations = read_json(out / "citations.json")["citations"]
    results = {}
    for citation, entry in citations.items():
        sides = {}
        for edition, requests in entry["requests"].items():
            year = edition.replace("necb", "")
            section = next((r for r in requests if r["tool"] == "get_section"), None)
            archived = payload_for(out, section) if section else None
            sides[year] = archived
        left, right = sides.get("2020"), sides.get("2025")
        record = {"kind": entry["kind"], "fragment": entry["fragment"],
                  "cited_by": entry["cited_by"],
                  "state_2020": (left or {}).get("meta", {}).get("state"),
                  "state_2025": (right or {}).get("meta", {}).get("state")}
        if not (left and right) or record["state_2020"] != PRESENT \
                or record["state_2025"] != PRESENT:
            record["verdict"] = "not comparable at this address"
            record["note"] = ("one side is {} / {} — an empty answer is not proven "
                              "Code absence; the paired provision must be "
                              "established positively".format(record["state_2020"],
                                                              record["state_2025"]))
            results[citation] = record
            continue
        a_full = left["payload"].get("full_text", "")
        b_full = right["payload"].get("full_text", "")
        a_frag, b_frag = fragment_of(a_full, entry["fragment"]), \
            fragment_of(b_full, entry["fragment"])
        granularity = "cited fragment" if (a_frag and b_frag) else "whole article"
        a = normalise(a_frag or a_full, "2020")
        b = normalise(b_frag or b_full, "2025")
        spans = [(t, a[i1:i2][:90], b[j1:j2][:90]) for t, i1, i2, j1, j2 in
                 difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes()
                 if t != "equal"]
        record.update({
            "granularity": granularity,
            "verdict": "substantively identical" if not spans else "differs",
            "diff_spans": spans,
            "superscripts_present": sorted(
                SUPERSCRIPTS & (set(a_frag or a_full) | set(b_frag or b_full))),
        })
        results[citation] = record

    write_json(out / "comparisons.json", results)
    counts = {}
    for record in results.values():
        counts[record["verdict"]] = counts.get(record["verdict"], 0) + 1
    frag = sum(1 for r in results.values() if r.get("granularity") == "cited fragment")
    print(f"citations compared: {len(results)}")
    for verdict in sorted(counts):
        print(f"  {verdict:34} {counts[verdict]}")
    print(f"  compared at the CITED FRAGMENT     : {frag}")
    print(f"  compared at the whole article      : "
          f"{sum(1 for r in results.values() if r.get('granularity') == 'whole article')}")
    differs = [c for c, r in results.items() if r["verdict"] == "differs"]
    if differs:
        print(f"\n  differing ({len(differs)}), for reading:")
        for citation in sorted(differs)[:12]:
            record = results[citation]
            print(f"    {citation}  ({record['granularity']}, "
                  f"cited by {' '.join(record['cited_by'])})")
            for tag, old, new in record["diff_spans"][:2]:
                print(f"       {tag:8} 2020 {old!r}")
                print(f"       {'':8} 2025 {new!r}")
    print(f"written: {out / 'comparisons.json'}")


if __name__ == "__main__":
    main()
