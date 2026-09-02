#!/usr/bin/env python3
"""Generate the article-by-article NECB Section 8.4 coverage document."""

from __future__ import annotations

import argparse
import ast
import json
import os
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT = REPO_ROOT / "docs" / "NECB_8_4_COVERAGE.html"
DEFAULT_COVERAGE_DATA = REPO_ROOT / "python" / "btap" / "necb" / "data" / "coverage"
DEFAULT_CACHE_2020 = DEFAULT_COVERAGE_DATA / "necb_8_4_articles_2020.json"
DEFAULT_CACHE_2025 = DEFAULT_COVERAGE_DATA / "necb_8_4_articles_2025.json"
DEFAULT_DISPOSITION = DEFAULT_COVERAGE_DATA / "necb_8_4_disposition.json"
PYTHON_INPUT_MODE = "python"
DEFAULT_INPUT_MODE = PYTHON_INPUT_MODE
REPO_URL = "https://github.com/canmet-energy/openstudio-necb-gems"

SUBSECTIONS = {
    "2020": {
        "8.4.1": "General",
        "8.4.2": "Compliance Calculations",
        "8.4.3": "Proposed Building",
        "8.4.4": "Building Energy Target of the Reference Building",
        "8.4.5": "Part-Load Performance Curves",
    },
    "2025": {
        "8.4.1": "General",
        "8.4.2": "Compliance Calculations",
        "8.4.3": "Proposed Building",
        "8.4.4": "Energy Use Intensity (EUI path — new in 2025)",
        "8.4.5": "Modeled Reference Building",
        "8.4.6": "Part-Load Performance Curves",
    },
}
STATUS_META = {
    "implemented": ("Implemented (self-declared)", "ok"),
    "partial": ("Partial", "warn"),
    "not_implemented": ("Not implemented", "bad"),
    "satisfied_by_clone": ("Satisfied by clone", "clone"),
    "host_scope": ("Delegated", "host"),
}
DISPOSITION_META = {
    "engine": ("EnergyPlus", "clone"),
    "modeller": ("Modeller / AHJ", "host"),
    "covered_by": ("Covered by (undeclared)", "warn"),
    "gap": ("GAP", "bad"),
}
STATE_META = {
    "declared": ("Declared", "ok"),
    "cited": ("Cited in code, not declared", "warn"),
    "dispositioned": ("Dispositioned", "host"),
    "unknown": ("Unknown", "bad"),
}
DOMAIN_SUBDIRS = ("hvac", "envelope", "loads", "lighting", "shw")
MANIFEST_DOMAINS = {"reference": "hvac", "necb": "necb"}


@dataclass(frozen=True)
class Inputs:
    source_root: Path = REPO_ROOT
    manifest_root: Path = REPO_ROOT
    cache_2020: Path = DEFAULT_CACHE_2020
    cache_2025: Path = DEFAULT_CACHE_2025
    disposition: Path = DEFAULT_DISPOSITION
    audit_dirs: tuple[Path, ...] = ()
    branch: str = "main"
    input_mode: str = DEFAULT_INPUT_MODE

    def __post_init__(self):
        if self.input_mode != PYTHON_INPUT_MODE:
            raise ValueError(f"unsupported input mode: {self.input_mode}")

    @property
    def caches(self) -> dict[str, Path]:
        return {"2020": self.cache_2020, "2025": self.cache_2025}

    @property
    def blob(self) -> str:
        return f"{REPO_URL}/blob/{self.branch}"


def esc(text: object) -> str:
    return str(text if text is not None else "").replace("&", "&amp;").replace(
        "<", "&lt;"
    ).replace(">", "&gt;").replace('"', "&quot;")


def split_ref(ref: object) -> tuple[str | None, int | None]:
    match = re.match(r"(8\.4\.\d+\.\d+)\.?\s*(?:\((\d+)\))?", str(ref or ""))
    if match is None:
        return None, None
    return match.group(1), int(match.group(2)) if match.group(2) else None


def disposition_key_for(vintage: str, key: str) -> str | None:
    if vintage != "2020":
        return key
    if key.startswith("8.4.4."):
        return None
    match = re.match(r"8\.4\.([56])\.", key)
    if match is None:
        return key
    return f"8.4.{int(match.group(1)) - 1}." + key[match.end():]


def article_sort_key(article: str) -> list[int]:
    return [int(value) for value in re.findall(r"\d+", article)]


def python_citation_value(node: ast.expr) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if not isinstance(node, ast.JoinedStr):
        return None
    parts = []
    for value in node.values:
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            parts.append(value.value)
        elif isinstance(value, ast.FormattedValue) and isinstance(value.value, ast.Name):
            parts.append(f"{{{value.value.id}}}")
    return "".join(parts)


