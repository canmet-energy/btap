"""Offline validation of code-provision citations.

Each ruleset may declare a ``provision_index`` in its edition manifest.  The
index is structural evidence only: canonical provision identities, hierarchy,
and source hashes.  Authorized raw payloads stay in the edition snapshot's
``provenance/`` directory, and validation never calls a network service.

The schema is code-family-neutral.  Citation syntax is family-owned; NECB is
the only parser registered today, so another family is never implied to be
supported merely because it has a manifest.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

SCHEMA_VERSION = 1
STATUSES = frozenset({"present", "absent", "not-indexed", "stale", "unsupported"})
KINDS = frozenset(
    {
        "article",
        "sentence",
        "clause",
        "subclause",
        "table",
        "table-note",
        "appendix-note",
    }
)

_ARTICLE_RE = re.compile(
    r"^(?:(?P<division>Division\s+[AB])\s+)?"
    r"(?:(?P<label>Article|Sentence|Clause|Subclause)\s+)?"
    r"(?P<number>\d+(?:\.\d+){3,})\.?"
    r"(?P<suffix>(?:\([^)]+\))*)$",
    re.IGNORECASE,
)
_TABLE_ID = (
    r"(?:"
    r"\d+(?:\.\d+){3,}(?:\.\(\d+\))?(?:\([a-z]+\))?(?:\.-[A-Z])?"
    r"|A-\d+(?:\.\d+){3,}(?:\.\(\d+\))?(?:\([a-z]+\))?-[A-Z]"
    r"|[A-Z]-\d+"
    r"|\d+-\d+"
    r")"
)
_TABLE_RE = re.compile(
    rf"^Table\s+(?P<table>{_TABLE_ID})"
    r"(?:\s+Note\s+\((?P<note>\d+)\))?$",
    re.IGNORECASE,
)
_APPENDIX_RE = re.compile(
    r"^(?:Appendix\s+)?Note\s+"
    r"(?P<note>A-\d+(?:\.\d+){3,}(?:\.\(\d+\))?(?:\([a-z]+\))?)\.?$",
    re.IGNORECASE,
)
_TOKEN_RE = re.compile(r"\(([^)]+)\)")
_SHA256_RE = re.compile(r"[0-9a-f]{64}")
_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
_ROMAN_RE = re.compile(r"(?:i{1,3}|iv|v|vi{0,3}|ix|x)")
_SENTENCE_LINE_RE = re.compile(r"^(\d+)\)\s+")
_CLAUSE_LINE_RE = re.compile(r"^([a-z])\)\s+")
_ROMAN_LINE_RE = re.compile(r"^(i{1,3}|iv|v|vi{0,3}|ix|x)\)\s+")
_ROMAN_SEQUENCE = ("i", "ii", "iii", "iv", "v", "vi", "vii", "viii", "ix", "x")
_NOTE_HEADING = r"^Notes to Table {table}:\s*$"
_TABLE_NOTE_LINE_RE = re.compile(r"^\((\d+)\)\s+")
_QUERY_RESULT_LIMIT = 100

_DOCUMENT_KEYS = {"schema", "code", "generated", "sources", "provisions"}
_CODE_KEYS = {"family", "id", "edition"}
_SOURCE_KEYS = {"kind", "path", "retrieved", "sha256"}
_PROVISION_KEYS = {
    "citation",
    "division",
    "kind",
    "parent",
    "status",
    "title",
    "children_complete",
    "evidence",
}
_EVIDENCE_KEYS = {"source", "record"}
_SOURCE_KINDS = {"authorized-mcp-payload", "existing-authorized-cache"}


class ProvisionError(ValueError):
    """Base class for provision-index and citation failures."""


class MalformedCitation(ProvisionError):
    """A citation does not fully match the registered family's grammar."""


class ProvisionIndexError(ProvisionError):
    """A committed provision index is structurally invalid."""


class ProvisionIndexUnavailable(ProvisionError):
    """The selected code does not declare an offline provision index."""


class ProvisionAbsent(ProvisionError):
    """The authority-backed index confirms that a provision is absent."""


class ProvisionNotIndexed(ProvisionError):
    """The index has no evidence for the requested provision."""


class StaleProvisionEvidence(ProvisionError):
    """The normalized index no longer matches one of its committed sources."""


@dataclass(frozen=True)
class Citation:
    """One parsed, canonical provision citation."""

    family: str
    canonical: str
    division: str
    kind: str
    parent: str | None


@dataclass(frozen=True)
class ProvisionCheck:
    """The offline evidence state for one well-formed citation."""

    code: str
    citation: Citation
    status: str
    detail: str
    provision: dict[str, Any] | None = None


@dataclass(frozen=True)
class _EvidenceWitness:
    exact: bool
    structural_children: frozenset[str] | None = None


def _malformed(value: object, detail: str) -> MalformedCitation:
    return MalformedCitation(
        f"malformed NECB provision citation {value!r}: {detail}. Expected an "
        "Article/Sentence/Clause/Subclause number, 'Table ...', "
        "'Table ... Note (n)', 'Note A-...', or an explicitly qualified "
        "'Division A ...' citation"
    )


