"""Two authoring defects #236 found by building from nothing and simulating.

A. A single-zone or no-reheat loop whose row sets no central heating design
   temperature kept OpenStudio's 16.7 C Sizing:System default — a VAV-preheat
   value — while the same builder designed its zones for 40 C supply air. The
   only heating coil was sized to deliver air barely warmer than the room, so
   a cold-morning recovery failed: 19.5 h of heating unmet in a January week,
   6.8 h once matched. The central temperature now follows the zones' own.

B. Fan coils the builder authors were not marked for the mode-specific sizing
   contract (D-106/D-107), so a heating-dominated zone's cooling-coil UA
   inversion failed: 2 Severe on a 24-zone office. They are marked at build
   time now (D-110).

SDK-only checks on the built model, plus one engine test that witnesses A at
the call site a user reaches: build, simulate, read unmet hours.
"""

from __future__ import annotations

import unittest
import warnings

import btap.modeling as modeling
from tests.support import DDY, EPW, load_fixture, needs_engine, needs_sdk

NO_REHEAT_ROWS = ("PSZ-AC with gas coil", "PSZ-AC with electric coil",
                  "Forced air furnace", "Shared PSZ with gas boiler coils and hot water baseboard")
REHEAT_ROW = "Shared hot water air handler with water reheat"
NECB_ROW = "PSZ RTU Gas and DX Coils and Hot Water Baseboard"   # its sizing block sets 43 C


def _built(name):
    model = load_fixture()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        modeling.build_system(model, name, sorted(model.getThermalZones(),
                                                  key=lambda z: z.nameString()))
    return model


@needs_sdk
class TestCentralHeatingFollowsTheZones(unittest.TestCase):

    def test_a_no_reheat_loop_delivers_what_its_zones_are_sized_for(self):
        for name in NO_REHEAT_ROWS:
            with self.subTest(system=name):
                model = _built(name)
                for loop in model.getAirLoopHVACs():
                    zone_sat = max(z.sizingZone().zoneHeatingDesignSupplyAirTemperature()
                                   for z in loop.thermalZones())
                    self.assertAlmostEqual(
                        zone_sat, loop.sizingSystem().centralHeatingDesignSupplyAirTemperature(),
                        msg="the only heating coil must be designed for the zones' supply air")
                    self.assertGreater(zone_sat, 30.0)

    def test_a_reheat_loop_keeps_its_central_default(self):
        # Its zones are heated by their reheat coils; the central coil preheats.
        model = _built(REHEAT_ROW)   # held: a loop outliving its model segfaults
        loop = model.getAirLoopHVACs()[0]
        self.assertAlmostEqual(16.7, loop.sizingSystem().centralHeatingDesignSupplyAirTemperature(),
                               places=1)

    def test_a_row_whose_sizing_block_sets_it_is_untouched(self):
        model = _built(NECB_ROW)
        loop = model.getAirLoopHVACs()[0]
        self.assertAlmostEqual(43.0, loop.sizingSystem().centralHeatingDesignSupplyAirTemperature())


@needs_sdk
class TestAuthoredFanCoilsAreMarked(unittest.TestCase):

    def test_every_fan_coil_the_builder_authors_is_marked(self):
        from btap.simulation.translation import marked_fan_coil_names
        for name in ("FPFC MAU DX Coils with Scroll Chiller",):
            with self.subTest(system=name):
                model = _built(name)
                fan_coils = sorted(fc.nameString() for fc in model.getZoneHVACFourPipeFanCoils())
                self.assertTrue(fan_coils)
                self.assertEqual(fan_coils, sorted(marked_fan_coil_names(model)))

    def test_the_heat_pump_plant_fan_coils_are_marked_too(self):
        from btap.simulation.translation import marked_fan_coil_names
        rows = [s["name"] for s in modeling.systems() if s["family"] == "ecm_hp_fancoils"]
        self.assertTrue(rows, "the ECM heat-pump fan-coil rows went missing")
        model = _built(rows[0])
        fan_coils = sorted(fc.nameString() for fc in model.getZoneHVACFourPipeFanCoils())
        self.assertTrue(fan_coils)
        self.assertEqual(fan_coils, sorted(marked_fan_coil_names(model)))

    def test_the_marker_is_defined_once(self):
        # btap.modeling and btap.simulation must read the SAME flag.
        import btap._fan_coil_sizing as shared
        import btap.simulation.translation as translation
        self.assertIs(shared.mark_fan_coil_for_mode_specific_sizing,
                      translation.mark_fan_coil_for_mode_specific_sizing)
        self.assertEqual(shared.FAN_COIL_MODE_SPECIFIC_AIRFLOW_FEATURE,
                         translation.FAN_COIL_MODE_SPECIFIC_AIRFLOW_FEATURE)


@needs_engine
class TestASingleZoneUnitRecoversFromSetback(unittest.TestCase):
    """A at the call site: the 24-zone office of #236, one PSZ-AC per zone,
    one January week. 19.5 h of heating unmet before the fix, 6.8 after."""

    def test_heating_unmet_hours_stay_low(self):
        import os
        import tempfile

        from btap import simulation
        from btap.codes.necb import lighting, loads, shw
        model = modeling.bar(
            space_type_ratios={("Space Function", "Office enclosed > 25 m2"): 0.75,
                               ("Space Function", "Corridor/Transition area other-sch-A"): 0.25},
            length=40.0, width=20.0, storeys=2, wwr=0.35)
        modeling.seed_constructions(model)
        loads.apply_loads(model, code="necb2020")
        lighting.apply_lights(model, code="necb2020")
        shw.apply_shw(model, code="necb2020", fuel="NaturalGas")
        modeling.build_system(model, "PSZ-AC with gas coil", list(model.getThermalZones()))
        with tempfile.TemporaryDirectory(prefix="setback-recovery-") as tmp:
            result = simulation.run(
                model, run_dir=os.path.join(tmp, "run"),
                weather={"epw": str(EPW), "ddy": str(DDY)},
                run_period={"begin_month": 1, "begin_day": 8, "end_month": 1, "end_day": 14})
        self.assertTrue(result.clean)
        self.assertLess(result.unmet_hours["heating"], 10.0, result.unmet_hours)


if __name__ == "__main__":
    unittest.main()