def python_call_kind(call: ast.Call) -> str:
    name = call.func.attr if isinstance(call.func, ast.Attribute) else ""
    return "warn" if name in {"warn", "warning"} else "cited"


def domain_for(relative: str) -> str:
    if relative.startswith("python/btap/necb/"):
        remainder = relative.removeprefix("python/btap/necb/")
        segment = remainder.split("/", 1)[0]
        return segment if segment in DOMAIN_SUBDIRS else "necb"
    raise ValueError(f"cannot attribute {relative} to a domain — teach domain_for")


def manifest_domain(path: Path) -> str:
    match = re.match(r"([a-z]+)_rules_", path.name)
    if match is None:
        raise ValueError(f"cannot derive manifest domain from {path}")
    return MANIFEST_DOMAINS.get(match.group(1), match.group(1))


class CoverageGenerator:
    def __init__(self, inputs: Inputs):
        self.inputs = inputs
        self.raw_citations = self._scan_citations()
        self.dispositions_2025 = json.loads(
            inputs.disposition.read_text(encoding="utf-8")
        )["dispositions"]
        self.code_lines: dict[str, int | None] = {}

    def _scan_citations(self) -> list[dict]:
        citations = []
        paths = sorted(self.inputs.source_root.glob("python/btap/necb/**/*.py"))
        for path in paths:
            relative = path.relative_to(self.inputs.source_root).as_posix()
            gem_name = domain_for(relative)
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for call in (node for node in ast.walk(tree) if isinstance(node, ast.Call)):
                for keyword in call.keywords:
                    if keyword.arg != "article":
                        continue
                    raw = python_citation_value(keyword.value)
                    if raw is None:
                        continue
                    raw = raw.replace("{prefix}", "PREFIX")
                    tokens = re.findall(
                        r"(?:PREFIX|8\.4)(?:\.\d+)*\.?(?:\(\d+\))?", raw
                    )
                    if tokens:
                        citations.append({
                            "gem": gem_name,
                            "file": relative,
                            "line": keyword.value.lineno,
                            "kind": python_call_kind(call),
                            "tokens": tokens,
                        })
        if not citations:
            raise ValueError(
                f"RAW_CITATIONS is empty — the {self.inputs.input_mode} source glob went stale"
            )
        return citations

    def citations_for(self, vintage: str, articles: dict) -> dict[str, list[dict]]:
        reference_prefix = "8.4.4" if vintage == "2020" else "8.4.5"
        citations: dict[str, list[dict]] = defaultdict(list)
        for citation in self.raw_citations:
            if (vintage == "2020" and citation["gem"] == "necb"
                    and any(token.startswith("8.4.4.") for token in citation["tokens"])):
                continue
            for token in citation["tokens"]:
                ref = token.replace("PREFIX", reference_prefix, 1)
                if ref.startswith("8.4.4."):
                    if citation["gem"] == "necb":
                        if vintage == "2020":
                            continue
                    elif vintage == "2025":
                        ref = ref.replace("8.4.4.", "8.4.5.", 1)
                article, _sentence = split_ref(ref)
                if article and article in articles:
                    candidate = {key: citation[key] for key in ("file", "line", "kind")}
                    if candidate not in citations[article]:
                        citations[article].append(candidate)
        return citations

    def declarations_for(self, vintage: str) -> dict[str, list[dict]]:
        declarations: dict[str, list[dict]] = defaultdict(list)
        paths = sorted(
            self.inputs.manifest_root.glob(f"python/btap/**/*_rules_{vintage}.json")
        )
        for path in paths:
            data = json.loads(path.read_text(encoding="utf-8"))
            entries = data.get("article_coverage", {}).get("articles")
            if entries is None:
                continue
            gem_name = manifest_domain(path)
            for entry in entries:
                if not str(entry.get("article") or "").startswith("8.4"):
                    continue
                article, sentence = split_ref(entry.get("article"))
                if article:
                    declaration = dict(entry)
                    declaration.update(gem=gem_name, vintage=vintage, sentence=sentence)
                    declarations[article].append(declaration)
        if not declarations:
            raise ValueError(
                f"no 8.4 declarations found for {vintage} — the manifest glob went stale"
            )
        return declarations

    def executed_for(self, vintage: str) -> dict[str, list[dict]]:
        executed: dict[str, list[dict]] = defaultdict(list)
        for run_dir in self.inputs.audit_dirs:
            audit_path = run_dir / "audit.json"
            if not audit_path.exists():
                continue
            try:
                run_vintage = str(json.loads((run_dir / "report.json").read_text())["vintage"])
            except (OSError, KeyError, TypeError, ValueError):
                run_vintage = ""
            if run_vintage != vintage:
                continue
            levels: dict[str, Counter] = defaultdict(Counter)
            for entry in json.loads(audit_path.read_text(encoding="utf-8")):
                ref = str(entry.get("article") or "")
                if not ref.startswith("8.4"):
                    continue
                article, _sentence = split_ref(ref)
                if article:
                    levels[article][str(entry.get("level") or "")] += 1
            for article, counts in levels.items():
                executed[article].append({
                    "run": run_dir.name,
                    "vintage": run_vintage,
                    "levels": counts,
                })
        return executed

    def dispositions_for(self, vintage: str, articles: dict) -> dict[str, dict]:
        dispositions = {}
        for key, value in self.dispositions_2025.items():
            mapped = disposition_key_for(vintage, key)
            if mapped and mapped in articles:
                dispositions[mapped] = value
        return dispositions

    @staticmethod
    def states_for(
        articles: dict,
        declarations: dict[str, list[dict]],
        citations: dict[str, list[dict]],
        dispositions: dict[str, dict],
    ) -> tuple[dict[str, str], list[str]]:
        states = {}
        conflicts = []
        for article in articles:
            if article in declarations:
                primary = "declared"
            elif article in citations:
                primary = "cited"
            elif article in dispositions:
                primary = "dispositioned"
            else:
                primary = "unknown"
            states[article] = primary
            if article in dispositions and primary != "dispositioned":
                conflicts.append(article)
        return states, conflicts

    def link(self, citation: dict) -> str:
        short = f"{citation['file'].split('/')[-1]}:{citation['line']}"
        badge = (
            ' <span class="pill bad" title="this citation sits on an audit WARNING — '
            'often announcing the rule is NOT applied">warning</span>'
            if citation["kind"] == "warn" else ""
        )
        return (
            f'<a href="{self.inputs.blob}/{citation["file"]}#L{citation["line"]}" '
            f'title="{esc(citation["file"])}:{citation["line"]}">{esc(short)}</a>{badge}'
        )

    @staticmethod
    def executed_badge(observations: list[dict]) -> str:
        if not observations:
            return ""
        substantive = any(set(observation["levels"]) - {"warning"} for observation in observations)
        label = "observed in run" if substantive else "observed in run (warnings only)"
        css = "ok" if substantive else "warn"
        details = []
        for observation in observations:
            levels = ", ".join(
                f"{count} {level}" for level, count in observation["levels"].items()
            )
            details.append(f"{observation['run']} ({observation['vintage']}): {levels}")
        return f'<span class="pill {css}" title="{esc(" | ".join(details))}">{label}</span>'

    def code_ref_link(self, ref: object) -> str:
        value = str(ref)
        if "#" not in value:
            return esc(value)
        path_text, symbol = value.split("#", 1)
        if value not in self.code_lines:
            line_number = None
            path = self.inputs.source_root / path_text
            if path.is_file():
                pattern = re.compile(
                    rf"def (?:self\.)?{re.escape(symbol)}(?:[\s(=]|$)"
                )
                for index, line in enumerate(
                    path.read_text(encoding="utf-8", errors="replace").splitlines(), 1
                ):
                    if pattern.search(line):
                        line_number = index
                        break
            self.code_lines[value] = line_number
        line_number = self.code_lines[value]
        line_suffix = f":{line_number}" if line_number else ""
        anchor = f"#L{line_number}" if line_number else ""
        text = f"{Path(path_text).name}#{symbol}{line_suffix}"
        return (
            f'<a href="{self.inputs.blob}/{esc(path_text)}{anchor}" '
            f'title="{esc(value)}">{esc(text)}</a>'
        )

    def code_cell(self, entry: dict) -> str:
        refs = entry.get("code") or []
        refs = refs if isinstance(refs, list) else [refs]
        if not refs:
            return ""
        return '<div class="coderefs">' + " · ".join(
            self.code_ref_link(ref) for ref in refs
        ) + "</div>"

    def declaration_rows(self, declarations: list[dict], executed: str) -> str:
        implementing = [item for item in declarations if item["status"] != "host_scope"]
        delegations = [item for item in declarations if item["status"] == "host_scope"]
        shown = implementing if implementing else delegations
        grouped: dict[tuple, list[dict]] = {}
        for declaration in shown:
            key = (
                declaration["gem"], declaration["article"], declaration["status"],
                str(declaration.get("how") or ""), str(declaration.get("gaps") or ""),
            )
            grouped.setdefault(key, []).append(declaration)
        rows = []
        for (gem_name, article, status, how, gaps), group in grouped.items():
            label, css = STATUS_META.get(status, (status, "none"))
            gap_html = "" if not gaps else f'<div class="gaps"><b>Gaps:</b> {esc(gaps)}</div>'
            rows.append(
                "<tr>\n"
                f'  <td class="ref">{esc(article)}</td>\n'
                f"  <td>{esc(gem_name)}</td>\n"
                f'  <td><span class="pill {css}">{esc(label)}</span> {executed}</td>\n'
                f'  <td class="how">{esc(how)}{gap_html}{self.code_cell(group[0])}</td>\n'
                "</tr>\n"
            )
        owner_heading = "Python domain" if self.inputs.input_mode == PYTHON_INPUT_MODE else "Gem"
        table = (
            f'<table class="inner"><thead><tr><th>Declared at</th><th>{owner_heading}</th><th>Status</th>'
            f'<th>How / gaps · code</th></tr></thead><tbody>{"".join(rows)}</tbody></table>'
        )
        if implementing and delegations:
            note = ", ".join(sorted({item["gem"] for item in delegations}))
            plural = "" if len(implementing) == 1 else "s"
            table += (
                '<div class="dim delegnote">Also declared <code>host_scope</code> by '
                f"{esc(note)} — runtime bookkeeping so a partial-composition run still names the "
                f"owner; reconciled against the row{plural} above.</div>"
            )
        return table

    def citation_cell(self, citations: list[dict]) -> str:
        if not citations:
            return ""
        links = [self.link(citation) for citation in citations[:8]]
        if len(citations) > 8:
            links.append(f'<span class="dim">+{len(citations) - 8} more</span>')
        return (
            '<div class="citerow"><b>Cited at</b> <span class="dim">'
            "(a citation proves a log line mentions the\n"
            "article — it is not, by itself, evidence the rule is applied):</span> "
            + " · ".join(links) + "</div>\n"
        )

    def disposition_block(self, disposition: dict, conflict: bool) -> str:
        label, css = DISPOSITION_META.get(
            disposition["category"], (disposition["category"], "none")
        )
        covered_by = disposition.get("covered_by") or []
        covered_by = covered_by if isinstance(covered_by, list) else [covered_by]
        target = ", ".join(str(value) for value in covered_by)
        conflict_text = (
            '<span class="pill bad">⚑ CONFLICT</span> this article is dispositioned AND '
            "declared/cited — resolve, do not trust either alone."
            if conflict else ""
        )
        target_text = "" if not target else f": {esc(target)}"
        draft = (
            '<span class="pill warn" title="not yet reviewed by a human">DRAFT</span>'
            if disposition.get("draft") else ""
        )
        reviewer = str(disposition["reviewer"])
        return (
            f'<div class="dispo{" conflict" if conflict else ""}">\n'
            f"  {conflict_text}\n"
            f'  <span class="pill {css}">{esc(label)}{target_text}</span>\n'
            f"  {draft}\n"
            f'  <span class="how">{esc(disposition["rationale"])}</span>\n'
            f'  <div class="dim">Reviewer: {esc(reviewer)}</div>\n'
            "</div>\n"
        )

    def clause_tree(self, record: dict, declarations: list[dict]) -> str:
        if not record["parse_ok"]:
            return (
                f'<details><summary>Requirement text — <b>structure unverified</b> '
                f'({esc(record["reason"])})</summary>\n'
                '<p class="dim">The parser could not verify this article\'s sentence structure, '
                "so the raw text is shown\n"
                "rather than a guessed tree (text under a wrong number is worse than no tree)."
                f"</p>\n<pre>{esc(record['raw'])}</pre></details>\n"
            )
        by_sentence: dict[int | None, list[dict]] = defaultdict(list)
        for declaration in declarations:
            by_sentence[declaration["sentence"]].append(declaration)
        if any(sentence is not None for sentence in by_sentence):
            depth_note = "coverage below is declared per-sentence where marked"
        elif declarations:
            depth_note = "coverage is declared at ARTICLE level — per-sentence marks would be fabrication"
        else:
            depth_note = "no coverage declared at any depth"

        items = []
        for sentence in record["sentences"]:
            groups: dict[tuple, list[dict]] = {}
            for declaration in by_sentence.get(sentence["num"], []):
                code = declaration.get("code") or []
                code = tuple(code if isinstance(code, list) else [code])
                key = (
                    declaration["gem"], declaration["status"],
                    str(declaration.get("how") or ""), code,
                )
                groups.setdefault(key, []).append(declaration)
            marks = []
            for group in groups.values():
                declaration = group[0]
                vintages = ", ".join(sorted({item["vintage"] for item in group}))
                label, css = STATUS_META.get(
                    declaration["status"], (declaration["status"], "none")
                )
                code = declaration.get("code") or []
                code = code if isinstance(code, list) else [code]
                code_html = " · ".join(self.code_ref_link(ref) for ref in code)
                pill = (
                    f'<span class="pill {css}" title="{esc(declaration["gem"])} '
                    f'({esc(vintages)}): {esc(str(declaration.get("how") or "")[:160])}">'
                    f'{esc(declaration["gem"])}: {esc(label)}</span>'
                )
                marks.append(pill if not code_html else f'{pill} <span class="dim">[{code_html}]</span>')
            clauses = []
            for clause in sentence["clauses"]:
                subs = "".join(
                    f'<li class="sub"><span class="cid">({esc(sub["id"])})</span> '
                    f'{esc(sub["text"])}</li>' for sub in clause["subclauses"]
                )
                sublist = "" if not subs else f"<ul>{subs}</ul>"
                clauses.append(
                    f'<li><span class="cid">({esc(clause["id"])})</span> '
                    f'{esc(clause["text"])}{sublist}</li>'
                )
            clause_list = "" if not clauses else f'<ul>{"".join(clauses)}</ul>'
            items.append(
                f'<li><span class="cid">({sentence["num"]})</span> {esc(sentence["text"])} '
                f'{" ".join(marks)}{clause_list}</li>'
            )
        equations = (record.get("equations") or [])[:6]
        equation_html = ""
        if equations:
            equation_html = (
                '<div class="eqs"><b>Formulas (reference rendering):</b><pre>'
                f'{esc(chr(10).join(chr(10).join((equation, "")) for equation in equations).rstrip())}'
                "</pre></div>"
            )
        return (
            f'<details><summary>Requirement text ({len(record["sentences"])} sentences) — '
            f'<span class="dim">{depth_note}</span></summary>\n'
            f'<ul class="clauses">{"".join(items)}</ul>{equation_html}</details>\n'
        )

    def vintage_part(self, vintage: str) -> dict:
        articles = json.loads(self.inputs.caches[vintage].read_text(encoding="utf-8"))["articles"]
        outside = [key for key in articles if not key.startswith("8.4.")]
        if outside:
            raise ValueError(
                f"LINT: non-8.4 content in the {vintage} text cache: {', '.join(outside)}"
            )
        declarations = self.declarations_for(vintage)
        citations = self.citations_for(vintage, articles)
        executed = self.executed_for(vintage)
        dispositions = self.dispositions_for(vintage, articles)
        states, conflicts = self.states_for(articles, declarations, citations, dispositions)
        counts = Counter(states.values())
        total = sum(counts.values())
        if total != len(articles):
            raise ValueError(
                f"SELF-CHECK FAILED ({vintage}): states sum to {total}, not {len(articles)}"
            )

        sections = []
        for prefix, subsection_title in SUBSECTIONS[vintage].items():
            rows = []
            matching = sorted(
                (article for article in articles if article.startswith(prefix + ".")),
                key=article_sort_key,
            )
            for article in matching:
                record = articles[article]
                declared = declarations[article]
                state = states[article]
                label, css = STATE_META[state]
                conflict = article in conflicts
                executed_badge = self.executed_badge(executed[article])
                body = ""
                if declared:
                    body += self.declaration_rows(declared, executed_badge)
                elif state == "cited":
                    body += (
                        '<div class="dispo"><span class="pill warn">cited in code, not declared'
                        '</span> <span class="how">No\n'
                        "  manifest entry exists, but source citations reference this article (see below). "
                        "This is a manifest\n"
                        "  gap to close — it is NOT a claim of implementation.</span> "
                        f"{executed_badge}</div>"
                    )
                elif state == "unknown":
                    body += (
                        '<div class="dispo"><span class="pill bad">unknown</span> '
                        '<span class="how">No declaration, no\n'
                        "  citation, no disposition. Nothing is known about how this article is "
                        "satisfied.</span></div>"
                    )
                if article in dispositions:
                    body += self.disposition_block(dispositions[article], conflict)
                body += self.citation_cell(citations[article])
                body += self.clause_tree(record, declared)
                title = record["title"] or "(untitled)"
                pages = "–".join(str(page) for page in (record.get("pages") or []))
                conflict_marker = ' <span class="pill bad">⚑</span>' if conflict else ""
                rows.append(
                    f'<tr class="article" id="v{vintage}-a{article.replace(".", "-")}">\n'
                    f'  <td class="ref">{esc(article)}.</td>\n'
                    f'  <td><b>{esc(title)}</b>\n'
                    f'      <span class="pill {css}">{label}</span>'
                    f"{conflict_marker}\n"
                    f'      <span class="dim">pp. {pages}</span></td>\n'
                    "</tr>\n"
                    f'<tr class="nested"><td colspan="2">{body}</td></tr>\n'
                )
            sections.append(
                f"<section><h2>{esc(prefix)}. {esc(subsection_title)}</h2>\n"
                f'<table class="outer"><tbody>{"".join(rows)}</tbody></table></section>\n'
            )

        cards = "".join(
            f'<div class="card {css}"><b>{counts.get(state, 0)}</b><span>{label}</span></div>'
            for state, (label, css) in STATE_META.items()
        )
        cards += f'<div class="card bad"><b>{len(conflicts)}</b><span>⚑ Conflicts</span></div>'
        html = (
            f'<details class="vintage-part" open id="v{vintage}">\n'
            f'<summary><b>NECB {vintage}</b> — {len(articles)} articles '
            '<span class="dim">(click to collapse)</span></summary>\n'
            f'<div class="cards">{cards}</div>\n'
            f'<div class="scroll">{"".join(sections)}</div>\n'
            "</details>\n"
        )
        return {
            "articles": articles,
            "counts": counts,
            "conflicts": conflicts,
            "states": states,
            "declarations": declarations,
            "citations": citations,
            "html": html,
        }

    def render(self) -> tuple[str, dict[str, dict]]:
        parts = {vintage: self.vintage_part(vintage) for vintage in ("2020", "2025")}
        if not self.inputs.audit_dirs:
            run_note = (
                'No run evidence supplied (set NECB_AUDIT_JSONS to one or more run directories '
                'containing audit.json + report.json) — the "observed in run" tier is absent from '
                "this build."
            )
        else:
            names = ", ".join(path.name for path in self.inputs.audit_dirs)
            run_note = (
                f'Run evidence: {names} — articles cited at runtime in those runs carry an '
                '"observed in run" badge (the strongest evidence tier here: it proves the citing '
                "code executed in at least one real scenario)."
            )
        retrieved_2020 = json.loads(
            self.inputs.cache_2020.read_text(encoding="utf-8")
        )["provenance"]["retrieved"]
        retrieved_2025 = json.loads(
            self.inputs.cache_2025.read_text(encoding="utf-8")
        )["provenance"]["retrieved"]
        html = HTML_TEMPLATE.format(
            run_note=esc(run_note),
            count_2020=len(parts["2020"]["articles"]),
            count_2025=len(parts["2025"]["articles"]),
            part_2020=parts["2020"]["html"],
            part_2025=parts["2025"]["html"],
            retrieved_2020=esc(retrieved_2020),
            retrieved_2025=esc(retrieved_2025),
            branch=esc(self.inputs.branch),
            repo=esc(REPO_URL),
        )
        return html, parts


