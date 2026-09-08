"""Stage 5 behaviour-binding gate (docs/NECB_MULTI_EDITION_PLAN.md, Stage 5
"bind edition-specific code through the manifest"): the 2025-only modules
under ``btap/codes/necb/editions/necb2025/`` are reached ONLY through an
edition manifest's ``behaviours`` map, never by importing them by name from
the pipeline.

Three things have to line up, and each is checked here:

1. **the call sites** — every literal a product-code ``.behaviour("…")`` call
   asks for (found by walking the AST of everything under ``python/btap/``,
   not by grep) is bound by at least one manifest on this tree. A call site
   asking for a name no edition implements would silently take the
   "this edition has no such feature" branch forever.
2. **the bindings** — every dotted module name any manifest binds actually
   imports. A binding is a deferred import; without this gate a typo lands in
   a determination, not in CI.
3. **the vocabulary** — ``btap.codes.BEHAVIOURS`` is exactly the union of the
   two: nothing declared that nobody asks for, nothing asked for that nobody
   declares. The vocabulary is deliberately code-side (a one-edition install
   must still answer ``None`` for another edition's behaviour rather than
   crashing), so this test is what keeps it honest against the manifests.

No SDK: everything here is manifests, source text and two stdlib imports.
"""

from __future__ import annotations

import ast
import json
import unittest
from pathlib import Path

import btap.codes as codes
import btap.codes.necb as necb_pkg

PACKAGE_ROOT = Path(codes.__file__).resolve().parents[1]  # python/btap


def _behaviour_names_asked_for() -> dict[str, list[str]]:
    """Every string literal passed to a ``.behaviour(...)`` call under
    ``python/btap/``, mapped to the files that ask for it.

    An AST walk, not a regex: the argument must be a literal to be checked at
    all, and a call spelled ``ruleset.behaviour(name)`` with a variable is a
    finding this gate cannot make (there are none today, and
    :meth:`test_no_dynamic_behaviour_names` keeps it that way).
    """
    asked: dict[str, list[str]] = {}
    for path in sorted(PACKAGE_ROOT.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if not (isinstance(func, ast.Attribute) and func.attr == "behaviour"):
                continue
            if node.args and isinstance(node.args[0], ast.Constant) \
                    and isinstance(node.args[0].value, str):
                asked.setdefault(node.args[0].value, []).append(str(path))
    return asked


def _dynamic_behaviour_calls() -> list[str]:
    """``.behaviour(...)`` calls whose first argument is not a string literal."""
    found = []
    for path in sorted(PACKAGE_ROOT.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if not (isinstance(func, ast.Attribute) and func.attr == "behaviour"):
                continue
            first = node.args[0] if node.args else None
            if not (isinstance(first, ast.Constant) and isinstance(first.value, str)):
                found.append(f"{path}:{node.lineno}")
    return found


def _manifest_behaviours() -> dict[str, dict[str, str]]:
    """``{code id: {behaviour name: dotted module}}`` read off disk."""
    root = necb_pkg._data_root()
    out = {}
    for manifest_path in sorted(root.glob("*/manifest.json")):
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        out[manifest_path.parent.name] = dict(manifest.get("behaviours") or {})
    return out


class BehaviourBindingTests(unittest.TestCase):
    def test_every_call_site_name_is_bound_by_some_manifest(self):
        asked = _behaviour_names_asked_for()
        self.assertTrue(asked, "no .behaviour('…') call site found under btap/")
        bound = set().union(*_manifest_behaviours().values())
        for name, files in sorted(asked.items()):
            self.assertIn(
                name, bound,
                f"{name!r} is asked for in {files} but no edition manifest "
                "binds it — a behaviour orphan")

    def test_every_bound_module_imports(self):
        from importlib import import_module

        bindings = _manifest_behaviours()
        self.assertIn("necb2025", bindings, "the 2025 manifest went missing")
        for code_id, behaviours in sorted(bindings.items()):
            for name, dotted in sorted(behaviours.items()):
                with self.subTest(code_id=code_id, behaviour=name):
                    module = import_module(dotted)
                    self.assertEqual(dotted, module.__name__)

    def test_vocabulary_matches_the_manifests_and_the_call_sites(self):
        bound = set().union(*_manifest_behaviours().values())
        asked = set(_behaviour_names_asked_for())
        self.assertEqual(
            set(codes.BEHAVIOURS), bound,
            "btap.codes.BEHAVIOURS must be exactly the names the manifests bind")
        self.assertEqual(
            set(codes.BEHAVIOURS), asked,
            "btap.codes.BEHAVIOURS must be exactly the names product code asks for")

    def test_no_dynamic_behaviour_names(self):
        self.assertEqual(
            [], _dynamic_behaviour_calls(),
            "a .behaviour() call with a computed name cannot be checked by "
            "this gate — keep the name a literal")

    def test_necb2020_binds_no_archetype_eui_path(self):
        self.assertIsNone(codes.resolve("necb2020").behaviour("archetype_eui_path"))
        self.assertIsNone(codes.resolve("necb2020").behaviour("part11_ghg"))

    def test_necb2025_binds_both_modules(self):
        ruleset = codes.resolve("necb2025")
        eui = ruleset.behaviour("archetype_eui_path")
        ghg = ruleset.behaviour("part11_ghg")
        self.assertEqual("btap.codes.necb.editions.necb2025.eui_archetypes",
                         eui.__name__)
        self.assertEqual("btap.codes.necb.editions.necb2025.part11_ghg",
                         ghg.__name__)
        # Resolution is memoized, so the same module object comes back.
        self.assertIs(eui, ruleset.behaviour("archetype_eui_path"))

    def test_undeclared_behaviour_name_raises(self):
        for code_id in codes.code_ids():
            with self.subTest(code_id=code_id):
                with self.assertRaises(KeyError) as ctx:
                    codes.resolve(code_id).behaviour("no_such_behaviour")
                self.assertIn("no_such_behaviour", str(ctx.exception))

    def test_manifest_binding_an_unknown_name_is_refused(self):
        import tempfile

        from btap.codes import _read_manifest

        with tempfile.TemporaryDirectory(prefix="behaviour-bad-") as tmp:
            path = Path(tmp) / "necb2020"
            path.mkdir()
            (path / "manifest.json").write_text(json.dumps({
                "id": "necb2020", "family": "necb", "edition": "2020",
                "label": "NECB 2020",
                "behaviours": {"not_a_behaviour": "btap.codes"},
            }), encoding="utf-8")
            with self.assertRaises(ValueError) as ctx:
                _read_manifest(path / "manifest.json")
            self.assertIn("not_a_behaviour", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