def _article_citation(value: str, match: re.Match[str]) -> Citation:
    division_text = match.group("division")
    division = division_text.rsplit(maxsplit=1)[-1].upper() if division_text else "B"
    number = match.group("number")
    tokens = _TOKEN_RE.findall(match.group("suffix"))
    if len(tokens) > 3:
        raise _malformed(value, "an article may carry at most sentence, clause, and subclause")

    normalized: list[str] = []
    if tokens:
        if not tokens[0].isdigit() or int(tokens[0]) < 1:
            raise _malformed(value, "the first parenthesized component must be a positive sentence")
        normalized.append(str(int(tokens[0])))
    if len(tokens) >= 2:
        if not re.fullmatch(r"[a-z]+", tokens[1], re.IGNORECASE):
            raise _malformed(value, "the second parenthesized component must be a clause letter")
        normalized.append(tokens[1].lower())
    if len(tokens) == 3:
        if not _ROMAN_RE.fullmatch(tokens[2].lower()):
            raise _malformed(value, "the third parenthesized component must be a roman subclause")
        normalized.append(tokens[2].lower())

    stem = f"Division A {number}" if division == "A" else number
    canonical = stem
    parents = [None]
    if normalized:
        canonical = f"{stem}.({normalized[0]})"
        parents.append(stem)
    if len(normalized) >= 2:
        canonical += f"({normalized[1]})"
        parents.append(f"{stem}.({normalized[0]})")
    if len(normalized) == 3:
        canonical += f"({normalized[2]})"
        parents.append(f"{stem}.({normalized[0]})({normalized[1]})")

    kind = ("article", "sentence", "clause", "subclause")[len(normalized)]
    label = match.group("label")
    if label is not None and label.lower() != kind:
        raise _malformed(
            value,
            f"the {label} label does not match the citation's {kind} structure",
        )
    return Citation(
        family="necb",
        canonical=canonical,
        division=division,
        kind=kind,
        parent=parents[-1],
    )


def _parse_necb(value: object) -> Citation:
    if not isinstance(value, str) or not value.strip():
        raise _malformed(value, "the citation must be a non-blank string")
    text = " ".join(value.strip().split())

    table = _TABLE_RE.fullmatch(text)
    if table is not None:
        identifier = table.group("table").upper()
        identifier = re.sub(
            r"\(([A-Z]+)\)",
            lambda match: f"({match.group(1).lower()})",
            identifier,
        )
        note = table.group("note")
        canonical_table = f"Table {identifier}"
        if note is None:
            return Citation("necb", canonical_table, "B", "table", None)
        if int(note) < 1:
            raise _malformed(value, "a table-note number must be positive")
        canonical = f"{canonical_table} Note ({int(note)})"
        return Citation("necb", canonical, "B", "table-note", canonical_table)

    appendix = _APPENDIX_RE.fullmatch(text)
    if appendix is not None:
        identifier = appendix.group("note").upper()
        identifier = re.sub(
            r"\(([A-Z]+)\)",
            lambda match: f"({match.group(1).lower()})",
            identifier,
        )
        return Citation("necb", f"Note {identifier}", "B", "appendix-note", None)

    article = _ARTICLE_RE.fullmatch(text)
    if article is not None:
        return _article_citation(text, article)

    raise _malformed(value, "the whole string must match one supported provision form")


def parse_citation(value: object, *, family: str) -> Citation:
    """Parse one citation using the selected code family's exact grammar.

    NECB is the only registered syntax today.  Other families fail explicitly
    rather than inheriting NECB numbering or implying authoritative access.
    """
    if family != "necb":
        raise ProvisionIndexUnavailable(
            f"no provision-citation parser is registered for code family {family!r}"
        )
    return _parse_necb(value)


def _next_letter(letter: str) -> str:
    if letter == "z":
        return "aa"
    return chr(ord(letter) + 1)


