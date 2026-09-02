#!/usr/bin/env python3
"""Fetch NECB Section 8.4 articles from the building-codes MCP.

Fetches every NECB Section 8.4 article for ONE edition (EDITION=2025 default,
EDITION=2020 supported), parses each into a sentence/clause tree with STRICT
sanity checks, and caches the result to
``btap/necb/data/coverage/necb_8_4_articles_2025.json``
for the coverage-document generator (which must run in CI without MCP access).

  python3 scripts/fetch_necb_8_4_text.py
  EDITION=2020 python3 scripts/fetch_necb_8_4_text.py

Auth: X-API-Key from ``HBIX_API_KEY``, else read at runtime from ``.mcp.json``
(which is never committed with a live key). The key is never printed and
never written into the cache.

Parsing is deliberately conservative: an article whose text fails ANY sanity
check is cached with ``parse_ok: false`` and its raw text — the generator then
renders "structure unverified" with the raw text in a <details>, never a
guessed tree. Requirement text under the wrong article number is the worst
outcome available in a compliance document; a patchy tree is not.

Python port (PR-A2): maintains exact Ruby parity on parse logic, cache schema,
and output content. The JSON is deterministic (sorted keys, pretty-print) so
a frozen Ruby cache and a regenerated Python cache diff cleanly on CONTENT
changes only, not on key order or whitespace.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import date
from pathlib import Path

# Importable without installing the package
PYTHON_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PYTHON_ROOT))

from btap._mcp import MCPClient, MCPError  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]

# The two editions do not share Section 8.4's structure: 2020's 8.4.4 is the
# reference building (20 articles) and 8.4.5 the part-load curves; 2025 inserts
# the EUI path as 8.4.4 and shifts everything down. One article list per
# edition, not a renumbering of one list.
ARTICLES_2020 = (
    [f"8.4.1.{i}" for i in range(1, 5)] +
    [f"8.4.2.{i}" for i in range(1, 11)] +
    [f"8.4.3.{i}" for i in range(1, 10)] +
    [f"8.4.4.{i}" for i in range(1, 21)] +
    [f"8.4.5.{i}" for i in range(1, 10)]
)

ARTICLES_2025 = (
    [f"8.4.1.{i}" for i in range(1, 6)] +
    [f"8.4.2.{i}" for i in range(1, 13)] +
    [f"8.4.3.{i}" for i in range(1, 10)] +
    [f"8.4.4.{i}" for i in range(1, 3)] +
    [f"8.4.5.{i}" for i in range(1, 21)] +
    [f"8.4.6.{i}" for i in range(1, 10)]
)

# Document furniture to strip
FURNITURE_PATTERNS = [
    re.compile(r"^National Energy Code of Canada for Buildings \d{4}$"),
    re.compile(r"^Division B(\s+8-\d+)?$"),
    re.compile(r"^8-\d+\s+Division B$"),
    re.compile(r"^©\s*His Majesty.*$"),
    re.compile(r"^\d{1,3}$"),  # bare page number
]

ARTICLE_TOKEN = re.compile(r"^8\.4\.\d+\.(\d+\.)?$")
SENTENCE = re.compile(r"^(\d+)\)\s+(.*)$")
CLAUSE = re.compile(r"^([a-z])\)\s+(.*)$")
ROMAN = re.compile(r"^(i{1,3}|iv|vi{0,3}|ix)\)\s+(.*)$")


def get_section(client: MCPClient, number: str, edition: str) -> dict:
    """Fetch one Section 8.4 article from the MCP."""
    return client.call(
        "get_section",
        {
            "code": "necb",
            "edition": edition,
            "division": "B",
            "section_number": number,
            "include_sentences": False
        }
    )


def embedded_article_start(lines: list[str], own: str) -> str | None:
    """Check if a DIFFERENT article demonstrably starts inside this body.

    An article token followed within 3 lines by a sentence "1)" indicates a
    new article. A bare token with no follow-up is a page running header and
    is stripped, not rejected — 8.4.6.4's correct body legitimately contains
    "8.4.6.5." as a running header.
    """
    for i, line in enumerate(lines):
        stripped = line.strip()
        if not ARTICLE_TOKEN.match(stripped):
            continue
        if stripped.rstrip(".") == own:
            continue

        # Look ahead up to 3 lines for "1)"
        for j in range(i + 1, min(i + 4, len(lines))):
            if re.match(r"^1\)\s", lines[j].strip()):
                return stripped

    return None


def next_letter(letter: str) -> str:
    """Next clause letter (a->b, z->aa)."""
    if letter == "z":
        return "aa"
    if len(letter) > 1:
        return letter  # don't handle multi-letter
    return chr(ord(letter) + 1)


def parse_article(number: str, record: dict) -> dict:
    """Parse article text into sentence/clause tree with strict sanity checks.

    Returns:
        {"parse_ok": True, "sentences": [...], "preamble_notes": [...], "preamble_dropped": [...]}
        or
        {"parse_ok": False, "reason": "<why>"}
    """
    raw = record.get("full_text", "")
    lines = [line.rstrip() for line in raw.split("\n")]

    # Check for embedded article start
    foreign = embedded_article_start(lines, number)
    if foreign:
        return {"parse_ok": False, "reason": f"embedded start of article {foreign}"}

    # Strip furniture and article tokens
    filtered = []
    for line in lines:
        s = line.strip()
        if not s:
            continue
        if any(pat.match(s) for pat in FURNITURE_PATTERNS):
            continue
        if ARTICLE_TOKEN.match(s):
            continue
        filtered.append(line)

    sentences = []
    preamble_notes = []
    preamble_dropped = []
    current = None  # innermost text sink
    expected_letter = None

    for line in filtered:
        s = line.strip()

        # Sentence
        m = SENTENCE.match(s)
        if m:
            sentences.append({
                "num": int(m.group(1)),
                "text": m.group(2),
                "clauses": []
            })
            current = sentences[-1]
            expected_letter = "a"
            continue

        # Clause (but "i)" is a clause letter only when alphabetically expected)
        if sentences:
            m = CLAUSE.match(s)
            if m:
                letter = m.group(1)
                # "i", "v", "x" are both clause letters and roman numerals
                is_roman_context = letter in ("i", "v", "x") and letter != expected_letter
                if not is_roman_context:
                    clause = {
                        "id": letter,
                        "text": m.group(2),
                        "subclauses": []
                    }
                    sentences[-1]["clauses"].append(clause)
                    current = clause
                    expected_letter = next_letter(letter)
                    continue

        # Roman numeral subclause
        if sentences and sentences[-1]["clauses"]:
            m = ROMAN.match(s)
            if m:
                sub = {"id": m.group(1), "text": m.group(2)}
                sentences[-1]["clauses"][-1]["subclauses"].append(sub)
                current = sub
                continue

        # Preamble (before sentence 1)
        if not sentences:
            if s.startswith("(See "):
                preamble_notes.append(s)
            else:
                preamble_dropped.append(s)
            continue

        # Continuation of current text sink
        if current:
            current["text"] = f"{current['text']} {s}".strip()

    # Trim trailing subsection heading bleed
    if current and "text" in current:
        m = re.match(r"^(.*[.)])\s+([A-Z][A-Za-z ,\/-]{2,40})$", current["text"])
        if m:
            current["text"] = m.group(1)

    # Sanity checks
    if not sentences:
        return {"parse_ok": False, "reason": "no sentences found"}

    nums = [s["num"] for s in sentences]
    if nums[0] != 1:
        return {"parse_ok": False, "reason": f"first sentence is {nums[0]}), not 1)"}

    if nums != list(range(1, len(nums) + 1)):
        return {"parse_ok": False, "reason": f"sentence numbering not contiguous: {','.join(map(str, nums))}"}

    return {
        "parse_ok": True,
        "sentences": sentences,
        "preamble_notes": preamble_notes,
        "preamble_dropped": preamble_dropped
    }


def main():
    parser = argparse.ArgumentParser(
        description="Fetch NECB Section 8.4 articles and cache with parse verification"
    )
    parser.add_argument(
        "--edition",
        default=os.getenv("EDITION", "2025"),
        choices=["2020", "2025"],
        help="NECB edition (default: 2025, or EDITION env var)"
    )
    parser.add_argument(
        "--out",
        type=Path,
        help=("Output path (default: python/btap/necb/data/coverage/"
              "necb_8_4_articles_<edition>.json)")
    )
    args = parser.parse_args()

    edition = args.edition
    articles = ARTICLES_2020 if edition == "2020" else ARTICLES_2025

    if args.out:
        out_path = args.out
    else:
        out_path = (PYTHON_ROOT / "btap" / "necb" / "data" / "coverage" /
                    f"necb_8_4_articles_{edition}.json")

    client = MCPClient("codes")

    cache = {
        "provenance": {
            "code": "necb",
            "edition": edition,
            "division": "B",
            "retrieved": date.today().isoformat(),
            "source": (
                "building-codes MCP (get_section, JSON-RPC), "
                "Crown copyright — reproduction authorized (GoC work)"
            ),
            "note": (
                f"Regenerate with: python3 scripts/fetch_necb_8_4_text.py --edition {edition}. "
                "The 2020->2025 renumbering (8.4.4->8.4.5) makes stale text actively misleading; "
                "check `retrieved` before trusting."
            )
        },
        "articles": {}
    }

    ok_count = 0

    for number in articles:
        try:
            record = get_section(client, number, edition)
            parsed = parse_article(number, record)

            if parsed["parse_ok"]:
                ok_count += 1
                status = "ok        "
            else:
                status = f"UNVERIFIED ({parsed['reason']})"

            cache["articles"][number] = {
                "title": record.get("title", ""),
                "pages": [record.get("page_start"), record.get("page_end")],
                "equations": [
                    eq.get("text") or eq.get("raw_text")
                    for eq in record.get("equations", [])
                ],
                "raw": record.get("full_text", "")
            }
            cache["articles"][number].update(parsed)

            title = record.get("title", "")[:50]
            print(f"{number:<10} {status} {title}")

        except MCPError as e:
            cache["articles"][number] = {
                "parse_ok": False,
                "reason": f"fetch failed: {e}",
                "raw": ""
            }
            print(f"{number:<10} FETCH FAILED {e}")

    # Write with sorted keys and pretty-print for deterministic diffs
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(cache, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8"
    )

    rel_path = out_path.relative_to(REPO_ROOT) if out_path.is_relative_to(REPO_ROOT) else out_path
    print(f"\n{ok_count}/{len(articles)} parsed clean -> {rel_path}")


if __name__ == "__main__":
    main()