HTML_TEMPLATE = """  <!-- Generated by python/scripts/generate_necb_8_4_coverage.py — do not
    edit by hand; `python3 python/scripts/generate_necb_8_4_coverage.py` regenerates. (A comment before
       the doctype is legal HTML5 and does not trigger quirks mode.) -->
  <!doctype html>
  <html lang="en"><head><meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>NECB Section 8.4 — Performance Path coverage</title>
  <style>
    :root {{ color-scheme: light dark;
      --bg:#fff; --fg:#1a1a1a; --dim:#666; --line:#e3e3e3; --panel:#fafafa;
      --ok:#1a7f37; --warn:#9a6700; --bad:#b32424; --clone:#0969da; --host:#6639ba; --none:#767676; }}
    @media (prefers-color-scheme: dark) {{ :root {{
      --bg:#0d1117; --fg:#e6edf3; --dim:#9198a1; --line:#30363d; --panel:#161b22;
      --ok:#3fb950; --warn:#d29922; --bad:#f85149; --clone:#58a6ff; --host:#bc8cff; --none:#8b949e; }} }}
    :root[data-theme="dark"] {{ --bg:#0d1117; --fg:#e6edf3; --dim:#9198a1; --line:#30363d; --panel:#161b22;
      --ok:#3fb950; --warn:#d29922; --bad:#f85149; --clone:#58a6ff; --host:#bc8cff; --none:#8b949e; }}
    :root[data-theme="light"] {{ --bg:#fff; --fg:#1a1a1a; --dim:#666; --line:#e3e3e3; --panel:#fafafa;
      --ok:#1a7f37; --warn:#9a6700; --bad:#b32424; --clone:#0969da; --host:#6639ba; --none:#767676; }}
    body {{ background:var(--bg); color:var(--fg); margin:0 auto; padding:2rem 1.25rem; max-width:76rem;
      font:15px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",Helvetica,Arial,sans-serif; }}
    h1 {{ font-size:1.55rem; margin:0 0 .3rem; }} h2 {{ font-size:1.12rem; margin:2rem 0 .5rem; }}
    .lede {{ color:var(--dim); max-width:58rem; }}
    .caveat {{ border-left:3px solid var(--warn); background:var(--panel); padding:.8rem 1rem; margin:1.1rem 0; border-radius:0 4px 4px 0; }}
    .cards {{ display:flex; flex-wrap:wrap; gap:.5rem; margin:1.1rem 0; }}
    .card {{ border:1px solid var(--line); border-radius:6px; padding:.5rem .85rem; background:var(--panel); min-width:8rem; }}
    .card b {{ display:block; font-size:1.3rem; }} .card span {{ color:var(--dim); font-size:.78rem; }}
    .card.ok b{{color:var(--ok)}} .card.warn b{{color:var(--warn)}} .card.bad b{{color:var(--bad)}} .card.host b{{color:var(--host)}}
    .scroll {{ overflow-x:auto; }}
    table {{ border-collapse:collapse; width:100%; }}
    tr.article > td {{ border-top:1px solid var(--line); padding:.55rem .5rem; background:var(--panel); vertical-align:top; }}
    tr.nested > td {{ padding:.15rem 0 .8rem 1.4rem; border:0; }}
    table.inner {{ font-size:.87rem; margin:.3rem 0; }}
    table.inner th {{ text-align:left; font-weight:500; font-size:.72rem; text-transform:uppercase; color:var(--dim);
      padding:.25rem .5rem; border-bottom:1px solid var(--line); }}
    table.inner td {{ padding:.4rem .5rem; border-bottom:1px solid var(--line); vertical-align:top; }}
    .ref {{ font-family:ui-monospace,SFMono-Regular,Menlo,monospace; white-space:nowrap; }}
    .orig {{ color:var(--dim); font-size:.72rem; }}
    .dim {{ color:var(--dim); font-size:.82em; }}
    .how {{ max-width:44rem; display:inline; }} .gaps {{ margin-top:.3rem; color:var(--warn); }}
    .pill {{ display:inline-block; padding:.05rem .5rem; border-radius:10px; font-size:.74rem; white-space:nowrap; border:1px solid currentColor; }}
    .pill.ok{{color:var(--ok)}} .pill.warn{{color:var(--warn)}} .pill.bad{{color:var(--bad)}}
    .pill.clone{{color:var(--clone)}} .pill.host{{color:var(--host)}} .pill.none{{color:var(--none)}}
    .citerow {{ font-size:.83rem; margin:.35rem 0; }}
    .citerow a {{ color:var(--clone); text-decoration:none; font-family:ui-monospace,SFMono-Regular,Menlo,monospace; font-size:.9em; }}
    .citerow a:hover {{ text-decoration:underline; }}
    .dispo {{ font-size:.87rem; margin:.35rem 0; padding:.45rem .6rem; background:var(--panel); border:1px solid var(--line); border-radius:5px; }}
    .dispo.conflict {{ border-color:var(--bad); }}
    details {{ margin:.4rem 0; font-size:.88rem; }}
    summary {{ cursor:pointer; color:var(--dim); }}
    ul.clauses {{ margin:.5rem 0 .3rem; padding-left:1.2rem; list-style:none; }}
    ul.clauses ul {{ list-style:none; padding-left:1.4rem; }}
    ul.clauses li {{ margin:.3rem 0; }}
    .cid {{ font-family:ui-monospace,SFMono-Regular,Menlo,monospace; color:var(--host); }}
    .eqs pre, details pre {{ background:var(--panel); border:1px solid var(--line); border-radius:5px;
      padding:.6rem; overflow-x:auto; font-size:.8rem; white-space:pre-wrap; }}
    footer {{ margin-top:2.5rem; padding-top:1rem; border-top:1px solid var(--line); color:var(--dim); font-size:.82rem; }}
    code {{ font-family:ui-monospace,SFMono-Regular,Menlo,monospace; font-size:.9em; }}
    .coderefs {{ margin-top:.25rem; font-size:.8rem; }}
    .coderefs a {{ color:var(--clone); text-decoration:none; font-family:ui-monospace,SFMono-Regular,Menlo,monospace; }}
    .coderefs a:hover {{ text-decoration:underline; }}
    .delegnote {{ margin:.2rem 0 .4rem; font-size:.78rem; }}
    details.vintage-part {{ margin:1.4rem 0; border:1px solid var(--line); border-radius:8px; padding:.2rem .9rem .6rem; }}
    details.vintage-part > summary {{ cursor:pointer; font-size:1.25rem; padding:.55rem 0; color:var(--fg); }}
    details.vintage-part[open] > summary {{ border-bottom:1px solid var(--line); margin-bottom:.6rem; }}
</style></head><body>

  <h1>NECB Section 8.4 — Performance Path coverage</h1>
    <p class="lede">How the Python <code>btap</code> package covers Section 8.4 of the National Energy Code of
  Canada for Buildings — one collapsible part per edition, each walking its own subsections under its own
  article numbers. Every article of both editions renders with its full requirement text, so coverage cannot
  be overstated by omission. {run_note}</p>

  <div class="caveat"><b>How to read the evidence — weakest to strongest.</b>
  <ul>
    <li><b>Disposition</b> — a curated claim of <i>responsibility</i> (engine / modeller / named Python domain / gap), not
        of correctness. Draft dispositions are unreviewed.</li>
    <li><b>"Cited at" links</b> — the article number appears on an audit log call in that source line. A citation
        proves the log line exists, <em>nothing more</em>; citations sitting on <em>warnings</em> often announce
        the rule is <em>not</em> applied and are badged accordingly. Absence of a citation is not evidence of
        non-implementation either.</li>
    <li><b>Manifest status</b> — the Python domain's self-declared <code>article_coverage</code>. "Implemented" here means
        the Python domain <i>asserts</i> it applies the rule; two real defects have been found inside articles declared
        implemented. Independent behavioural verification is <code>rake necb:verify</code>
        (see <code>docs/necb_rule_verification.md</code>).</li>
    <li><b>"Observed in run"</b> — the article was cited at runtime in a named real pipeline run: the citing code
        demonstrably executed in at least one scenario. Still not proof of correct values.</li>
  </ul>
    <b>Prescriptive values</b> (U-values, LPDs, efficiencies) are governed by the Python package's data JSON — the number
    the software actually applies and the thing to audit: <code>python/btap/necb/envelope/data/envelope_rules_*.json</code>,
    <code>python/btap/necb/loads/data/space_types_*.json</code>, <code>python/btap/necb/shw/data/shw_rules_*.json</code>,
    <code>python/btap/necb/hvac/data/efficiencies_*.json</code>. The official code wording is available through the
  building-codes MCP (<code>get_section</code>/<code>get_table</code>) as a human reference only.</div>

  <p class="lede"><b>Jump to:</b> <a href="#v2020">NECB 2020</a> ({count_2020} articles,
  8.4.1–8.4.5) · <a href="#v2025">NECB 2025</a> ({count_2025} articles, 8.4.1–8.4.6).
  Each edition is a collapsible part in its OWN article numbering — 2020's 8.4.4 is the reference building
  where 2025's 8.4.4 is the EUI path, so nothing is renumbered across editions here.</p>

  {part_2020}
  {part_2025}

    <footer>Generated by <code>python/scripts/generate_necb_8_4_coverage.py</code> — do not edit by hand
    (<code>python3 python/scripts/generate_necb_8_4_coverage.py</code> to regenerate).
  Requirement text: NECB 2020 and 2025 Division B via the building-codes MCP
  (2020 retrieved {retrieved_2020},
  2025 retrieved {retrieved_2025})
  (Crown copyright — reproduction authorized as Government of Canada work); parse safety checks in
  <code>python/scripts/fetch_necb_8_4_text.py</code>. Source links resolve against <code>{branch}</code> of {repo}.</footer>
  </body></html>
"""


