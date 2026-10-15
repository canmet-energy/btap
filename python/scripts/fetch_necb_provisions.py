#!/usr/bin/env python3
"""Fetch a bounded NECB provision corpus and build its offline structural index.

This is a maintainer operation.  It uses ``btap._mcp.MCPClient("codes")`` and
requires ``HBIX_API_KEY`` in the environment.  Runtime and CI read only the
committed ``coverage/provisions.json`` files.

The first corpus is deliberately small but crosses every structural boundary
the decision-by-provision registry needs:

* same-number Division A and Division B Articles 1.1.1.1;
* a Division B article with sentence/clause structure, reused from the
  existing Section 8.4 cache rather than fetched or copied as text again;
* the reference-system Table 8.4.x.7.-B and its table notes;
* the explanatory Appendix note for Article 8.4.x.13; and
* Article 8.4.1.5, present in 2025 and authority-confirmed absent in 2020.

Exact authorized MCP results are archived as
``provenance/provisions.result.json`` in each edition.  The normalized index
contains no requirement text: only identities, hierarchy, titles, source
locators, and source hashes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import tomllib
from datetime import date
from pathlib import Path
from typing import Any

PYTHON_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PYTHON_ROOT))

from btap._mcp import MCPClient  # noqa: E402
from btap.codes.provisions import (  # noqa: E402
    parse_citation,
    structure_from_cache,
    structure_from_text,
    table_note_ids,
)

DATA_ROOT = PYTHON_ROOT / "btap" / "codes" / "necb" / "data"
DECISIONS_DIR = PYTHON_ROOT.parent / "docs" / "decisions"
INDEX_PATH = Path("coverage/provisions.json")
ARCHIVE_PATH = Path("provenance/provisions.result.json")
SECTION_CACHE_PATH = Path("coverage/articles_8_4.json")

EDITION_SPECS = {
    "2020": {
        "reference_article": "8.4.4.7",
        "structured_article": "8.4.4.13",
        "table": "8.4.4.7.-B",
        "appendix_note": "A-8.4.4.13",
        "inventory_probe": "8.4.1.5",
    },
    "2025": {
        "reference_article": "8.4.5.7",
        "structured_article": "8.4.5.13",
        "table": "8.4.5.7.-B",
        "appendix_note": "A-8.4.5.13",
        "inventory_probe": "8.4.1.5",
    },
}

def _json_bytes(value: Any, *, sort_keys: bool = True) -> bytes:
    return (
        json.dumps(value, indent=2, sort_keys=sort_keys, ensure_ascii=False) + "\n"
    ).encode("utf-8")


def _archive_bytes(value: Any) -> bytes:
    """Canonical retained-payload bytes used by every archived MCP source."""
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _source_artifacts(
    *,
    archive_sha256: str,
    section_cache_sha256: str,
) -> list[dict[str, str]]:
    return sorted(
        [
            {
                "path": ARCHIVE_PATH.as_posix(),
                "sha256": archive_sha256,
            },
            {
                "path": SECTION_CACHE_PATH.as_posix(),
                "sha256": section_cache_sha256,
            },
        ],
        key=lambda item: item["path"],
    )


def _source_set_sha256(artifacts: list[dict[str, str]]) -> str:
    return _sha256_bytes(_archive_bytes(artifacts))


def _section_arguments(edition: str, division: str, number: str) -> dict[str, Any]:
    return {
        "code": "necb",
        "edition": edition,
        "division": division,
        "section_number": number,
        "include_sentences": False,
    }


def _canonical_reference(value: str) -> str:
    """Normalize legacy spelling before inspecting the canonical source set."""
    if re.fullmatch(r"A-\d+(?:\.\d+){3,}\.\(\d+\)", value):
        return f"Note {value}"
    table_with_period = re.fullmatch(r"(Table\s+.+)\.", value)
    if table_with_period:
        return table_with_period.group(1)
    return parse_citation(value, family="necb").canonical


def concrete_references(
    edition: str,
    *,
    source_dir: Path = DECISIONS_DIR,
) -> tuple[str, ...]:
    """Return every concrete NECB citation in canonical source order."""
    references: list[str] = []
    code_id = f"necb{edition}"
    for path in sorted(
        source_dir.glob("D-*.md"),
        key=lambda item: int(item.stem.removeprefix("D-")),
    ):
        raw = path.read_text(encoding="utf-8")
        try:
            front = raw.split("+++\n", 2)[1]
        except IndexError:
            raise ValueError(f"{path} has no TOML front matter") from None
        meta = tomllib.loads(front)
        articles = meta.get("articles", {})
        if not isinstance(articles, dict):
            raise ValueError(f"{path} articles must be a table")
        for key, requirement in articles.items():
            if not isinstance(requirement, dict):
                if key in {"unverified", "not_applicable"} and isinstance(
                    requirement, list
                ):
                    continue
                raise ValueError(f"{path} articles.{key} must be a table")
            sources = requirement.get("sources")
            if isinstance(sources, list):
                for source in sources:
                    if not isinstance(source, dict):
                        raise ValueError(f"{path} articles.{key}.sources has a non-table")
                    if (
                        source.get("code") == "necb"
                        and source.get("edition") == edition
                    ):
                        values = source.get("references")
                        if not isinstance(values, list):
                            raise ValueError(
                                f"{path} articles.{key}.sources references must be a list"
                            )
                        references.extend(_canonical_reference(value) for value in values)
            elif code_id in requirement:
                values = requirement[code_id]
                if not isinstance(values, list):
                    raise ValueError(f"{path} articles.{key}.{code_id} must be a list")
                references.extend(_canonical_reference(value) for value in values)
    return tuple(dict.fromkeys(references))


def _section_call_id(division: str, number: str) -> str:
    return f"section_{division}_{number.replace('.', '_').replace('-', '_')}"


def _table_call_id(number: str) -> str:
    return f"table_{number.replace('.', '_').replace('-', '_')}"


def _article_citation(citation: Any) -> str | None:
    if citation.kind not in {"article", "sentence", "clause", "subclause"}:
        return None
    return citation.canonical.split(".(", 1)[0]


def _table_parent(number: str) -> str | None:
    match = re.fullmatch(r"(\d+(?:\.\d+){3,})(?:\.-[A-Z])?", number)
    return match.group(1) if match else None


def _appendix_parent(number: str) -> str:
    """Return the Article explained by an Appendix note or note sentence."""
    return number.removeprefix("A-").split(".(", 1)[0]


def _cache_article_is_usable(edition: str, number: str) -> bool:
    """Whether the committed cache can witness the article's full hierarchy."""
    cache_path = DATA_ROOT / f"necb{edition}" / SECTION_CACHE_PATH
    try:
        cache = json.loads(cache_path.read_text(encoding="utf-8"))
        article = cache["articles"][number]
        structure_from_cache(article)
    except (KeyError, TypeError, ValueError):
        return False
    return True


