"""Stage 2 (docs/NECB_MULTI_EDITION_PLAN.md): API tests for the ``Ruleset``
registry — ``btap.codes.Ruleset``, ``code_ids``, ``editions``, ``resolve``.

Written against the SPEC before the implementation lands (a sibling agent
builds ``btap.codes.__init__`` and the two manifests in parallel); these
tests fail with ImportError until that lands, then guard it. No SDK import.

Also guards "three registries, kept separate": ``editions()`` (backs
``--code`` choices) is a distinct callable from ``coverage.editions()``
("has packaged 8.4 text"); Stage 8 may add a manifest-only edition to the
former without touching the latter, so this asserts today's equal VALUE,
never that the two functions stay in lockstep.
"""

import dataclasses
import unittest


class RulesetRegistryTests(unittest.TestCase):
    def test_code_ids_sorted(self):
        from btap.codes import code_ids

        self.assertEqual(code_ids(), ["necb2020", "necb2025"])

    def test_editions_necb(self):
        from btap.codes import editions

        self.assertEqual(editions("necb"), ["2020", "2025"])

    def test_resolve_round_trip_necb2020(self):
        from btap.codes import resolve

        ruleset = resolve("necb2020")
        self.assertEqual(ruleset.id, "necb2020")
        self.assertEqual(ruleset.family, "necb")
        self.assertEqual(ruleset.edition, "2020")
        self.assertEqual(ruleset.label, "NECB 2020")

    def test_resolve_round_trip_necb2025(self):
        from btap.codes import resolve

        ruleset = resolve("necb2025")
        self.assertEqual(ruleset.id, "necb2025")
        self.assertEqual(ruleset.family, "necb")
        self.assertEqual(ruleset.edition, "2025")
        self.assertEqual(ruleset.label, "NECB 2025")

    def test_article_reference_and_lighting_subsection(self):
        from btap.codes import resolve

        for key in ("reference_subsection", "lighting_subsection"):
            self.assertEqual(resolve("necb2020").article(key), "8.4.4")
            self.assertEqual(resolve("necb2025").article(key), "8.4.5")

    def test_article_heat_pump_aux_fuel_present_only(self):
        # Edition-specific; the plan says not to pin its value — assert
        # only presence as a non-empty string.
        from btap.codes import resolve

        for code_id in ("necb2020", "necb2025"):
            value = resolve(code_id).article("heat_pump_aux_fuel")
            self.assertIsInstance(value, str)
            self.assertTrue(value)

    def test_article_missing_key_raises_keyerror(self):
        from btap.codes import resolve

        with self.assertRaises(KeyError):
            resolve("necb2020").article("no_such_article_key")

    def test_behaviour_is_bound_through_the_manifest(self):
        # Stage 5: the placeholder that returned None for both editions is
        # now the manifest binding. 2020 binds nothing (so the 8.4.4 EUI path
        # simply does not exist there); 2025 binds its own module. The full
        # contract, including the orphan rule, is
        # tests/necb/test_behaviour_binding.py.
        from btap.codes import resolve

        self.assertIsNone(resolve("necb2020").behaviour("archetype_eui_path"))
        self.assertEqual(
            "btap.codes.necb.editions.necb2025.eui_archetypes",
            resolve("necb2025").behaviour("archetype_eui_path").__name__)

    def test_rules_loads_this_editions_own_file(self):
        """Stage 6: ``rules`` is the ONE loader, and it reads THIS edition."""
        from btap.codes import resolve
        from btap.codes.necb import rulesdata

        rules = resolve("necb2020").rules("envelope")
        self.assertIsInstance(rules, dict)
        self.assertTrue(rules)
        # The same memoized object the family's loader hands the domain shim:
        # one cache, not one per caller.
        self.assertIs(rules, rulesdata.load("envelope", "necb2020"))
        # Every domain the manifest declares resolves; nothing else does.
        for domain in ("umbrella", "envelope", "hvac", "hvac_efficiencies",
                       "lighting", "loads", "shw"):
            self.assertTrue(resolve("necb2025").rules(domain), domain)

    def test_rules_of_undeclared_domain_raises_naming_edition_and_domain(self):
        """No default file name, no other edition's rules — one loud error."""
        from btap.codes import resolve

        with self.assertRaises(ValueError) as ctx:
            resolve("necb2020").rules("plumbing")
        message = str(ctx.exception)
        self.assertIn("necb2020", message)
        self.assertIn("plumbing", message)

    def test_rules_are_per_edition_not_shared(self):
        """Two editions are two snapshots: the loader never crosses them."""
        from btap.codes import resolve

        self.assertIsNot(resolve("necb2020").rules("shw"),
                         resolve("necb2025").rules("shw"))

    def test_from_edition_equals_resolve(self):
        from btap.codes import Ruleset, resolve

        self.assertEqual(Ruleset.from_edition("2020"), resolve("necb2020"))
        self.assertEqual(Ruleset.from_edition("2025"), resolve("necb2025"))

    def test_resolve_unknown_id_raises_with_id_in_message(self):
        from btap.codes import resolve

        with self.assertRaises((KeyError, ValueError)) as ctx:
            resolve("necb2017")
        self.assertIn("necb2017", str(ctx.exception))

    def test_ruleset_is_frozen(self):
        from btap.codes import resolve

        ruleset = resolve("necb2020")
        with self.assertRaises(dataclasses.FrozenInstanceError):
            ruleset.id = "necb2025"

    def test_editions_registry_separation(self):
        from btap.codes import coverage, editions

        self.assertIsNot(editions, coverage.editions)
        # Today's value happens to match coverage's "has packaged 8.4 text"
        # list, but the two are independent registries (Stage 8 may add a
        # manifest-only edition to `editions()` without touching
        # `coverage.editions()`) — assert this list alone, never equality
        # between the two.
        self.assertEqual(editions("necb"), ["2020", "2025"])


if __name__ == "__main__":
    unittest.main()
