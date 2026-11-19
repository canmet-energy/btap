"""The NECB domain facades show their REAL signatures, and cannot drift from them.

#236 built a building from nothing as a user would, from the READMEs and
``help()``. ``btap.codes.necb.lighting.apply_lights`` and
``btap.codes.necb.shw.apply_shw`` were ``(model, **kwargs)`` with no docstring,
so ``help()`` could not say what they accept: the arguments lived one module
down. Each facade now spells out its target's signature — which is a COPY, and
a copy drifts. This test holds every facade's parameters (name, kind, default)
equal to its target's, and refuses a new ``**kwargs`` forwarder.
"""

from __future__ import annotations

import ast
import importlib
import inspect
import unittest
from pathlib import Path

from tests.support import needs_sdk

NECB = Path(__file__).resolve().parents[2] / "src" / "btap" / "codes" / "necb"

#: facade (module, name) -> target (module, name)
FORWARDERS = {
    ("btap.codes.necb.envelope", "hdd18"): ("btap.codes.necb.envelope.climate", "hdd18"),
    ("btap.codes.necb.envelope", "cost"): ("btap.costing.envelope", "cost"),
    ("btap.codes.necb.shw", "apply_shw"): ("btap.codes.necb.shw.demand", "apply_shw"),
    ("btap.codes.necb.shw", "cost"): ("btap.costing.shw", "cost"),
    ("btap.codes.necb.shw", "apply_water_heater_efficiency"):
        ("btap.codes.necb.shw.efficiency", "apply_efficiency"),
    ("btap.codes.necb.shw", "reference_shw"): ("btap.codes.necb.shw.reference", "reference_shw"),
    ("btap.codes.necb.lighting", "apply_lights"):
        ("btap.codes.necb.lighting.apply_lights", "apply_lights"),
    ("btap.codes.necb.lighting", "add_daylighting_controls"):
        ("btap.codes.necb.lighting.daylighting", "add_controls"),
    ("btap.codes.necb.lighting", "reference_lighting"):
        ("btap.codes.necb.lighting.reference", "reference_lighting"),
    ("btap.codes.necb.lighting", "reference_daylighting"):
        ("btap.codes.necb.lighting.reference_daylighting", "apply"),
}

#: `**kwargs` facades that are NOT plain forwarders, each with its reason.
KWARGS_ALLOWED = {
    ("lighting", "cost"): "injects the daylighted-area provider before forwarding, "
                          "so its signature is not its target's",
}


def _params(fn):
    return [(p.name, p.kind, p.default) for p in inspect.signature(fn).parameters.values()]


@needs_sdk
class TestFacadesMirrorTheirTargets(unittest.TestCase):

    def test_every_facade_has_its_targets_parameters(self):
        for (fmod, fname), (tmod, tname) in FORWARDERS.items():
            with self.subTest(facade=f"{fmod}.{fname}"):
                facade = getattr(importlib.import_module(fmod), fname)
                target = getattr(importlib.import_module(tmod), tname)
                self.assertEqual(_params(target), _params(facade),
                                 f"{fmod}.{fname} no longer matches {tmod}.{tname}")

    def test_every_facade_has_a_docstring(self):
        for (fmod, fname) in FORWARDERS:
            with self.subTest(facade=f"{fmod}.{fname}"):
                doc = inspect.getdoc(getattr(importlib.import_module(fmod), fname))
                self.assertTrue(doc and len(doc) > 20, "help() would say nothing")


class TestNoNewKwargsForwarder(unittest.TestCase):
    """SDK-free: reads the domain __init__ files as source."""

    def test_no_domain_facade_hides_its_arguments_behind_kwargs(self):
        found = []
        for init in sorted(NECB.glob("*/__init__.py")):
            for node in ast.parse(init.read_text(encoding="utf-8")).body:
                if (isinstance(node, ast.FunctionDef) and node.args.kwarg
                        and not node.name.startswith("_")
                        and (init.parent.name, node.name) not in KWARGS_ALLOWED):
                    found.append(f"{init.parent.name}.{node.name}")
        self.assertEqual([], found,
                         "a public facade takes **kwargs, so help() cannot show its "
                         "arguments: spell out the target's signature and add it to "
                         "FORWARDERS, or list it in KWARGS_ALLOWED with the reason")

    def test_the_allowlist_is_not_stale(self):
        for domain, name in KWARGS_ALLOWED:
            with self.subTest(facade=f"{domain}.{name}"):
                tree = ast.parse((NECB / domain / "__init__.py").read_text(encoding="utf-8"))
                self.assertTrue(any(isinstance(n, ast.FunctionDef) and n.name == name
                                    and n.args.kwarg for n in tree.body))


if __name__ == "__main__":
    unittest.main()