def call_specs(
    edition: str,
    spec: dict[str, str],
    *,
    references: tuple[str, ...] | None = None,
) -> dict[str, dict[str, Any]]:
    """The bounded, reproducible MCP request set for one edition.

    The committed decision sources declare the additional evidence required by
    concrete mappings.  Section 8.4 articles reuse their retained cache; every
    other governing Article, Table, and Appendix note has an exact MCP payload
    in the archive.
    """
    calls = {
        "division_a_1_1_1_1": {
            "tool": "get_section",
            "arguments": _section_arguments(edition, "A", "1.1.1.1"),
        },
        "division_b_1_1_1_1": {
            "tool": "get_section",
            "arguments": _section_arguments(edition, "B", "1.1.1.1"),
        },
        "reference_system_table": {
            "tool": "get_table",
            "arguments": {
                "code": "necb",
                "edition": edition,
                "division": "B",
                "table_number": spec["table"],
            },
        },
        "heat_pump_appendix_note": {
            "tool": "get_section",
            "arguments": _section_arguments(edition, "B", spec["appendix_note"]),
        },
        "subsection_8_4_1_inventory": {
            "tool": "query_sections",
            "arguments": {
                "code": "necb",
                "edition": edition,
                "hierarchy_level": "article",
                "section_pattern": "8.4.1.%",
                "limit": 100,
            },
        },
    }
    for reference in references if references is not None else concrete_references(edition):
        citation = parse_citation(reference, family="necb")
        article = _article_citation(citation)
        if article is not None:
            number = article.removeprefix("Division A ")
            if number.startswith("8.4."):
                if not _cache_article_is_usable(edition, number):
                    call_id = _section_call_id("B", number)
                    calls.setdefault(
                        call_id,
                        {
                            "tool": "get_section",
                            "arguments": _section_arguments(edition, "B", number),
                        },
                    )
                continue
            call_id = _section_call_id(citation.division, number)
            calls.setdefault(
                call_id,
                {
                    "tool": "get_section",
                    "arguments": _section_arguments(edition, citation.division, number),
                },
            )
            continue
        if citation.kind in {"table", "table-note"}:
            table_number = citation.canonical.removeprefix("Table ").split(" Note ", 1)[0]
            if table_number == spec["table"]:
                continue
            call_id = _table_call_id(table_number)
            calls.setdefault(
                call_id,
                {
                    "tool": "get_table",
                    "arguments": {
                        "code": "necb",
                        "edition": edition,
                        "division": "B",
                        "table_number": table_number,
                    },
                },
            )
            article = _table_parent(table_number)
            if article is not None and (
                not article.startswith("8.4.")
                or not _cache_article_is_usable(edition, article)
            ):
                article_call_id = _section_call_id("B", article)
                calls.setdefault(
                    article_call_id,
                    {
                        "tool": "get_section",
                        "arguments": _section_arguments(edition, "B", article),
                    },
                )
            continue
        if citation.kind == "appendix-note":
            number = citation.canonical.removeprefix("Note ")
            if number == spec["appendix_note"]:
                continue
            call_id = _section_call_id("B", number)
            calls.setdefault(
                call_id,
                {
                    "tool": "get_section",
                    "arguments": _section_arguments(edition, "B", number),
                },
            )
            article = _appendix_parent(number)
            if not article.startswith("8.4.") or not _cache_article_is_usable(
                edition, article
            ):
                article_call_id = _section_call_id("B", article)
                calls.setdefault(
                    article_call_id,
                    {
                        "tool": "get_section",
                        "arguments": _section_arguments(edition, "B", article),
                    },
                )
            continue
        raise ValueError(f"unsupported concrete citation {reference!r}")
    return calls


