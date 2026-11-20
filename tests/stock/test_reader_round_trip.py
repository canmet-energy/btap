"""A recipe written from a btap-built model rebuilds it (#237).

Four defects stopped that round trip, each silent or misleading:

- a RESOLVED HVAC group — the identified system, not a guess, and what every
  model built with btap's own builder produces — was neither built nor
  listed; only `accept_candidates` candidates were ever built;
- thermostats were applied AFTER HVAC, and the builder refuses zones without
  one, so on a fresh target the HVAC was refused for lack of the thermostats
  it was about to receive;
- a recipe carries densities, not schedules, so on a target with no schedules
  the loads landed unscheduled and EnergyPlus refused them — unnamed;
- what was skipped or refused was in the RETURN value only, with zero audit
  warnings.
"""

from __future__ import annotations

import unittest

from tests.support import needs_sdk

SYSTEM = "PSZ-AC with gas coil"


def _geometry(*, loads=True):
    from btap import modeling
    from btap.codes.necb import loads as necb_loads
    model = modeling.create(shape="rectangle", length=20.0, width=10.0, storeys=1)
    necb_loads.assign_space_types(
        model, {s.nameString(): ["Space Function", "Office enclosed > 25 m2"]
                for s in model.getSpaces()}, code="necb2020")
    modeling.seed_constructions(model)
    if loads:
        necb_loads.apply_loads(model, code="necb2020")
    return model


def _recipe():
    from btap import modeling, stock
    source = _geometry()
    modeling.build_system(source, SYSTEM, list(source.getThermalZones()))
    recipe = stock.write_recipe(source)
    groups = recipe["hvac"]["zone_groups"]
    assert groups and all(g["resolved"] for g in groups), groups
    return recipe


@needs_sdk
class TestRoundTrip(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.recipe = _recipe()

    def test_an_identified_system_is_built_on_a_fresh_target(self):
        from btap import stock
        from btap.audit import AuditLog
        target, audit = _geometry(loads=False), AuditLog()
        self.assertEqual(0, sum(not z.thermostatSetpointDualSetpoint().empty()
                                for z in target.getThermalZones()))
        account = stock.build_from_recipe(self.recipe, target, audit=audit)
        self.assertEqual([], account["refused"])
        self.assertIn(f"HVAC {SYSTEM!r} (IDENTIFIED) on 10 zone(s)", account["applied"])
        self.assertEqual(10, len(target.getAirLoopHVACs()))
        self.assertTrue(any(e["action"] == "HVAC built from the identified catalogue system"
                            and e["level"] == "decision" for e in audit.entries))

    def test_an_identified_system_whose_zones_are_absent_is_refused(self):
        import openstudio

        from btap import stock
        account = stock.build_from_recipe(self.recipe, openstudio.model.Model())
        self.assertEqual(1, len(account["refused"]))
        self.assertIn("none of its 10 zone(s) exist", account["refused"][0])

    def test_unscheduled_loads_are_named_and_warned(self):
        from btap import stock
        from btap.audit import AuditLog
        target, audit = _geometry(loads=False), AuditLog()
        account = stock.build_from_recipe(self.recipe, target, audit=audit)
        named = [s for s in account["skipped"] if "has NO schedule" in s]
        self.assertEqual({"People", "ElectricEquipment"},
                         {s.split(": ")[1].split(" has")[0] for s in named})
        self.assertTrue(any("SKIPPED" in w["action"] for w in audit.warnings))

    def test_a_target_with_schedules_flags_nothing(self):
        from btap import stock
        from btap.audit import AuditLog
        target, audit = _geometry(), AuditLog()
        account = stock.build_from_recipe(self.recipe, target, audit=audit)
        self.assertEqual([], [s for s in account["skipped"] if "has NO schedule" in s])


if __name__ == "__main__":
    unittest.main()
