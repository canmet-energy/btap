"""The PUBLIC API is declared, and changing it is a deliberate act.

Each subpackage's ``__all__`` is the promise made to users: a name in it is
something they may import and depend on; a name not in it is internal and may
change without notice. Python makes every non-underscore name importable, so
without a declaration ``btap.codes`` appeared to export ``json``, ``Path`` and
``dataclass`` merely because it imports them.

This pins every list EXACTLY. Removing or renaming a public name fails here, so
it cannot happen silently; adding one fails too, so a new name is published on
purpose. Either way the fix is to update ``PUBLIC`` below in the same change,
and the policy for doing so is in ``src/README.md`` ("Public API").

Six of the seven modules import without the SDK — the facades import lazily
(D-79), and ``btap.costing``'s public names are submodules, checked by
``find_spec`` rather than imported. ``btap.stock`` imports OpenStudio eagerly,
so its checks run under ``needs_sdk``: skipped by the zero-install fallback,
enforced wherever ``BTAP_SDK_REQUIRED=1`` (CI).
"""

from __future__ import annotations

import importlib
import importlib.util
import types
import unittest

from tests.support import needs_sdk

#: The declared public API, by module. Order matches each module's __all__.
PUBLIC: dict[str, list[str]] = {
    "btap": ["__version__"],
    "btap.audit": ["AuditLog", "emit_coverage"],
    "btap.simulation": ["Backend", "Http", "Local", "Remote", "Result", "engine", "run",
                        "runner"],
    "btap.modeling": [
        "SHAPES", "create", "create_from_footprint", "bar", "apply_wwr",
        "seed_constructions", "render", "floor_plans", "systems", "build_system",
        "replace_system", "remove_hvac_from_zones", "plant_is_hvac_candidate",
        "characterize", "catalog_html", "model_hvac_diagrams", "hvac_icon_defs",
    ],
    "btap.costing": ["envelope", "hvac", "lighting", "shw"],
    "btap.codes": ["performance_compliance", "resolve", "code_ids", "editions",
                   "Ruleset", "UnknownRuleset"],
    "btap.stock": ["RecipeError", "build_from_recipe", "identify_candidates", "suggest",
                   "controls_section", "envelope_section", "equipment_section",
                   "hvac_section", "loads_section", "space_types_section",
                   "write_recipe"],
}

#: The six subpackages. A seventh must declare its API before it ships.
SUBPACKAGES = {"btap.audit", "btap.simulation", "btap.modeling", "btap.costing",
               "btap.codes", "btap.stock"}

#: Modules whose import needs the OpenStudio SDK.
SDK_BACKED = {"btap.stock"}


def _has(module: types.ModuleType, name: str) -> bool:
    """A public name resolves without importing anything the SDK backs."""
    if name in vars(module):
        return True
    # A public SUBMODULE (btap.costing's whole API) is checked by spec, not by
    # import, so this test stays SDK-free.
    return importlib.util.find_spec(f"{module.__name__}.{name}") is not None


class _Checks:
    """The checks, over ``self.modules``; mixed into the two classes below."""

    modules: list[str] = []

    def test_every_module_declares_its_api(self):
        for name in self.modules:
            with self.subTest(module=name):
                module = importlib.import_module(name)
                self.assertTrue(hasattr(module, "__all__"),
                                f"{name} declares no __all__")

    def test_each_list_is_exactly_the_declared_api(self):
        for name in self.modules:
            expected = PUBLIC[name]
            with self.subTest(module=name):
                declared = importlib.import_module(name).__all__
                self.assertEqual(
                    expected, list(declared),
                    f"{name}.__all__ changed. A removed or renamed name BREAKS "
                    "users; an added one is a new promise. Either is allowed, "
                    "but only on purpose: update PUBLIC here in the same change "
                    "(policy: src/README.md, 'Public API').")

    def test_every_declared_name_resolves(self):
        for name in self.modules:
            expected = PUBLIC[name]
            module = importlib.import_module(name)
            for public in expected:
                with self.subTest(name=f"{name}.{public}"):
                    self.assertTrue(_has(module, public),
                                    f"{name}.__all__ names {public!r}, which does not exist")

    def test_no_declared_name_is_private_or_repeated(self):
        for name in self.modules:
            expected = PUBLIC[name]
            with self.subTest(module=name):
                self.assertEqual(len(expected), len(set(expected)), "a name is listed twice")
                private = [n for n in expected if n.startswith("_") and n != "__version__"]
                self.assertEqual([], private)


class TestThePublicApiIsDeclared(_Checks, unittest.TestCase):
    modules = sorted(set(PUBLIC) - SDK_BACKED)

    def test_every_subpackage_is_covered(self):
        self.assertEqual(SUBPACKAGES, set(PUBLIC) - {"btap"})

    def test_incidental_imports_are_not_public(self):
        # The names that motivated this test: visible on btap.codes only
        # because the module imports them.
        declared = set(importlib.import_module("btap.codes").__all__)
        for incidental in ("json", "Path", "dataclass", "field", "lru_cache", "Any",
                           "Mapping", "MappingProxyType", "annotations",
                           "BEHAVIOURS", "DATA_DIR"):
            with self.subTest(name=incidental):
                self.assertNotIn(incidental, declared)


@needs_sdk
class TestTheSdkBackedPublicApiIsDeclared(_Checks, unittest.TestCase):
    modules = sorted(SDK_BACKED)


if __name__ == "__main__":
    unittest.main()