def fetch_calls(
    client: MCPClient,
    edition: str,
    spec: dict[str, str],
    *,
    references: tuple[str, ...] | None = None,
) -> dict[str, Any]:
    """Make the bounded live calls whose exact results are retained."""
    calls = call_specs(edition, spec, references=references)
    for call in calls.values():
        call["result"] = client.call(call["tool"], call["arguments"])
    return calls


def _archive_key(tool: str, arguments: dict[str, Any]) -> str:
    if tool == "get_section":
        return ":".join(
            (
                tool,
                arguments["code"],
                arguments["edition"],
                arguments["division"],
                arguments["section_number"],
            )
        )
    if tool == "get_table":
        return ":".join(
            (
                tool,
                arguments["code"],
                arguments["edition"],
                arguments["division"],
                arguments["table_number"],
            )
        )
    if tool == "query_sections":
        return ":".join(
            (
                tool,
                arguments["code"],
                arguments["edition"],
                arguments["hierarchy_level"],
                arguments["section_pattern"],
            )
        )
    raise ValueError(f"no canonical archive key for tool {tool!r}")


def _call_evidence(calls: dict[str, Any], call_id: str) -> dict[str, str]:
    call = calls[call_id]
    return _evidence("mcp", _archive_key(call["tool"], call["arguments"]))


