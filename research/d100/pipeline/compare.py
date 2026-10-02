#!/usr/bin/env python3
"""Stage 5 — compare each cited provision across editions, BY KIND.

An article is compared as text, a table as its structured headers and rows, and
a Table Note as the note text inside the PARENT article. An earlier version
read `full_text` from a `get_section` for everything, which produced three wrong
answers at once (Sol, `065` item 2):

* D-03's two table citations reported `mcp_empty` on both sides although their
  `get_table` payloads positively establish them;
* `Table 3.2.2.2.` reported `differs` on one extra rendered caption span in the
  enclosing article, never comparing the rows that are the cited requirement;
* `Table 3.2.3.1.`'s "identical" verdict was about enclosing article text, so it
  was accidental evidence.

Normalisation is exactly two things, and no more:

1. **Both subsection renumberings**, in ONE edition-keyed pass. The reference
   subsection moved 8.4.4 -> 8.4.5 and the prescriptive subsection moved
   8.4.5 -> 8.4.6, so a sequential rewrite can move one reference twice. A token
   matching neither role for that edition is left alone, which matters because
   NECB 2025's Subsection 8.4.4 is live and holds the archetype-EUI path.
2. **Observed subscript glyphs**, from an explicit allowlist — not global NFKD,
   which folds superscripts and would erase the exponent in `(5/75)^n`.

Whitespace is also collapsed. That is stated here rather than described as
"nothing else", which was inaccurate (Sol, `065`).

Differences are reported as spans, never scored: a `similarity 1.000` once hid
four real changes behind a rounded float.
"""

from __future__ import annotations

import difflib
import re

from common import PRESENT, out_dir, read_json, request_key, write_json

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
SENTENCE_RE = re.compile(r"(?m)^(\d+)\)\s")
#: `(2)`, `(2)(a)`, and an INCLUSIVE range `(4)-(5)`. Reading only the first
#: number returned Sentence (4) alone for D-62's `5.2.2.8.(4)-(5)` and still
#: labelled the result a cited-fragment comparison (Sol, `065` item 3).
FRAGMENT_RE = re.compile(r"^\((\d+)\)(?:-\((\d+)\))?")


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


def wanted_sentences(fragment: str):
    """The sentence numbers a fragment cites, inclusive, or [] for none."""
    match = FRAGMENT_RE.match(fragment or "")
    if not match:
        return []
    first = int(match.group(1))
    last = int(match.group(2)) if match.group(2) else first
    if last < first:
        return []
    return list(range(first, last + 1))


def sentences_of(full_text: str, numbers):
    """``(text, complete)`` for the cited sentences, in order.

    ``complete`` is False when any requested sentence is missing, so a partial
    range can never be presented as the cited fragment.
    """
    if not numbers or not full_text:
        return None, False
    marks = [(int(m.group(1)), m.start()) for m in SENTENCE_RE.finditer(full_text)]
    index = {number: position for number, position in marks}
    out = []
    for number in numbers:
        if number not in index:
            return None, False
        start = index[number]
        later = [p for n, p in marks if p > start]
        out.append(full_text[start:(min(later) if later else len(full_text))])
    return "".join(out), True


def spans_between(left: str, right: str):
    return [(tag, left[i1:i2][:90], right[j1:j2][:90])
            for tag, i1, i2, j1, j2 in
            difflib.SequenceMatcher(None, left, right, autojunk=False).get_opcodes()
            if tag != "equal"]


def archived(out, request):
    path = out / "hbix" / f"{request_key(request)}.json"
    return read_json(path) if path.exists() else None


def table_text(payload) -> str:
    """A table's STRUCTURE as comparable text: headers then rows, in order.

    This is the cited requirement for a table citation. Comparing the enclosing
    article's prose instead made one verdict accidental and another wrong.
    """
    headers = payload.get("headers") or []
    rows = payload.get("rows") or []
    lines = ["headers: " + " | ".join(str(h) for h in headers)]
    for row in rows:
        if isinstance(row, dict):
            lines.append(" | ".join(f"{k}={row[k]}" for k in headers if k in row)
                         or " | ".join(f"{k}={v}" for k, v in sorted(row.items())))
        else:
            lines.append(" | ".join(str(cell) for cell in row))
    return "\n".join(lines)


def note_text(payload, fragment: str):
    """The requested Note's text from the PARENT article's section payload."""
    match = re.match(r"Note\s*\((\d+)\)", fragment or "")
    if not match or not payload:
        return None
    wanted = match.group(1)
    body = payload.get("full_text") or ""
    found = re.search(r"(?m)^\(" + wanted + r"\)\s*(.+?)(?=^\(\d+\)|\Z)",
                      body, re.DOTALL)
    return found.group(0) if found else None


def sides_for(out, entry):
    """``{year: {tool: archived}}`` for one citation."""
    sides = {}
    for edition, requests in entry["requests"].items():
        year = edition.replace("necb", "")
        sides[year] = {request["tool"]: archived(out, request)
                       for request in requests}
    return sides