def generate(inputs: Inputs, output: Path) -> tuple[CoverageGenerator, dict[str, dict]]:
    generator = CoverageGenerator(inputs)
    html, parts = generator.render()
    output.write_text(html, encoding="utf-8")
    return generator, parts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input-mode",
        choices=[PYTHON_INPUT_MODE],
        default=DEFAULT_INPUT_MODE,
    )
    parser.add_argument("--source-root", type=Path, default=REPO_ROOT)
    parser.add_argument("--manifest-root", type=Path, default=REPO_ROOT)
    parser.add_argument("--cache-2020", type=Path, default=DEFAULT_CACHE_2020)
    parser.add_argument("--cache-2025", type=Path, default=DEFAULT_CACHE_2025)
    parser.add_argument("--disposition", type=Path, default=DEFAULT_DISPOSITION)
    parser.add_argument("--audit-dir", action="append", type=Path, default=None)
    parser.add_argument("--branch", default=os.environ.get("COVERAGE_BRANCH", "main").strip())
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)
    audit_dirs = args.audit_dir
    if audit_dirs is None:
        audit_dirs = [Path(value.strip()) for value in os.environ.get(
            "NECB_AUDIT_JSONS", ""
        ).split(":") if value.strip()]
    inputs = Inputs(
        source_root=args.source_root,
        manifest_root=args.manifest_root,
        cache_2020=args.cache_2020,
        cache_2025=args.cache_2025,
        disposition=args.disposition,
        audit_dirs=tuple(audit_dirs),
        branch=args.branch,
        input_mode=args.input_mode,
    )
    _generator, parts = generate(inputs, args.output)
    print(f"wrote {args.output.relative_to(REPO_ROOT) if args.output.is_relative_to(REPO_ROOT) else args.output}")
    for vintage, part in parts.items():
        counts = " ".join(f"{key}={value}" for key, value in part["counts"].items())
        conflicts = ", ".join(part["conflicts"])
        print(
            f"  {vintage}: {counts}  (sum {sum(part['counts'].values())}/"
            f"{len(part['articles'])})  conflicts: {conflicts}"
        )
        parse_failures = [
            article for article, record in part["articles"].items() if not record["parse_ok"]
        ]
        print(
            f"  {vintage} clause-tree fallbacks: "
            f"{', '.join(parse_failures) if parse_failures else 'none'}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())