def _expect_section(
    record: object,
    *,
    edition: str,
    division: str,
    number: str,
    hierarchy_level: str,
) -> dict[str, Any]:
    if not isinstance(record, dict):
        raise ValueError(f"{division} {number} returned {type(record).__name__}, not an object")
    expected = {
        "edition": edition,
        "division": division,
        "section_number": number,
        "article_number": number,
        "hierarchy_level": hierarchy_level,
    }
    differences = {
        key: (record.get(key), value)
        for key, value in expected.items()
        if record.get(key) != value
    }
    if differences:
        raise ValueError(f"section payload identity mismatch for {division} {number}: {differences}")
    return record


def _expect_table(
    record: object, *, edition: str, number: str
) -> dict[str, Any]:
    if not isinstance(record, dict):
        raise ValueError(f"Table {number} returned {type(record).__name__}, not an object")
    expected = {"edition": edition, "division": "B", "table_number": number}
    differences = {
        key: (record.get(key), value)
        for key, value in expected.items()
        if record.get(key) != value
    }
    if differences:
        raise ValueError(f"table payload identity mismatch for {number}: {differences}")
    rows = record.get("rows")
    row_count = record.get("row_count")
    if not isinstance(rows, list) or row_count != len(rows):
        raise ValueError(
            f"Table {number} archive must be complete: row_count={row_count!r}, "
            f"rows={len(rows) if isinstance(rows, list) else type(rows).__name__}"
        )
    if record.get("has_more"):
        raise ValueError(f"Table {number} payload is paginated; fetch all rows")
    return record


def _inventory_numbers(record: object, *, edition: str, limit: int) -> set[str]:
    if not isinstance(record, list) or not record:
        raise ValueError("8.4.1 article inventory must be a non-empty list")
    if len(record) >= limit:
        raise ValueError(
            f"8.4.1 article inventory reached its limit of {limit}; "
            "absence cannot be established"
        )
    numbers = set()
    for item in record:
        if not isinstance(item, dict):
            raise ValueError("8.4.1 article inventory contains a non-object")
        expected = {
            "edition": edition,
            "division": "B",
            "hierarchy_level": "article",
        }
        differences = {
            key: (item.get(key), value)
            for key, value in expected.items()
            if item.get(key) != value
        }
        if differences:
            raise ValueError(f"8.4.1 article inventory identity mismatch: {differences}")
        number = item.get("section_number")
        if not isinstance(number, str) or not re.fullmatch(r"8\.4\.1\.\d+", number):
            raise ValueError(f"8.4.1 inventory returned unexpected number {number!r}")
        if item.get("article_number") != number:
            raise ValueError(
                f"8.4.1 inventory article_number {item.get('article_number')!r} "
                f"does not match section_number {number!r}"
            )
        if number in numbers:
            raise ValueError(f"8.4.1 inventory repeats {number}")
        numbers.add(number)
    suffixes = sorted(int(number.rsplit(".", 1)[-1]) for number in numbers)
    expected = list(range(1, suffixes[-1] + 1))
    if suffixes != expected:
        raise ValueError(
            f"8.4.1 article inventory is not contiguous: found {suffixes}, "
            f"expected {expected}"
        )
    return numbers


def _evidence(source: str, record: str) -> dict[str, str]:
    return {"source": source, "record": record}


def _add(
    provisions: dict[str, dict[str, Any]],
    citation: str,
    *,
    status: str,
    title: str | None,
    children_complete: bool,
    evidence: list[dict[str, str]],
    parent: str | None = None,
) -> None:
    parsed = parse_citation(citation, family="necb")
    canonical = parsed.canonical
    if canonical in provisions:
        raise ValueError(f"duplicate normalized provision {canonical}")
    provisions[canonical] = {
        "citation": canonical,
        "division": parsed.division,
        "kind": parsed.kind,
        "parent": parsed.parent if parent is None else parent,
        "status": status,
        "title": title,
        "children_complete": children_complete,
        "evidence": evidence,
    }


