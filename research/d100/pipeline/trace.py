#!/usr/bin/env python3
"""Stage 3 — trace every ``ruling=`` site toward a public entry point.

Reports candidate call chains and the guards on the path to each site. It does
NOT decide reachability, and it does not infer it from a file's directory: a
shared module can branch on ruleset data, so directory placement is not
evidence (Sol, `058`, `061` item 5).

Sites with no corroborated chain are marked `unresolved`, never assigned every
code id by default. `manifest_bound_entry` records whether a chain reaches a
function the manifests actually bind; anything beyond that -- the per-code
chain from each manifest binding, with edition guards -- is human work and the
packet says so.
"""

from __future__ import annotations

import ast
import re
from collections import defaultdict
from pathlib import Path

from common import (DECISION_ID_RE, PYTHON_ROOT, out_dir, read_json, write_json)

BTAP = PYTHON_ROOT / "btap"
AUDIT_METHODS = frozenset({"decision", "info", "warn"})
#: What the manifests bind as the code path, and the public API above it.
ENTRY_MARKERS = ("codes/necb/path.py", "codes/pipeline.py", "codes/compliance.py")
MAX_DEPTH = 7


def modules():
    for path in sorted(BTAP.rglob("*.py")):
        yield path, ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def spans_of(tree):
    return sorted(((n.name, n.lineno, n.end_lineno, n)
                   for n in ast.walk(tree)
                   if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))),
                  key=lambda s: (s[1], -s[2]))


def enclosing(spans, line):
    best = None
    for name, start, end, node in spans:
        if start <= line <= end and (best is None or start >= best[1]):
            best = (name, start, end, node)
    return best


def import_graph():
    """``{module: {modules it can reach}}``. A package import reaches its
    submodules, because attribute access on a package is how `path.py` calls
    `envelope.reference._apply`."""
    known = {str(p.relative_to(PYTHON_ROOT)) for p in BTAP.rglob("*.py")}
    graph = {}
    for path, tree in modules():
        rel = str(path.relative_to(PYTHON_ROOT))
        targets = set()
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module] + [f"{node.module}.{a.name}" for a in node.names]
            for name in names:
                if not name.startswith("btap"):
                    continue
                as_path = name.replace(".", "/")
                targets.update(c for c in (f"{as_path}.py", f"{as_path}/__init__.py")
                               if c in known)
                targets.update(m for m in known if m.startswith(as_path + "/"))
        graph[rel] = targets
    return graph


def call_index():
    calls = defaultdict(set)
    for path, tree in modules():
        rel = str(path.relative_to(PYTHON_ROOT))
        spans = spans_of(tree)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            callee = (node.func.attr if isinstance(node.func, ast.Attribute)
                      else getattr(node.func, "id", None))
            site = enclosing(spans, node.lineno)
            if callee and site:
                calls[callee].add((rel, site[0], ast.unparse(node.func)[:80],
                                   node.lineno))
    return calls


def ruling_sites():
    found = []
    for path, tree in modules():
        rel = str(path.relative_to(PYTHON_ROOT))
        spans = spans_of(tree)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            method = (node.func.attr if isinstance(node.func, ast.Attribute)
                      else getattr(node.func, "id", None))
            if method not in AUDIT_METHODS:
                continue
            for keyword in node.keywords:
                if keyword.arg != "ruling":
                    continue
                value = keyword.value
                if not (isinstance(value, ast.Constant)
                        and isinstance(value.value, str)):
                    continue
                encl = enclosing(spans, value.lineno)
                guards = sorted({(inner.lineno, ast.unparse(inner.test)[:120])
                                 for inner in ast.walk(encl[3])
                                 if isinstance(inner, ast.If)
                                 and inner.lineno <= value.lineno
                                 <= (inner.end_lineno or inner.lineno)}) if encl else []
                for decision_id in DECISION_ID_RE.findall(value.value):
                    found.append({"id": decision_id, "module": rel,
                                  "line": value.lineno,
                                  "function": encl[0] if encl else "(module level)",
                                  "guards": guards})
    return found


def chains(calls, graph, module, func):
    """Corroborated upward chains. A dotted expression naming a different
    module rejects the edge, so `envelope.reference._apply` cannot be confused
    with another module's `_apply`."""
    out = []

    def walk(mod, name, chain, visited):
        if len(chain) > MAX_DEPTH or len(out) > 500:
            out.append(chain)
            return
        extended = False
        for caller_mod, caller_func, expr, call_line in sorted(calls.get(name, ())):
            if (caller_mod, caller_func) in visited:
                continue
            if caller_mod != mod and mod not in graph.get(caller_mod, ()):
                continue
            if "." in expr:
                named = expr.rsplit(".", 2)[0].split(".")[-1]
                if named and named not in mod and named not in ("self", "cls"):
                    continue
            extended = True
            walk(caller_mod, caller_func,
                 chain + [f"{caller_mod}:{call_line}::{caller_func} [{expr}]"],
                 visited | {(caller_mod, caller_func)})
        if not extended:
            out.append(chain)

    walk(module, func, [f"{module}::{func}"], {(module, func)})
    return out


def main(argv=None):
    out = out_dir(argv, __doc__)
    calls, graph = call_index(), import_graph()
    sites = ruling_sites()
    by_id = defaultdict(list)
    for site in sites:
        found = chains(calls, graph, site["module"], site["function"])
        entry = [c for c in found
                 if any(marker in step for step in c for marker in ENTRY_MARKERS)]
        # UNVERIFIED candidates, named as such. A name-only call index produced
        # a provably invalid chain -- `path.py` calls `reference._apply`, which
        # then calls `Prescriptive._apply`, and both modules define `_apply` --
        # and a qualified-symbol check still validated only the top of an edge.
        # Sol ruled against building a general resolver: these are candidates,
        # the global corroborated count is UNRESOLVED, and an accepted packet
        # must carry a human-verified per-code chain from the manifest binding
        # through the lifecycle hook and guards (Sol, `065` item 4, `068`).
        site["unverified_candidate_chains"] = [" <- ".join(c) for c in entry][:4]
        site["chain_corroborated"] = None          # unresolved, not False
        site["per_code_chain"] = None              # human work, never inferred
        site["requires_human_resolution"] = True   # every site, without exception
        by_id[site["id"]].append(site)

    write_json(out / "traces.json", dict(sorted(by_id.items())))
    with_candidate = sum(1 for s in sites if s["unverified_candidate_chains"])
    print(f"ruling sites: {len(sites)} across {len(by_id)} decisions")
    print(f"  with at least one UNVERIFIED candidate chain : {with_candidate}")
    print(f"  with no candidate chain at all               : "
          f"{len(sites) - with_candidate}")
    print(f"  carrying at least one guard                  : "
          f"{sum(1 for s in sites if s['guards'])}")
    print("  corroborated chains                          : UNRESOLVED")
    print("  Every site requires human resolution. A candidate chain is a "
          "starting point for reading, not evidence of reachability: a shared "
          "module or a same-named function is not proof, and no count here is "
          "a corroborated count (Sol, 068).")
    print(f"written: {out / 'traces.json'}")


if __name__ == "__main__":
    main()
