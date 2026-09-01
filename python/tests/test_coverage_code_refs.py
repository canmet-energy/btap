"""Keep article-coverage code pointers attached to real Python definitions."""

from __future__ import annotations

import ast
import json
import re
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
MAPPING_PATH = Path(__file__).with_name("data") / "coverage_code_ref_mapping.json"
SIZING_TIME = re.compile(
    r"sizing[- ]time|autosiz|not explicitly enforced|not individually evaluated",
    re.IGNORECASE,
)


def coverage_manifests():
    manifests = []
    for path in sorted((REPO_ROOT / "python" / "btap").glob("**/*_rules_*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        articles = data.get("article_coverage", {}).get("articles")
        if articles is not None:
            manifests.append((path.relative_to(REPO_ROOT), articles))
    return manifests


def code_refs(manifests):
    return [
        ref
        for _manifest, articles in manifests
        for article in articles
        for ref in article.get("code", [])
    ]


def definitions(path):
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }


def test_manifest_inventory_and_every_code_ref_resolves():
    manifests = coverage_manifests()
    assert len(manifests) == 12
    assert sum(len(articles) for _path, articles in manifests) == 241

    refs = code_refs(manifests)
    assert len(refs) > 60
    assert len(refs) == 313
    assert all(not re.match(r"^btap-[^/]+/lib/", ref) for ref in refs)

    definitions_by_path = {}
    for manifest, articles in manifests:
        for article in articles:
            for ref in article.get("code", []):
                path_text, separator, symbol = ref.partition("#")
                assert separator and symbol, f"{manifest} {article['article']}: invalid ref {ref}"
                path = REPO_ROOT / path_text
                assert path.is_file(), f"{manifest} {article['article']}: no such file {path_text}"
                definitions_by_path.setdefault(path, definitions(path))
                assert symbol in definitions_by_path[path], (
                    f"{manifest} {article['article']}: {path_text} does not define #{symbol}"
                )


def test_every_covering_entry_names_its_code():
    for manifest, articles in coverage_manifests():
        for article in articles:
            if article.get("gap_owner") == "modeller":
                continue

            status = article.get("status")
            if status in {"implemented", "satisfied_by_clone"}:
                needed = True
            elif status == "host_scope":
                needed = not re.search(
                    r"modeller", f"{article.get('how', '')} {article.get('gaps', '')}", re.I
                )
            elif status == "partial":
                needed = not SIZING_TIME.search(str(article.get("gaps", "")))
            else:
                needed = False

            assert not needed or article.get("code"), (
                f"{manifest} {article['article']} ({status}): must name the code where "
                "this is dealt with"
            )


def test_reviewed_mapping_was_consumed_without_unknown_old_refs():
    mapping = json.loads(MAPPING_PATH.read_text(encoding="utf-8"))
    rows = mapping["mappings"]
    assert mapping["source_checkpoint"] == "cbce093"
    assert len(rows) == 87
    assert sum(row["uses"] for row in rows) == 313

    old_refs = [row["old"] for row in rows]
    new_refs = [row["new"] for row in rows]
    assert len(set(old_refs)) == len(old_refs)
    assert len(set(new_refs)) == len(new_refs)

    actual = Counter(code_refs(coverage_manifests()))
    expected = Counter({row["new"]: row["uses"] for row in rows})
    assert actual == expected
    assert not set(actual).intersection(old_refs)
    assert not {
        ref for ref in actual if re.match(r"^btap-[^/]+/lib/", ref)
    }.difference(old_refs)