def _add_article_tree(
    provisions: dict[str, dict[str, Any]],
    *,
    division: str,
    number: str,
    title: str,
    structure: dict[str, dict[str, Any]],
    evidence: list[dict[str, str]],
) -> None:
    article = f"Division A {number}" if division == "A" else number
    _add(
        provisions,
        article,
        status="present",
        title=title,
        children_complete=True,
        evidence=evidence,
    )
    for sentence, sentence_record in structure.items():
        sentence_citation = f"{article}.({sentence})"
        _add(
            provisions,
            sentence_citation,
            status="present",
            title=None,
            children_complete=True,
            evidence=evidence,
        )
        for clause, subclauses in sentence_record["clauses"].items():
            clause_citation = f"{sentence_citation}({clause})"
            _add(
                provisions,
                clause_citation,
                status="present",
                title=None,
                children_complete=True,
                evidence=evidence,
            )
            for subclause in subclauses:
                _add(
                    provisions,
                    f"{clause_citation}({subclause})",
                    status="present",
                    title=None,
                    children_complete=False,
                    evidence=evidence,
                )


def _build_index(
    calls: dict[str, Any],
    archive: dict[str, Any],
    edition: str,
    section_cache: dict[str, Any],
    *,
    retrieved: str,
    section_cache_sha256: str | None = None,
    references: tuple[str, ...] | None = None,
) -> dict[str, Any]:
    """Normalize one already-retained bounded source set."""
    spec = EDITION_SPECS[edition]
    references = references if references is not None else concrete_references(edition)
    citations = [parse_citation(reference, family="necb") for reference in references]
    archive_bytes = _archive_bytes(archive)

    provenance = section_cache.get("provenance") or {}
    if provenance.get("code") != "necb" or provenance.get("edition") != edition:
        raise ValueError(
            f"Section 8.4 cache identifies {(provenance.get('code'), provenance.get('edition'))!r}, "
            f"expected ('necb', {edition!r})"
        )
    articles = section_cache.get("articles")
    if not isinstance(articles, dict):
        raise ValueError("Section 8.4 cache has no articles object")

    provisions: dict[str, dict[str, Any]] = {}
    for division, call_id in (
        ("A", "division_a_1_1_1_1"),
        ("B", "division_b_1_1_1_1"),
    ):
        section = _expect_section(
            calls[call_id]["result"],
            edition=edition,
            division=division,
            number="1.1.1.1",
            hierarchy_level="article",
        )
        _add_article_tree(
            provisions,
            division=division,
            number="1.1.1.1",
            title=str(section.get("title") or ""),
            structure=structure_from_text(section),
            evidence=[_call_evidence(calls, call_id)],
        )

    cache_articles = {spec["reference_article"], spec["structured_article"]}
    external_articles: set[tuple[str, str]] = set()
    table_numbers = {spec["table"]}
    appendix_numbers = {spec["appendix_note"]}
    for citation in citations:
        article = _article_citation(citation)
        if article is not None:
            number = article.removeprefix("Division A ")
            if number.startswith("8.4."):
                try:
                    structure_from_cache(articles[number])
                except (KeyError, TypeError, ValueError):
                    external_articles.add(("B", number))
                else:
                    cache_articles.add(number)
            else:
                external_articles.add((citation.division, number))
            continue
        if citation.kind in {"table", "table-note"}:
            number = citation.canonical.removeprefix("Table ").split(" Note ", 1)[0]
            table_numbers.add(number)
            parent = _table_parent(number)
            if parent is not None:
                if parent.startswith("8.4."):
                    try:
                        structure_from_cache(articles[parent])
                    except (KeyError, TypeError, ValueError):
                        external_articles.add(("B", parent))
                    else:
                        cache_articles.add(parent)
                else:
                    external_articles.add(("B", parent))
            continue
        if citation.kind == "appendix-note":
            number = citation.canonical.removeprefix("Note ")
            appendix_numbers.add(number)
            article = _appendix_parent(number)
            if article.startswith("8.4."):
                try:
                    structure_from_cache(articles[article])
                except (KeyError, TypeError, ValueError):
                    external_articles.add(("B", article))
                else:
                    cache_articles.add(article)
            else:
                external_articles.add(("B", article))

    for number in sorted(cache_articles):
        article = articles.get(number)
        if not isinstance(article, dict):
            raise ValueError(
                f"Section 8.4 cache is missing cited article {number}; "
                "refresh its authorized cache before indexing the citation"
            )
        _add_article_tree(
            provisions,
            division="B",
            number=number,
            title=str(article.get("title") or ""),
            structure=structure_from_cache(article),
            evidence=[_evidence("section-8.4", f"articles.{number}")],
        )

    for division, number in sorted(external_articles):
        call_id = _section_call_id(division, number)
        section = _expect_section(
            calls[call_id]["result"],
            edition=edition,
            division=division,
            number=number,
            hierarchy_level="article",
        )
        _add_article_tree(
            provisions,
            division=division,
            number=number,
            title=str(section.get("title") or ""),
            structure=structure_from_text(section),
            evidence=[_call_evidence(calls, call_id)],
        )

    for number in sorted(table_numbers):
        call_id = "reference_system_table" if number == spec["table"] else _table_call_id(number)
        table = _expect_table(
            calls[call_id]["result"],
            edition=edition,
            number=number,
        )
        parent = _table_parent(number)
        table_evidence = [_call_evidence(calls, call_id)]
        if number == spec["table"] and parent in cache_articles:
            table_evidence.append(_evidence("section-8.4", f"articles.{parent}"))
        _add(
            provisions,
            f"Table {number}",
            status="present",
            title=str(table.get("title") or ""),
            children_complete=number == spec["table"],
            evidence=table_evidence,
            parent=parent,
        )
        if number == spec["table"]:
            for note in table_note_ids(articles[spec["reference_article"]], number):
                _add(
                    provisions,
                    f"Table {number} Note ({note})",
                    status="present",
                    title=None,
                    children_complete=False,
                    evidence=table_evidence,
                )

    for number in sorted(appendix_numbers):
        call_id = (
            "heat_pump_appendix_note"
            if number == spec["appendix_note"]
            else _section_call_id("B", number)
        )
        appendix = _expect_section(
            calls[call_id]["result"],
            edition=edition,
            division="B",
            number=number,
            hierarchy_level="note",
        )
        if appendix.get("normative") is not False:
            raise ValueError(f"{number} is not identified as an explanatory note")
        explained = number.removeprefix("A-")
        if appendix.get("explains") != explained:
            raise ValueError(
                f"{number} explains {appendix.get('explains')!r}, "
                f"expected {explained!r}"
            )
        _add(
            provisions,
            f"Note {number}",
            status="present",
            title=str(appendix.get("title") or ""),
            children_complete=False,
            evidence=[_call_evidence(calls, call_id)],
            parent=explained,
        )

    inventory_call = calls["subsection_8_4_1_inventory"]
    inventory = _inventory_numbers(
        inventory_call["result"],
        edition=edition,
        limit=inventory_call["arguments"]["limit"],
    )
    probe = spec["inventory_probe"]
    if probe in inventory:
        article = articles.get(probe)
        if not isinstance(article, dict):
            raise ValueError(
                f"authority lists {probe}, but the existing Section 8.4 cache omits it"
            )
        _add_article_tree(
            provisions,
            division="B",
            number=probe,
            title=str(article.get("title") or ""),
            structure=structure_from_cache(article),
            evidence=[
                _call_evidence(calls, "subsection_8_4_1_inventory"),
                _evidence("section-8.4", f"articles.{probe}"),
            ],
        )
    else:
        _add(
            provisions,
            probe,
            status="absent",
            title=None,
            children_complete=False,
            evidence=[_call_evidence(calls, "subsection_8_4_1_inventory")],
        )

    for reference in references:
        if reference not in provisions:
            raise ValueError(
                f"provision index did not retain cited NECB reference {reference!r}"
            )

    cache_retrieved = provenance.get("retrieved")
    if not isinstance(cache_retrieved, str) or not re.fullmatch(
        r"\d{4}-\d{2}-\d{2}", cache_retrieved
    ):
        raise ValueError("Section 8.4 cache provenance has no YYYY-MM-DD retrieved date")
    index = {
        "schema": 1,
        "code": {"family": "necb", "id": f"necb{edition}", "edition": edition},
        "generated": retrieved,
        "sources": {
            "mcp": {
                "kind": "authorized-mcp-payload",
                "path": ARCHIVE_PATH.as_posix(),
                "retrieved": retrieved,
                "sha256": _sha256_bytes(archive_bytes),
            },
            "section-8.4": {
                "kind": "existing-authorized-cache",
                "path": SECTION_CACHE_PATH.as_posix(),
                "retrieved": cache_retrieved,
                "sha256": section_cache_sha256 or _sha256_bytes(_json_bytes(section_cache)),
            },
        },
        "provisions": provisions,
    }
    return index


