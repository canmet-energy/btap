#!/usr/bin/env python3
"""Generate the Python package-wide NECB article-coverage Markdown rollup."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT = REPO_ROOT / "docs" / "NECB_GEM_COVERAGE.md"
PYTHON_INPUT_MODE = "python"
LEGACY_INPUT_MODE = "legacy-ruby"
DEFAULT_INPUT_MODE = PYTHON_INPUT_MODE
MANIFEST_DOMAINS = {"reference": "hvac", "necb": "necb"}
STATUS_GROUPS = (
    ("implemented", "Implemented"),
    ("partial", "Partial (warns every run)"),
    ("not_implemented", "Not implemented (warns every run)"),
    ("satisfied_by_clone", "Satisfied by construction (clone)"),
    ("host_scope", "Host / other-gem scope"),
)
FIELD_VERIFIED_HEADING = "Field / document verification (modeller scope, does not warn)"
VINTAGES = ("2020", "2025")


def manifest_paths(manifest_root: Path, input_mode: str) -> list[Path]:
    if input_mode == PYTHON_INPUT_MODE:
        patterns = ("python/btap/**/*_rules_*.json",)
    elif input_mode == LEGACY_INPUT_MODE:
        patterns = (
            "openstudio-*/lib/**/data/*_rules_*.json",
            "btap-*/lib/**/data/*_rules_*.json",
        )
    else:
        raise ValueError(f"unsupported input mode: {input_mode}")
    return sorted(path for pattern in patterns for path in manifest_root.glob(pattern))


def manifest_domain(path: Path) -> str:
    match = re.match(r"([a-z]+)_rules_", path.name)
    if match is None:
        raise ValueError(f"cannot derive manifest domain from {path}")
    prefix = match.group(1)
    return MANIFEST_DOMAINS.get(prefix, prefix)


def canonical(article: object, vintage: object) -> str:
    value = str(article or "")
    if str(vintage) != "2020":
        return value
    match = re.match(r"8\.4\.([45])\.", value)
    if match is None:
        return value
    return f"8.4.{int(match.group(1)) + 1}." + value[match.end():]


def article_sort_key(article: object) -> list[int]:
    return [int(value) for value in re.findall(r"\d+", str(article))]


def canonicals_match(first: str, second: str) -> bool:
    return first.startswith(second) or second.startswith(first)


def collect_records(manifest_root: Path, input_mode: str = DEFAULT_INPUT_MODE) -> list[dict]:
    manifests = manifest_paths(manifest_root, input_mode)
    if not manifests:
        raise ValueError("no coverage manifests found — the glob went stale")

    records = []
    for path in manifests:
        data = json.loads(path.read_text(encoding="utf-8"))
        coverage = data.get("article_coverage", {}).get("articles")
        if coverage is None:
            continue
        match = re.search(r"(\d{4})\.json$", path.name)
        vintage = match.group(1) if match else data.get("provenance", {}).get("edition", "?")
        domain = manifest_domain(path)
        for article in coverage:
            raw_article = str(article.get("article") or "")
            records.append({
                "gem": domain,
                "vintage": str(vintage),
                "article": raw_article,
                "canonical": canonical(raw_article, vintage),
                "title": str(article.get("title") or ""),
                "status": str(article.get("status") or ""),
                "how": article.get("how"),
                "gaps": article.get("gaps"),
                "gap_owner": article.get("gap_owner"),
                "code": article.get("code"),
            })
    return records


def notes(row: dict) -> str:
    parts = []
    if row["how"]:
        parts.append(row["how"])
    if row["gaps"]:
        parts.append(f"Gaps: {row['gaps']}")
    refs = row["code"] if isinstance(row["code"], list) else [row["code"]]
    refs = [ref for ref in refs if ref is not None]
    if refs:
        parts.append("Code: " + ", ".join(f"`{str(ref).split('/')[-1]}`" for ref in refs))
    return " — ".join(parts).replace("|", "/")


def render(records: list[dict], input_mode: str = DEFAULT_INPUT_MODE) -> str:
    if input_mode == LEGACY_INPUT_MODE:
        generator = "scripts/generate_necb_gem_coverage.rb"
        regenerate = "ruby scripts/generate_necb_gem_coverage.rb"
        title = "NECB coverage across the openstudio-* gem family"
        owner = "gem"
        source_heading = "Gem"
        host_scope_heading = "Host / other-gem scope"
        delegation_heading = "Cross-gem delegations"
        host_scope_text = "delegated to the umbrella or a sibling gem"
        emitter_text = (
            "Each gem emits its section of this accounting into"
        )
        epilogue_text = (
            "is emitted by `Compliance#emit_article_coverage` from the epilogue both"
        )
        delegation_text = "the sibling-gem entry that actually"
    else:
        generator = "python/scripts/generate_necb_gem_coverage.py"
        regenerate = "python3 python/scripts/generate_necb_gem_coverage.py"
        title = "NECB coverage across the Python btap package"
        owner = "Python domain"
        source_heading = "Python domain"
        host_scope_heading = "Host / other-domain scope"
        delegation_heading = "Cross-domain delegations"
        host_scope_text = "delegated to the umbrella or a sibling Python domain"
        emitter_text = "Each Python domain emits its section of this accounting into"
        epilogue_text = (
            "is emitted by `compliance.py#_emit_article_coverage` from the epilogue both"
        )
        delegation_text = "the sibling-domain entry that actually"
    out = [
        f"<!-- Generated by {generator} — do not edit by hand.",
        f"     Regenerate: {regenerate} -->",
        "",
        f"# {title}",
        "",
        f"Rollup of every {owner}'s NECB `article_coverage` manifest, one collapsible",
        "section per vintage, each in that code edition's own article numbering.",
        "Statuses: **implemented** / **partial** (warns every run) /",
        "**not_implemented** (warns every run) / **satisfied_by_clone** /",
        f"**host_scope** ({host_scope_text}); entries with",
        '`gap_owner: "modeller"` are field/document-verified scope notes and do',
        f"not warn (D-09, D-76). {emitter_text}",
        "the shared AuditLog on every run — including the umbrella, whose manifest",
        epilogue_text,
        "compliance paths share — so nothing is silently missed.",
        "",
        "## At a glance",
        "",
        "| | NECB 2020 | NECB 2025 |",
        "|---|---|---|",
    ]

    summary_rows = [
        (host_scope_heading if status == "host_scope" else heading,
         lambda row, status=status: row["status"] == status
         and str(row["gap_owner"] or "") != "modeller")
        for status, heading in STATUS_GROUPS
    ]
    summary_rows.append((
        FIELD_VERIFIED_HEADING,
        lambda row: str(row["gap_owner"] or "") == "modeller",
    ))
    for heading, predicate in summary_rows:
        counts = [sum(row["vintage"] == vintage and predicate(row) for row in records)
                  for vintage in VINTAGES]
        if sum(counts):
            out.append(f"| {heading} | {counts[0]} | {counts[1]} |")
    vintage_counts = [sum(row["vintage"] == vintage for row in records) for vintage in VINTAGES]
    out.extend([
        f"| **Total entries** | **{vintage_counts[0]}** | **{vintage_counts[1]}** |",
        "",
    ])

    for vintage in VINTAGES:
        vintage_rows = [row for row in records if row["vintage"] == vintage]
        out.extend([
            "<details>",
            f"<summary><b>NECB {vintage}</b> — {len(vintage_rows)} entries (click to expand)</summary>",
            "",
        ])
        field_verified = sorted(
            (row for row in vintage_rows if str(row["gap_owner"] or "") == "modeller"),
            key=lambda row: (row["gem"], article_sort_key(row["canonical"])),
        )

        for status, heading in STATUS_GROUPS:
            group = sorted(
                (row for row in vintage_rows
                 if row["status"] == status and str(row["gap_owner"] or "") != "modeller"),
                key=lambda row: (row["gem"], article_sort_key(row["canonical"])),
            )
            if not group:
                continue
            out.extend([
                f"### {heading} ({len(group)})",
                "",
                f"| {source_heading} | Article | Title | Notes |",
                "|---|---|---|---|",
            ])
            out.extend(
                f"| {row['gem']} | {row['article']} | {row['title']} | {notes(row)} |"
                for row in group
            )
            out.append("")

        if field_verified:
            out.extend([
                f"### {FIELD_VERIFIED_HEADING} ({len(field_verified)})",
                "",
                "Requirements the code imposes on the BUILDING that no energy model can",
                "answer — a blower-door test, an installed control device, a pipe",
                "insulation thickness. Declared so a reviewer sees them accounted for;",
                "verified from drawings, submittals or on site.",
                "",
                f"| {source_heading} | Article | Title | Notes |",
                "|---|---|---|---|",
            ])
            out.extend(
                f"| {row['gem']} | {row['article']} | {row['title']} | {notes(row)} |"
                for row in field_verified
            )
            out.append("")

        covering = [row for row in vintage_rows if row["status"] != "host_scope"]
        host = sorted(
            (row for row in vintage_rows if row["status"] == "host_scope"),
            key=lambda row: (row["gem"], article_sort_key(row["canonical"])),
        )
        if host:
            out.extend([
                f"### {delegation_heading} ({len(host)})",
                "",
                f"Each `host_scope` article and {delegation_text}",
                'covers it. "(none in family)" means the umbrella/modeller owns it — a',
                "genuine open item to watch on a real run.",
                "",
                "| host_scope in | Article | Covered by |",
                "|---|---|---|",
            ])
            for delegated in host:
                matches = sorted({
                    f"{row['gem']} {row['article']} ({row['status']})"
                    for row in covering
                    if row["gem"] != delegated["gem"]
                    and canonicals_match(row["canonical"], delegated["canonical"])
                })
                covered = "; ".join(matches) if matches else "(none in family — host/modeller scope)"
                out.append(f"| {delegated['gem']} | {delegated['article']} | {covered} |")
            out.append("")

        out.extend(["</details>", ""])

    domains = len({row["gem"] for row in records})
    out.extend([
        f"_{len(records)} coverage entries across {domains} domains "
        f"({vintage_counts[0]} × 2020, {vintage_counts[1]} × 2025)._",
        "",
    ])
    return "\n".join(out)


def generate(
    manifest_root: Path = REPO_ROOT,
    output: Path = DEFAULT_OUTPUT,
    input_mode: str = DEFAULT_INPUT_MODE,
) -> list[dict]:
    records = collect_records(manifest_root, input_mode=input_mode)
    output.write_text(render(records, input_mode=input_mode), encoding="utf-8")
    return records


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input-mode",
        choices=[PYTHON_INPUT_MODE, LEGACY_INPUT_MODE],
        default=DEFAULT_INPUT_MODE,
    )
    parser.add_argument("--manifest-root", type=Path, default=REPO_ROOT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)
    records = generate(args.manifest_root, args.output, args.input_mode)
    print(f"wrote {args.output.name} — {len(records)} entries in two vintage sections")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())