def compare_one(entry, sides):
    """One citation's verdict, dispatched by kind."""
    kind, fragment = entry["kind"], entry["fragment"]
    tool = "get_table" if kind.startswith("table") else "get_section"
    record = {"kind": kind, "fragment": fragment, "cited_by": entry["cited_by"],
              "compared_with": tool}
    for year in ("2020", "2025"):
        payload = (sides.get(year) or {}).get(tool)
        record[f"state_{year}"] = (payload or {}).get("meta", {}).get("state")

    if record["state_2020"] != PRESENT or record["state_2025"] != PRESENT:
        record["verdict"] = "one-sided at this address"
        record["note"] = (
            "states {} / {} — an empty answer is not proven Code absence, and "
            "a same-address comparison is not available. The paired provision "
            "must be established positively.".format(
                record["state_2020"], record["state_2025"]))
        return record

    left = sides["2020"][tool]["payload"]
    right = sides["2025"][tool]["payload"]

    if kind.startswith("table"):
        if fragment.startswith("Note"):
            left_note = note_text((sides["2020"].get("get_section") or {}).get("payload"),
                                  fragment)
            right_note = note_text((sides["2025"].get("get_section") or {}).get("payload"),
                                   fragment)
            if left_note is None or right_note is None:
                record["verdict"] = "note not isolated in the parent article"
                record["granularity"] = "unresolved"
                return record
            a, b = normalise(left_note, "2020"), normalise(right_note, "2025")
            record["granularity"] = "table note, from the parent article"
        else:
            a = normalise(table_text(left), "2020")
            b = normalise(table_text(right), "2025")
            record["granularity"] = "structured headers and rows"
            record["row_counts"] = [len(left.get("rows") or []),
                                    len(right.get("rows") or [])]
    else:
        numbers = wanted_sentences(fragment)
        left_text, left_ok = sentences_of(left.get("full_text", ""), numbers)
        right_text, right_ok = sentences_of(right.get("full_text", ""), numbers)
        if numbers and left_ok and right_ok:
            a, b = normalise(left_text, "2020"), normalise(right_text, "2025")
            record["granularity"] = ("cited sentence" if len(numbers) == 1
                                     else f"cited sentences {numbers[0]}-{numbers[-1]}")
            record["sentences"] = numbers
        else:
            a = normalise(left.get("full_text", ""), "2020")
            b = normalise(right.get("full_text", ""), "2025")
            record["granularity"] = "whole article"
            if numbers:
                record["fragment_not_isolated"] = numbers

    spans = spans_between(a, b)
    record["verdict"] = "substantively identical" if not spans else "differs"
    record["diff_spans"] = spans
    record["superscripts_present"] = sorted(SUPERSCRIPTS & (set(a) | set(b)))
    return record


def candidate_pairings(citations, results):
    """One-sided citations of one decision that are present in complementary
    editions — a CANDIDATE renumbered pair, never an asserted one.

    D-03 cites `8.4.5.5.-C` and `8.4.6.5.-C`; the first is present in 2020 only
    and the second in 2025 only. That is positive per-edition evidence, which is
    what Sol asked for in place of a mapping rule — but which of them pairs with
    which is a record fact, so it is reported for confirmation, not resolved.
    """
    by_decision = {}
    for citation, record in results.items():
        if record["verdict"] != "one-sided at this address":
            continue
        only = ("2020" if record["state_2020"] == PRESENT else
                "2025" if record["state_2025"] == PRESENT else None)
        if not only:
            continue
        for decision in record["cited_by"]:
            by_decision.setdefault(decision, []).append((citation, only))
    out = {}
    for decision, items in sorted(by_decision.items()):
        in_2020 = [c for c, y in items if y == "2020"]
        in_2025 = [c for c, y in items if y == "2025"]
        if in_2020 and in_2025:
            out[decision] = {"present_in_2020_only": sorted(in_2020),
                             "present_in_2025_only": sorted(in_2025),
                             "status": "CANDIDATE pair — confirm against the "
                                       "decision's own body; not asserted here"}
    return out


def main(argv=None):
    out = out_dir(argv, __doc__)
    citations = read_json(out / "citations.json")["citations"]
    results = {citation: compare_one(entry, sides_for(out, entry))
               for citation, entry in citations.items()}
    pairings = candidate_pairings(citations, results)
    write_json(out / "comparisons.json",
               {"comparisons": results, "candidate_pairings": pairings})

    counts, grains = {}, {}
    for record in results.values():
        counts[record["verdict"]] = counts.get(record["verdict"], 0) + 1
        grain = record.get("granularity", "-")
        grains[grain] = grains.get(grain, 0) + 1
    print(f"citations compared: {len(results)}")
    for verdict in sorted(counts):
        print(f"  {verdict:34} {counts[verdict]}")
    print("  by granularity:")
    for grain in sorted(grains):
        print(f"    {grain:40} {grains[grain]}")
    if pairings:
        print(f"\n  candidate renumbered pairs ({len(pairings)}), for confirmation:")
        for decision, pair in pairings.items():
            print(f"    {decision}: {pair['present_in_2020_only']} (2020) <-> "
                  f"{pair['present_in_2025_only']} (2025)")
    differs = sorted(c for c, r in results.items() if r["verdict"] == "differs")
    if differs:
        print(f"\n  differing ({len(differs)}), for reading:")
        for citation in differs[:10]:
            record = results[citation]
            print(f"    {citation}  ({record['granularity']}, "
                  f"cited by {' '.join(record['cited_by'])})")
            for tag, left, right in record["diff_spans"][:2]:
                print(f"       {tag:8} 2020 {left!r}")
                print(f"       {'':8} 2025 {right!r}")
    print(f"written: {out / 'comparisons.json'}")


if __name__ == "__main__":
    main()
