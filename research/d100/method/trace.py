#!/usr/bin/env python3
"""Trace each ``ruling=`` site back to the manifest-bound entry points.

Sol's `058`: "the module is shared" is evidence, not proof — a shared module
can branch on ruleset data. This builds the chain he asked for,

    manifest path binding -> lifecycle hook -> function -> ruling site

statically, by finding the function enclosing each site and then walking
callers upward across ``btap``. It reports the chain and, separately, every
guard on the path from the enclosing function's body down to the site, so the
guards can be read rather than assumed. It does NOT decide reachability; it
produces the evidence a human reads.
"""

from __future__ import annotations

import ast
import json
import re
from collections import defaultdict
from pathlib import Path

PYTHON_ROOT = Path("/workspaces/openstudio-necb-gems/python")
BTAP = PYTHON_ROOT / "btap"
ID_TOKEN = re.compile(r"\bD-\d{2}\b")
AUDIT_METHODS = frozenset({"decision", "info", "warn"})


def modules():
    for path in sorted(BTAP.rglob("*.py")):
        yield path, ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def function_spans(tree):
    """[(name, start, end, node)] for every def/async def, innermost last."""
    spans = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            spans.append((node.name, node.lineno, node.end_lineno, node))
    return sorted(spans, key=lambda s: (s[1], -s[2]))


def enclosing(spans, line):
    best = None
    for name, start, end, node in spans:
        if start <= line <= end and (best is None or start >= best[1]):
            best = (name, start, end, node)
    return best


def import_graph():
    """``{module: {module it can reach by import}}``, resolved to file paths.

    Function names alone over-connect: every ``_apply`` in the tree looks like
    a caller of every other. A chain step is only corroborated when the caller
    module actually imports the callee's module.
    """
    graph = {}
    known = {str(p.relative_to(PYTHON_ROOT)) for p in BTAP.rglob("*.py")}
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
                for candidate in (f"{as_path}.py", f"{as_path}/__init__.py"):
                    if candidate in known:
                        targets.add(candidate)
                # Importing a PACKAGE reaches its submodules by attribute:
                # `path.py` does `from ... import envelope` then calls
                # `envelope.reference._apply(...)`. Without this the chain
                # Sol traced by hand was rejected while a false one survived.
                prefix = as_path + "/"
                targets.update(m for m in known if m.startswith(prefix))
        graph[rel] = targets
    return graph


def corroborated(chain, graph):
    """True when every step is same-module or a real import edge."""
    for lower, upper in zip(chain, chain[1:]):
        lower_mod, upper_mod = lower.split("::")[0], upper.split("::")[0]
        if lower_mod == upper_mod:
            continue
        if lower_mod not in graph.get(upper_mod, ()):
            return False
    return True


def build_index():
    """``{module: {func: node}}`` and ``{callee: {(module, caller)}}``."""
    defs, calls = {}, defaultdict(set)
    for path, tree in modules():
        rel = str(path.relative_to(PYTHON_ROOT))
        spans = function_spans(tree)
        defs[rel] = {name: (start, end) for name, start, end, _ in spans}
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            callee = (node.func.attr if isinstance(node.func, ast.Attribute)
                      else getattr(node.func, "id", None))
            if not callee:
                continue
            site = enclosing(spans, node.lineno)
            if site:
                # Keep the DOTTED expression as written. Bare names cannot
                # tell `envelope.reference._apply` from `prescriptive._apply`,
                # and presenting the wrong one as the chain is the error this
                # whole exercise exists to avoid. The reader resolves it by
                # reading the expression at the line given.
                calls[callee].add((rel, site[0], ast.unparse(node.func)[:80],
                                   node.lineno))
    return defs, calls


def sites():
    """[(decision id, module, line, enclosing function, guards)]"""
    found = []
    for path, tree in modules():
        rel = str(path.relative_to(PYTHON_ROOT))
        spans = function_spans(tree)
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
                guards = []
                if encl:
                    for inner in ast.walk(encl[3]):
                        if isinstance(inner, ast.If) and inner.lineno <= value.lineno <= (
                                inner.end_lineno or inner.lineno):
                            guards.append((inner.lineno,
                                           ast.unparse(inner.test)[:120]))
                for decision_id in ID_TOKEN.findall(value.value):
                    found.append({
                        "id": decision_id, "module": rel, "line": value.lineno,
                        "function": encl[0] if encl else "(module level)",
                        "guards": sorted(set(guards)),
                    })
    return found


def callers_of(defs, calls, module, func, graph, depth=7, cap=4000):
    """Upward call chains from ``func`` toward an entry point.

    Cycle detection is PER PATH, not global. A global ``seen`` set pruned a
    valid chain whenever an invalid branch happened to reach the same function
    first -- which silently dropped the very chain Sol traced by hand for
    D-19. Corroboration is applied during the walk so uncorroborated branches
    are abandoned rather than explored.
    """
    chains = []

    def walk(mod, name, chain, visited):
        if len(chains) >= cap:
            return
        if len(chain) > depth:
            chains.append(chain)
            return
        up = sorted(calls.get(name, ()))
        extended = False
        for caller_mod, caller_func, expr, call_line in up:
            if (caller_mod, caller_func) in visited:
                continue
            if caller_mod != mod and mod not in graph.get(caller_mod, ()):
                continue                      # not a real import edge
            # A dotted call names its module: `envelope.reference._apply`
            # can only be reference.py. Reject an edge whose expression names
            # a DIFFERENT module than the one being walked.
            if "." in expr:
                named = expr.rsplit(".", 2)[0].split(".")[-1]
                if named and named not in mod and named not in ("self", "cls"):
                    continue
            extended = True
            walk(caller_mod, caller_func,
                 chain + [f"{caller_mod}:{call_line}::{caller_func} [{expr}]"],
                 visited | {(caller_mod, caller_func)})
        if not extended:
            chains.append(chain)

    walk(module, func, [f"{module}::{func}"], {(module, func)})
    return chains


def main():
    defs, calls = build_index()
    graph = import_graph()
    all_sites = sites()
    by_id = defaultdict(list)
    for site in all_sites:
        chains = callers_of(defs, calls, site["module"], site["function"], graph)
        # keep the chains that reach a plausible entry point
        real = chains          # corroborated during the walk
        entry = [c for c in real
                 if any("codes/necb/path.py" in step or "codes/pipeline.py" in step
                        or "codes/compliance.py" in step for step in c)]
        site["chains_to_entry"] = [" <- ".join(c) for c in entry][:4]
        site["uncorroborated_dropped"] = len(chains) - len(real)
        site["reaches_entry"] = bool(entry)
        by_id[site["id"]].append(site)

    out = Path("/home/vscode/.claude/jobs/a100f076/tmp/traces.json")
    out.write_text(json.dumps(by_id, indent=2, ensure_ascii=False) + "\n",
                   encoding="utf-8")
    traced = sum(1 for s in all_sites if s["reaches_entry"])
    print(f"ruling sites: {len(all_sites)} across {len(by_id)} decisions")
    print(f"  with a static chain to path/pipeline/compliance : {traced}")
    print(f"  without one (need manual tracing)               : {len(all_sites) - traced}")
    print(f"  sites carrying at least one guard               : "
          f"{sum(1 for s in all_sites if s['guards'])}")
    print(f"\nwritten: {out}")


if __name__ == "__main__":
    main()