def structure_from_text(record: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Extract a complete sentence/clause/subclause identity tree."""
    raw = record.get("full_text")
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError("section payload has no full_text to structure")

    sentences: dict[str, dict[str, Any]] = {}
    current_sentence: dict[str, Any] | None = None
    current_clause: list[str] | None = None
    expected_letter = "a"

    lines = raw.splitlines()
    for position, raw_line in enumerate(lines):
        line = raw_line.strip()
        if not line:
            continue

        sentence = _SENTENCE_LINE_RE.match(line)
        if sentence is not None:
            number = str(int(sentence.group(1)))
            if number in sentences:
                raise ValueError(f"duplicate sentence ({number})")
            current_sentence = {"clauses": {}}
            sentences[number] = current_sentence
            current_clause = None
            expected_letter = "a"
            continue

        clause = _CLAUSE_LINE_RE.match(line)
        if clause is not None and current_sentence is not None:
            letter = clause.group(1)
            next_marker = None
            for following in lines[position + 1 :]:
                following = following.strip()
                if not following:
                    continue
                roman = _ROMAN_LINE_RE.match(following)
                if roman is not None:
                    next_marker = roman.group(1)
                break
            roman_context = (
                letter in {"i", "v", "x"}
                and letter != expected_letter
                and current_clause is not None
            )
            roman_context |= (
                letter == "i"
                and letter == expected_letter
                and current_clause is not None
                and next_marker == "ii"
            )
            if not roman_context:
                if letter != expected_letter:
                    raise ValueError(
                        f"sentence ({next(reversed(sentences))}) expected clause "
                        f"({expected_letter}), found ({letter})"
                    )
                current_clause = []
                current_sentence["clauses"][letter] = current_clause
                expected_letter = _next_letter(letter)
                continue

        roman = _ROMAN_LINE_RE.match(line)
        if roman is not None and current_clause is not None:
            identifier = roman.group(1)
            if identifier in current_clause:
                raise ValueError(f"duplicate subclause ({identifier})")
            if len(current_clause) >= len(_ROMAN_SEQUENCE):
                raise ValueError(
                    f"more than {len(_ROMAN_SEQUENCE)} supported subclauses"
                )
            expected_roman = _ROMAN_SEQUENCE[len(current_clause)]
            if identifier != expected_roman:
                raise ValueError(
                    f"expected subclause ({expected_roman}), found ({identifier})"
                )
            current_clause.append(identifier)

    if not sentences:
        raise ValueError("section payload contains no numbered sentences")
    numbers = [int(number) for number in sentences]
    expected = list(range(1, len(numbers) + 1))
    if numbers != expected:
        raise ValueError(
            f"sentence numbering is not contiguous: found {numbers}, expected {expected}"
        )
    return sentences


def structure_from_cache(record: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Normalize one existing Section 8.4 cache record's verified tree."""
    if record.get("parse_ok") is not True:
        raise ValueError(
            "Section 8.4 cache record is not structurally verified: "
            f"{record.get('reason') or 'parse_ok is not true'}"
        )
    sentences = record.get("sentences")
    if not isinstance(sentences, list) or not sentences:
        raise ValueError("Section 8.4 cache record contains no sentences")

    normalized: dict[str, dict[str, Any]] = {}
    for expected_sentence, sentence in enumerate(sentences, start=1):
        if not isinstance(sentence, dict):
            raise ValueError("Section 8.4 cache contains a non-object sentence")
        number = str(int(sentence["num"]))
        if int(number) != expected_sentence:
            raise ValueError(
                "Section 8.4 cache sentence numbering is not contiguous: "
                f"expected {expected_sentence}, found {number}"
            )
        raw_clauses = sentence.get("clauses") or []
        if not isinstance(raw_clauses, list):
            raise ValueError(
                f"Section 8.4 cache Sentence ({number}) clauses is not a list"
            )
        clauses: dict[str, list[str]] = {}
        expected_letter = "a"
        for clause in raw_clauses:
            if not isinstance(clause, dict):
                raise ValueError(
                    f"Section 8.4 cache Sentence ({number}) contains a "
                    "non-object clause"
                )
            letter = str(clause["id"]).lower()
            if letter != expected_letter:
                raise ValueError(
                    f"Section 8.4 cache Sentence ({number}) expected Clause "
                    f"({expected_letter}), found ({letter})"
                )
            raw_subclauses = clause.get("subclauses") or []
            if not isinstance(raw_subclauses, list):
                raise ValueError(
                    f"Section 8.4 cache Clause ({letter}) subclauses is not a list"
                )
            subclauses: list[str] = []
            for position, item in enumerate(raw_subclauses):
                if not isinstance(item, dict):
                    raise ValueError(
                        f"Section 8.4 cache Clause ({letter}) contains a "
                        "non-object subclause"
                    )
                identifier = str(item["id"]).lower()
                if position >= len(_ROMAN_SEQUENCE):
                    raise ValueError(
                        f"Section 8.4 cache Clause ({letter}) has more than "
                        f"{len(_ROMAN_SEQUENCE)} supported subclauses"
                    )
                expected_roman = _ROMAN_SEQUENCE[position]
                if identifier != expected_roman:
                    raise ValueError(
                        f"Section 8.4 cache Clause ({letter}) expected Subclause "
                        f"({expected_roman}), found ({identifier})"
                    )
                subclauses.append(identifier)
            clauses[letter] = subclauses
            expected_letter = _next_letter(letter)
        normalized[number] = {"clauses": clauses}
    return normalized


def table_note_ids(article: dict[str, Any], table_number: str) -> list[str]:
    """Return the complete numbered-note inventory under one table heading."""
    raw = article.get("raw")
    if not isinstance(raw, str):
        raise ValueError(f"article cache has no raw text for Table {table_number}")
    heading = re.compile(
        _NOTE_HEADING.format(table=re.escape(table_number)),
        re.MULTILINE,
    )
    matches = list(heading.finditer(raw))
    if len(matches) != 1:
        raise ValueError(
            f"expected one 'Notes to Table {table_number}' heading, "
            f"found {len(matches)}"
        )

    notes: list[str] = []
    for raw_line in raw[matches[0].end() :].splitlines():
        line = raw_line.strip()
        note = _TABLE_NOTE_LINE_RE.match(line)
        if note is not None:
            number = str(int(note.group(1)))
            if number in notes:
                raise ValueError(f"Table {table_number} repeats Note ({number})")
            notes.append(number)
            continue
        if notes and _SENTENCE_LINE_RE.match(line):
            break
    if not notes:
        raise ValueError(
            f"Table {table_number} has a notes heading but no numbered notes"
        )
    numbers = [int(number) for number in notes]
    if numbers != list(range(1, len(numbers) + 1)):
        raise ValueError(
            f"Table {table_number} note numbering is not contiguous: {numbers}"
        )
    return notes


def _snapshot(code_id: str) -> tuple[Any, Path, dict[str, Any]]:
    from btap.codes import _family_roots, resolve

    ruleset = resolve(code_id)
    roots = dict(_family_roots())
    try:
        root = roots[ruleset.family] / ruleset.id
    except KeyError:
        raise ProvisionIndexUnavailable(
            f"code family {ruleset.family!r} has no registered data root"
        ) from None
    manifest_path = root / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    return ruleset, root, manifest


def _relative_source(snapshot: Path, value: object, *, context: str) -> Path:
    if not isinstance(value, str) or not value:
        raise ProvisionIndexError(f"{context}.path must be a non-blank relative path")
    relative = PurePosixPath(value)
    if relative.is_absolute() or ".." in relative.parts:
        raise ProvisionIndexError(f"{context}.path must stay inside the edition snapshot")
    return snapshot.joinpath(*relative.parts)


def _exact_keys(value: object, expected: set[str], *, context: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ProvisionIndexError(f"{context} must be an object")
    actual = set(value)
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        raise ProvisionIndexError(
            f"{context} has wrong keys; missing={missing}, extra={extra}"
        )
    return value


def _article_tree(
    article: str,
    structure: dict[str, dict[str, Any]],
) -> set[str]:
    citations = {article}
    for sentence, sentence_record in structure.items():
        sentence_citation = f"{article}.({sentence})"
        citations.add(sentence_citation)
        for clause, subclauses in sentence_record["clauses"].items():
            clause_citation = f"{sentence_citation}({clause})"
            citations.add(clause_citation)
            citations.update(
                f"{clause_citation}({subclause})" for subclause in subclauses
            )
    return citations


def _structural_children(citations: set[str], parent: str, *, family: str) -> frozenset[str]:
    return frozenset(
        candidate
        for candidate in citations
        if parse_citation(candidate, family=family).parent == parent
    )


def _article_ancestor(citation: Citation) -> str | None:
    current = citation
    while current.kind not in {"article", "table", "appendix-note"}:
        if current.parent is None:
            return None
        current = parse_citation(current.parent, family=current.family)
    return current.canonical if current.kind == "article" else None


def _semantic_error(context: str, locator: str, detail: str) -> ProvisionIndexError:
    return ProvisionIndexError(
        f"{context}.record {locator!r} does not semantically witness the "
        f"indexed provision: {detail}"
    )


def _mcp_evidence_witness(
    source_value: Any,
    locator: str,
    *,
    record: dict[str, Any],
    citation: Citation,
    ruleset: Any,
    context: str,
) -> _EvidenceWitness:
    if not isinstance(source_value, dict) or locator not in source_value:
        raise ProvisionIndexError(
            f"{context}.record {locator!r} is not in the authorized MCP archive"
        )
    payload = source_value[locator]
    parts = locator.split(":")
    if len(parts) != 5:
        raise _semantic_error(context, locator, "the archive locator is malformed")
    tool, family, edition, scope, identifier = parts
    if family != ruleset.family or edition != ruleset.edition:
        raise _semantic_error(
            context,
            locator,
            f"it addresses {family!r} {edition!r}, not "
            f"{ruleset.family!r} {ruleset.edition!r}",
        )

    if tool == "get_section":
        if not isinstance(payload, dict):
            raise _semantic_error(context, locator, "the section result is not an object")
        expected = {
            "edition": edition,
            "division": scope,
            "section_number": identifier,
            "article_number": identifier,
        }
        differences = {
            key: (payload.get(key), value)
            for key, value in expected.items()
            if payload.get(key) != value
        }
        if differences:
            raise _semantic_error(
                context,
                locator,
                f"the section identity differs: {differences}",
            )
        level = payload.get("hierarchy_level")
        if level == "article":
            article = f"Division A {identifier}" if scope == "A" else identifier
            try:
                tree = _article_tree(article, structure_from_text(payload))
            except (KeyError, TypeError, ValueError) as exc:
                raise _semantic_error(
                    context,
                    locator,
                    f"the article hierarchy cannot be reconstructed: {exc}",
                ) from exc
            if record["status"] == "present" and citation.canonical in tree:
                return _EvidenceWitness(
                    True,
                    _structural_children(
                        tree,
                        citation.canonical,
                        family=ruleset.family,
                    ),
                )
            raise _semantic_error(
                context,
                locator,
                f"{citation.canonical!r} is not present in the reconstructed "
                f"hierarchy of {article}",
            )
        if level == "note":
            note = parse_citation(f"Note {identifier}", family=ruleset.family)
            explains = payload.get("explains")
            if (
                record["status"] == "present"
                and citation.canonical == note.canonical
                and record["parent"] == explains
                and payload.get("normative") is False
            ):
                return _EvidenceWitness(True, frozenset())
            raise _semantic_error(
                context,
                locator,
                f"the explanatory note identifies {note.canonical!r} with "
                f"parent {explains!r}, not {citation.canonical!r} with parent "
                f"{record['parent']!r}",
            )
        raise _semantic_error(
            context,
            locator,
            f"the section hierarchy level is {level!r}, not 'article' or 'note'",
        )

    if tool == "get_table":
        if not isinstance(payload, dict):
            raise _semantic_error(context, locator, "the table result is not an object")
        expected = {
            "edition": edition,
            "division": scope,
            "table_number": identifier,
        }
        differences = {
            key: (payload.get(key), value)
            for key, value in expected.items()
            if payload.get(key) != value
        }
        rows = payload.get("rows")
        if differences or not isinstance(rows, list) or payload.get("row_count") != len(
            rows
        ) or payload.get("has_more"):
            raise _semantic_error(
                context,
                locator,
                "the table identity or completeness metadata does not match",
            )
        table = parse_citation(f"Table {identifier}", family=ruleset.family)
        if record["status"] != "present":
            raise _semantic_error(context, locator, "a returned table proves presence")
        if citation.canonical == table.canonical:
            numeric_parent = identifier.split(".-", 1)[0]
            if record["parent"] != numeric_parent:
                raise _semantic_error(
                    context,
                    locator,
                    f"Table {identifier} belongs to Article {numeric_parent}, not "
                    f"{record['parent']!r}",
                )
            return _EvidenceWitness(True)
        if citation.kind == "table-note" and citation.parent == table.canonical:
            return _EvidenceWitness(False)
        raise _semantic_error(
            context,
            locator,
            f"the payload identifies {table.canonical!r}, not "
            f"{citation.canonical!r}",
        )

    if tool == "query_sections":
        if scope != "article" or not isinstance(payload, list) or not payload:
            raise _semantic_error(
                context,
                locator,
                "the article inventory is empty or not an article query result",
            )
        if len(payload) >= _QUERY_RESULT_LIMIT:
            raise _semantic_error(
                context,
                locator,
                f"the article inventory reached its {_QUERY_RESULT_LIMIT}-record limit",
            )
        if identifier.count("%") != 1 or not identifier.endswith("%"):
            raise _semantic_error(
                context,
                locator,
                f"unsupported inventory pattern {identifier!r}",
            )
        number_pattern = re.compile(
            "^" + re.escape(identifier).replace("%", r"\d+") + "$"
        )
        numbers: set[str] = set()
        for item in payload:
            if not isinstance(item, dict):
                raise _semantic_error(
                    context,
                    locator,
                    "the article inventory contains a non-object",
                )
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
            number = item.get("section_number")
            if (
                differences
                or not isinstance(number, str)
                or number_pattern.fullmatch(number) is None
                or item.get("article_number") != number
                or number in numbers
            ):
                raise _semantic_error(
                    context,
                    locator,
                    "the article inventory contains an invalid or repeated identity",
                )
            numbers.add(number)
        suffixes = sorted(int(number.rsplit(".", 1)[-1]) for number in numbers)
        if suffixes != list(range(1, suffixes[-1] + 1)):
            raise _semantic_error(
                context,
                locator,
                f"the article inventory is not contiguous: {suffixes}",
            )
        article = _article_ancestor(citation)
        if article is None or number_pattern.fullmatch(article) is None:
            raise _semantic_error(
                context,
                locator,
                f"{citation.canonical!r} is outside inventory pattern {identifier!r}",
            )
        if record["status"] == "present" and article in numbers:
            return _EvidenceWitness(citation.kind == "article")
        if (
            record["status"] == "absent"
            and citation.kind == "article"
            and article not in numbers
        ):
            return _EvidenceWitness(True)
        raise _semantic_error(
            context,
            locator,
            f"the complete inventory has articles {sorted(numbers)!r}",
        )

    raise _semantic_error(context, locator, f"unsupported MCP tool {tool!r}")


def _cache_evidence_witness(
    source_value: Any,
    locator: str,
    *,
    record: dict[str, Any],
    citation: Citation,
    ruleset: Any,
    context: str,
) -> _EvidenceWitness:
    if not isinstance(source_value, dict):
        raise _semantic_error(context, locator, "the Section 8.4 cache is not an object")
    provenance = source_value.get("provenance")
    if not isinstance(provenance, dict) or (
        provenance.get("code"),
        provenance.get("edition"),
    ) != (ruleset.family, ruleset.edition):
        raise _semantic_error(
            context,
            locator,
            "the Section 8.4 cache identifies a different code or edition",
        )
    prefix = "articles."
    article_number = locator.removeprefix(prefix)
    articles = source_value.get("articles")
    if (
        not locator.startswith(prefix)
        or not isinstance(articles, dict)
        or article_number not in articles
        or not isinstance(articles[article_number], dict)
    ):
        raise ProvisionIndexError(
            f"{context}.record {locator!r} is not in the existing Section 8.4 cache"
        )
    article = articles[article_number]
    try:
        tree = _article_tree(article_number, structure_from_cache(article))
    except (KeyError, TypeError, ValueError) as exc:
        raise _semantic_error(
            context,
            locator,
            f"the cached article hierarchy cannot be reconstructed: {exc}",
        ) from exc
    if record["status"] == "present" and citation.canonical in tree:
        return _EvidenceWitness(
            True,
            _structural_children(
                tree,
                citation.canonical,
                family=ruleset.family,
            ),
        )

    if citation.kind in {"table", "table-note"}:
        table = (
            citation.canonical
            if citation.kind == "table"
            else citation.parent
        )
        assert table is not None
        table_number = table.removeprefix("Table ")
        try:
            notes = table_note_ids(article, table_number)
        except ValueError as exc:
            raise _semantic_error(context, locator, str(exc)) from exc
        table_citations = {table}
        table_citations.update(f"{table} Note ({note})" for note in notes)
        if record["status"] == "present" and citation.canonical in table_citations:
            numeric_parent = table_number.split(".-", 1)[0]
            if citation.kind == "table" and record["parent"] != numeric_parent:
                raise _semantic_error(
                    context,
                    locator,
                    f"{table} belongs to Article {numeric_parent}, not "
                    f"{record['parent']!r}",
                )
            structural_children = (
                frozenset(f"{table} Note ({note})" for note in notes)
                if citation.kind == "table"
                else frozenset()
            )
            return _EvidenceWitness(True, structural_children)

    raise _semantic_error(
        context,
        locator,
        f"{citation.canonical!r} is not present in cached Article {article_number}",
    )


def _validate_document(
    document: object,
    *,
    ruleset: Any,
    snapshot: Path,
) -> tuple[dict[str, Any], str | None]:
    doc = _exact_keys(document, _DOCUMENT_KEYS, context="provision index")
    if doc["schema"] != SCHEMA_VERSION:
        raise ProvisionIndexError(
            f"{ruleset.id} provision index schema {doc['schema']!r} is not "
            f"supported; expected {SCHEMA_VERSION}"
        )
    if not isinstance(doc["generated"], str) or not _DATE_RE.fullmatch(doc["generated"]):
        raise ProvisionIndexError("provision index generated must be YYYY-MM-DD")

    code = _exact_keys(doc["code"], _CODE_KEYS, context="provision index code")
    expected_code = {
        "family": ruleset.family,
        "id": ruleset.id,
        "edition": ruleset.edition,
    }
    if code != expected_code:
        raise ProvisionIndexError(
            f"{ruleset.id} provision index identifies {code!r}, expected {expected_code!r}"
        )

    if not isinstance(doc["sources"], dict) or not doc["sources"]:
        raise ProvisionIndexError("provision index sources must be a non-empty object")
    stale: list[str] = []
    stale_source_ids: set[str] = set()
    source_documents: dict[str, tuple[str, Any]] = {}
    for source_id, raw_source in sorted(doc["sources"].items()):
        if not isinstance(source_id, str) or not source_id:
            raise ProvisionIndexError("provision index source ids must be non-blank strings")
        context = f"provision index sources[{source_id!r}]"
        source = _exact_keys(raw_source, _SOURCE_KEYS, context=context)
        if source["kind"] not in _SOURCE_KINDS:
            raise ProvisionIndexError(
                f"{context}.kind must be one of {sorted(_SOURCE_KINDS)!r}"
            )
        if (
            not isinstance(source["retrieved"], str)
            or not _DATE_RE.fullmatch(source["retrieved"])
        ):
            raise ProvisionIndexError(f"{context}.retrieved must be YYYY-MM-DD")
        if not isinstance(source["sha256"], str) or not _SHA256_RE.fullmatch(
            source["sha256"]
        ):
            raise ProvisionIndexError(f"{context}.sha256 must be a lowercase SHA-256")
        path = _relative_source(snapshot, source["path"], context=context)
        if not path.is_file():
            stale.append(f"{source['path']} is missing")
            stale_source_ids.add(source_id)
            continue
        source_bytes = path.read_bytes()
        digest = hashlib.sha256(source_bytes).hexdigest()
        if digest != source["sha256"]:
            stale.append(
                f"{source['path']} hashes {digest}, index records {source['sha256']}"
            )
            stale_source_ids.add(source_id)
        try:
            source_documents[source_id] = (
                source["kind"],
                json.loads(source_bytes.decode("utf-8")),
            )
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            if source_id in stale_source_ids:
                continue
            raise ProvisionIndexError(
                f"{context}.path {source['path']!r} is not UTF-8 JSON: {exc}"
            ) from exc

    if not isinstance(doc["provisions"], dict) or not doc["provisions"]:
        raise ProvisionIndexError("provision index provisions must be a non-empty object")
    parsed_citations: dict[str, Citation] = {}
    normalized_keys: dict[str, list[str]] = {}
    for key in sorted(doc["provisions"]):
        citation = parse_citation(key, family=ruleset.family)
        parsed_citations[key] = citation
        normalized_keys.setdefault(citation.canonical, []).append(key)
    duplicates = {
        canonical: keys
        for canonical, keys in normalized_keys.items()
        if len(keys) > 1
    }
    if duplicates:
        canonical, keys = next(iter(sorted(duplicates.items())))
        raise ProvisionIndexError(
            f"provision index has duplicate normalized identity {canonical!r}: "
            f"{keys!r}"
        )
    for key, citation in parsed_citations.items():
        if key != citation.canonical:
            raise ProvisionIndexError(
                f"provision index key {key!r} is an alias; use canonical "
                f"{citation.canonical!r}"
            )

    complete_child_witnesses: dict[str, frozenset[str]] = {}
    for key, raw_record in sorted(doc["provisions"].items()):
        context = f"provision index provisions[{key!r}]"
        record = _exact_keys(raw_record, _PROVISION_KEYS, context=context)
        if record["citation"] != key:
            raise ProvisionIndexError(
                f"{context}.citation {record['citation']!r} does not match its key"
            )
        citation = parsed_citations[key]
        if record["division"] != citation.division:
            raise ProvisionIndexError(
                f"{context}.division {record['division']!r} does not match "
                f"{citation.division!r}"
            )
        if record["kind"] != citation.kind or record["kind"] not in KINDS:
            raise ProvisionIndexError(
                f"{context}.kind {record['kind']!r} does not match {citation.kind!r}"
            )
        if record["status"] not in {"present", "absent"}:
            raise ProvisionIndexError(f"{context}.status must be 'present' or 'absent'")
        if not isinstance(record["children_complete"], bool):
            raise ProvisionIndexError(f"{context}.children_complete must be boolean")
        if record["status"] == "absent" and record["children_complete"]:
            raise ProvisionIndexError(
                f"{context} is absent and cannot declare complete children"
            )
        if record["title"] is not None and not isinstance(record["title"], str):
            raise ProvisionIndexError(f"{context}.title must be a string or null")
        parent = record["parent"]
        if parent is not None and not isinstance(parent, str):
            raise ProvisionIndexError(f"{context}.parent must be a string or null")
        if citation.parent is not None:
            if parent != citation.parent:
                raise ProvisionIndexError(
                    f"{context}.parent {parent!r} does not match the citation parent "
                    f"{citation.parent!r}"
                )
        elif citation.kind == "article" and parent is not None:
            raise ProvisionIndexError(f"{context}.parent must be null for an article")
        elif parent is not None:
            parsed_parent = parse_citation(parent, family=ruleset.family)
            if parent != parsed_parent.canonical:
                raise ProvisionIndexError(
                    f"{context}.parent {parent!r} is an alias; use canonical "
                    f"{parsed_parent.canonical!r}"
                )
            appendix_parent = (
                citation.kind == "appendix-note"
                and parsed_parent.kind
                in {"article", "sentence", "clause", "subclause"}
            )
            if (not appendix_parent and parsed_parent.kind != "article") or (
                parsed_parent.division != citation.division
            ):
                raise ProvisionIndexError(
                    f"{context}.parent {parent!r} must be an "
                    f"{'Article, Sentence, Clause, or Subclause' if citation.kind == 'appendix-note' else 'Article'} "
                    f"in Division {citation.division}"
                )
        if not isinstance(record["evidence"], list) or not record["evidence"]:
            raise ProvisionIndexError(f"{context}.evidence must be a non-empty list")
        for position, raw_evidence in enumerate(record["evidence"]):
            evidence_context = f"{context}.evidence[{position}]"
            evidence = _exact_keys(
                raw_evidence, _EVIDENCE_KEYS, context=evidence_context
            )
            if evidence["source"] not in doc["sources"]:
                raise ProvisionIndexError(
                    f"{evidence_context}.source {evidence['source']!r} is not declared"
                )
            if not isinstance(evidence["record"], str) or not evidence["record"]:
                raise ProvisionIndexError(
                    f"{evidence_context}.record must be a non-blank string"
                )

        has_exact_witness = False
        has_stale_witness = False
        child_witnesses: list[frozenset[str]] = []
        for position, evidence in enumerate(record["evidence"]):
            evidence_context = f"{context}.evidence[{position}]"
            source_document = source_documents.get(evidence["source"])
            if source_document is None or evidence["source"] in stale_source_ids:
                has_stale_witness = True
                continue
            source_kind, source_value = source_document
            locator = evidence["record"]
            if source_kind == "authorized-mcp-payload":
                witness = _mcp_evidence_witness(
                    source_value,
                    locator,
                    record=record,
                    citation=citation,
                    ruleset=ruleset,
                    context=evidence_context,
                )
            elif source_kind == "existing-authorized-cache":
                witness = _cache_evidence_witness(
                    source_value,
                    locator,
                    record=record,
                    citation=citation,
                    ruleset=ruleset,
                    context=evidence_context,
                )
            else:  # pragma: no cover - source kind is checked above
                raise AssertionError(source_kind)
            has_exact_witness = has_exact_witness or witness.exact
            if witness.structural_children is not None:
                child_witnesses.append(witness.structural_children)
        if not has_exact_witness and not has_stale_witness:
            raise ProvisionIndexError(
                f"{context}.evidence has no source record that semantically "
                f"witnesses {record['status']} {citation.canonical!r}"
            )
        if record["children_complete"] and not has_stale_witness:
            if not child_witnesses:
                raise ProvisionIndexError(
                    f"{context}.children_complete has no semantic child-inventory "
                    "witness"
                )
            first = child_witnesses[0]
            if any(children != first for children in child_witnesses[1:]):
                raise ProvisionIndexError(
                    f"{context}.evidence sources disagree about the complete "
                    "structural child inventory"
                )
            complete_child_witnesses[key] = first

    provisions = doc["provisions"]
    for key, record in provisions.items():
        parent = record["parent"]
        if parent is not None and parent not in provisions:
            raise ProvisionIndexError(
                f"provision index provisions[{key!r}].parent {parent!r} is not indexed"
            )
    for key, expected_children in complete_child_witnesses.items():
        indexed_children = frozenset(
            child
            for child, citation in parsed_citations.items()
            if citation.parent == key
        )
        if indexed_children != expected_children:
            raise ProvisionIndexError(
                f"provision index provisions[{key!r}].children_complete disagrees "
                f"with its evidence; indexed={sorted(indexed_children)!r}, "
                f"evidence={sorted(expected_children)!r}"
            )
    return doc, "; ".join(stale) if stale else None


def _document(code_id: str) -> tuple[Any, dict[str, Any] | None, str | None]:
    ruleset, snapshot, manifest = _snapshot(code_id)
    relative = manifest.get("provision_index")
    if relative is None:
        return ruleset, None, None
    path = _relative_source(snapshot, relative, context=f"{code_id} manifest provision_index")
    if not path.is_file():
        return ruleset, None, f"{relative} is missing"
    index_bytes = path.read_bytes()
    stale_problems: list[str] = []
    provenance = manifest.get("provenance") or {}
    binding = provenance.get(relative)
    if not isinstance(binding, dict):
        raise ProvisionIndexError(
            f"{code_id} manifest provenance does not bind provision_index {relative!r}"
        )
    result_sha256 = binding.get("result_sha256")
    if not isinstance(result_sha256, str) or not _SHA256_RE.fullmatch(result_sha256):
        raise ProvisionIndexError(
            f"{code_id} manifest provenance for {relative!r} has no lowercase "
            "result_sha256"
        )
    actual = hashlib.sha256(index_bytes).hexdigest()
    if actual != result_sha256:
        return (
            ruleset,
            None,
            f"{relative} hashes {actual}, manifest records {result_sha256}",
        )
    try:
        document = json.loads(index_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProvisionIndexError(
            f"{code_id} provision_index {relative!r} is not UTF-8 JSON: {exc}"
        ) from exc
    validated, source_stale = _validate_document(
        document, ruleset=ruleset, snapshot=snapshot
    )
    if source_stale:
        stale_problems.append(source_stale)
    return (
        ruleset,
        validated,
        "; ".join(stale_problems) if stale_problems else None,
    )


def provision_index(code_id: str) -> dict[str, Any]:
    """Return a fresh copy of one code's validated, current offline index."""
    _ruleset, document, stale = _document(code_id)
    if stale:
        raise StaleProvisionEvidence(f"{code_id} provision evidence is stale: {stale}")
    if document is None:
        raise ProvisionIndexUnavailable(
            f"{code_id} does not declare an installed provision_index"
        )
    return copy.deepcopy(document)


def check_citation(code_id: str, value: object) -> ProvisionCheck:
    """Return ``present``, ``absent``, ``not-indexed``, ``stale`` or ``unsupported``.

    ``absent`` requires positive negative evidence: either an explicit absent
    record or a missing child beneath a parent whose child inventory is marked
    complete.  A citation outside the representative cache is ``not-indexed``;
    absence is never inferred from silence.
    """
    ruleset, document, stale = _document(code_id)
    citation = parse_citation(value, family=ruleset.family)
    if stale:
        return ProvisionCheck(
            code_id,
            citation,
            "stale",
            f"{code_id} provision evidence is stale: {stale}",
        )
    if document is None:
        detail = f"{code_id} does not declare an installed provision_index"
        return ProvisionCheck(code_id, citation, "unsupported", detail)

    provisions = document["provisions"]
    record = provisions.get(citation.canonical)
    if record is not None:
        status = record["status"]
        detail = (
            f"{citation.canonical} is present in {code_id}"
            if status == "present"
            else f"{citation.canonical} is authority-confirmed absent from {code_id}"
        )
        return ProvisionCheck(
            code_id,
            citation,
            status,
            detail,
            copy.deepcopy(record),
        )

    ancestor = citation.parent
    while ancestor is not None:
        parent = provisions.get(ancestor)
        if parent is not None:
            if parent["status"] == "absent" or parent["children_complete"]:
                return ProvisionCheck(
                    code_id,
                    citation,
                    "absent",
                    f"{citation.canonical} is absent from the complete "
                    f"child inventory of {ancestor} in {code_id}",
                )
            break
        ancestor = parse_citation(ancestor, family=ruleset.family).parent

    return ProvisionCheck(
        code_id,
        citation,
        "not-indexed",
        f"{citation.canonical} has no committed evidence in {code_id}; "
        "missing cache data is not evidence of absence",
    )


def validate_citation(code_id: str, value: object) -> dict[str, Any]:
    """Return the indexed provision record or raise a state-specific error."""
    result = check_citation(code_id, value)
    if result.status == "present":
        assert result.provision is not None
        return result.provision
    if result.status == "absent":
        raise ProvisionAbsent(result.detail)
    if result.status == "not-indexed":
        raise ProvisionNotIndexed(result.detail)
    if result.status == "stale":
        raise StaleProvisionEvidence(result.detail)
    if result.status == "unsupported":
        raise ProvisionIndexUnavailable(result.detail)
    raise ProvisionError(f"unknown provision check status {result.status!r}")