def build_documents(
    client: MCPClient,
    edition: str,
    section_cache: dict[str, Any],
    *,
    retrieved: str,
    section_cache_sha256: str | None = None,
    references: tuple[str, ...] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Fetch and normalize one edition without writing it."""
    calls = fetch_calls(
        client,
        edition,
        EDITION_SPECS[edition],
        references=references,
    )
    archive = {
        _archive_key(call["tool"], call["arguments"]): call["result"]
        for call in calls.values()
    }
    return archive, _build_index(
        calls,
        archive,
        edition,
        section_cache,
        retrieved=retrieved,
        section_cache_sha256=section_cache_sha256,
        references=references,
    )


def build_index_from_archive(
    archive: dict[str, Any],
    edition: str,
    section_cache: dict[str, Any],
    *,
    retrieved: str,
    section_cache_sha256: str | None = None,
    references: tuple[str, ...] | None = None,
) -> dict[str, Any]:
    """Replay a committed MCP archive into its normalized provision index."""
    specs = call_specs(edition, EDITION_SPECS[edition], references=references)
    expected = {
        _archive_key(call["tool"], call["arguments"]): call_id
        for call_id, call in specs.items()
    }
    actual_keys = set(archive) if isinstance(archive, dict) else set()
    if actual_keys != set(expected):
        raise ValueError(
            "provision archive has the wrong call set; "
            f"missing={sorted(set(expected) - actual_keys)}, "
            f"extra={sorted(actual_keys - set(expected))}"
        )
    calls: dict[str, dict[str, Any]] = {}
    for locator, call_id in expected.items():
        call = specs[call_id]
        calls[call_id] = {
            "tool": call["tool"],
            "arguments": call["arguments"],
            "result": archive[locator],
        }
    return _build_index(
        calls,
        archive,
        edition,
        section_cache,
        retrieved=retrieved,
        section_cache_sha256=section_cache_sha256,
        references=references,
    )


def _manifest_with_provision(
    manifest: dict[str, Any],
    *,
    edition: str,
    archive: dict[str, Any],
    section_cache_sha256: str,
    index_bytes: bytes,
    retrieved: str,
) -> dict[str, Any]:
    if manifest.get("id") != f"necb{edition}" or manifest.get("edition") != edition:
        raise ValueError(f"manifest identity does not match NECB {edition}")

    if "provision_index" not in manifest:
        reordered: dict[str, Any] = {}
        for key, value in manifest.items():
            if key == "provenance":
                reordered["provision_index"] = INDEX_PATH.as_posix()
            reordered[key] = value
        manifest = reordered
    else:
        manifest["provision_index"] = INDEX_PATH.as_posix()

    provenance = manifest.setdefault("provenance", {})
    requests = [
        {"tool": call["tool"], **call["arguments"]}
        for call in call_specs(edition, EDITION_SPECS[edition]).values()
    ]
    archive_bytes = _archive_bytes(archive)
    source_artifacts = _source_artifacts(
        archive_sha256=_sha256_bytes(archive_bytes),
        section_cache_sha256=section_cache_sha256,
    )
    provenance[INDEX_PATH.as_posix()] = {
        "source": f"mcp:necb:{edition}",
        "request": requests,
        "source_revision": None,
        "source_sha256": _source_set_sha256(source_artifacts),
        "source_artifacts": source_artifacts,
        "extractor": "python/scripts/fetch_necb_provisions.py",
        "retrieved": retrieved,
        "method": "generated",
        "source_verification": "archived",
        "note": (
            "The retained provisions.result.json is the exact bounded set of "
            "authorized MCP tool results. source_artifacts is the canonical "
            "two-input descriptor and also pins coverage/articles_8_4.json, "
            "which supplies Section 8.4 structure and table-note identities "
            "without duplicating that cache."
        ),
        "result_sha256": _sha256_bytes(index_bytes),
    }
    return manifest


def write_edition(
    client: MCPClient,
    edition: str,
    *,
    data_root: Path = DATA_ROOT,
    retrieved: str | None = None,
) -> tuple[Path, Path]:
    """Fetch, validate, write, and provenance-bind one edition."""
    retrieved = retrieved or date.today().isoformat()
    snapshot = data_root / f"necb{edition}"
    cache_path = snapshot / SECTION_CACHE_PATH
    manifest_path = snapshot / "manifest.json"
    section_cache = json.loads(cache_path.read_text(encoding="utf-8"))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    section_cache_sha256 = _sha256_file(cache_path)

    archive, index = build_documents(
        client,
        edition,
        section_cache,
        retrieved=retrieved,
        section_cache_sha256=section_cache_sha256,
    )
    archive_bytes = _archive_bytes(archive)
    index_bytes = _json_bytes(index)
    manifest = _manifest_with_provision(
        manifest,
        edition=edition,
        archive=archive,
        section_cache_sha256=section_cache_sha256,
        index_bytes=index_bytes,
        retrieved=retrieved,
    )

    archive_path = snapshot / ARCHIVE_PATH
    index_path = snapshot / INDEX_PATH
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    index_path.parent.mkdir(parents=True, exist_ok=True)
    archive_path.write_bytes(archive_bytes)
    index_path.write_bytes(index_bytes)
    manifest_path.write_bytes(_json_bytes(manifest, sort_keys=False))
    return archive_path, index_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Fetch the bounded NECB normative provision corpus"
    )
    parser.add_argument(
        "--edition",
        choices=["2020", "2025", "all"],
        default="all",
        help="edition to refresh (default: both)",
    )
    parser.add_argument(
        "--data-root",
        type=Path,
        default=DATA_ROOT,
        help="NECB snapshot root (default: packaged source-tree data)",
    )
    args = parser.parse_args(argv)

    editions = tuple(EDITION_SPECS) if args.edition == "all" else (args.edition,)
    client = MCPClient("codes")
    for edition in editions:
        archive, index = write_edition(
            client, edition, data_root=args.data_root
        )
        relative_archive = (
            archive.relative_to(PYTHON_ROOT)
            if archive.is_relative_to(PYTHON_ROOT)
            else archive
        )
        relative_index = (
            index.relative_to(PYTHON_ROOT)
            if index.is_relative_to(PYTHON_ROOT)
            else index
        )
        print(f"NECB {edition}: wrote {relative_archive} and {relative_index}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
