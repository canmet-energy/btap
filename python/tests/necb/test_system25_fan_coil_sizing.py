"""Focused engine witness for NECB reference Systems 2 and 5 fan-coil sizing."""

from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

import btap.modeling as modeling
from btap.codes import performance_compliance
from btap.codes.necb import hvac
from btap.simulation import runner, translation
from tests.necb.hvac_helpers import load_fixture, sorted_zones
from tests.support import DDY, EPW, needs_engine, needs_sdk

PROPOSED_SYSTEM = "PSZ RTU Gas and DX Coils and Hot Water Baseboard"


def _building(model, space_type, **extra):
    return {
        "storeys": 1,
        "zone_types": {
            zone.nameString(): space_type
            for zone in model.getThermalZones()
        },
        "winter_design_temp_c": -20,
        **extra,
    }


@needs_sdk
class TestSystem25FanCoilSizingContract(unittest.TestCase):
    def test_system_5_fan_coils_carry_the_same_translation_contract(self):
        proposed = load_fixture()
        modeling.build_system(proposed, PROPOSED_SYSTEM, sorted_zones(proposed))
        zone_names = [
            zone.nameString() for zone in proposed.getThermalZones()
        ]
        result = hvac.reference_hvac(
            proposed,
            code="necb2020",
            building=_building(
                proposed,
                "warehouse",
                refrigerated_zones=zone_names,
            ),
        )

        self.assertEqual(
            {5}, {assignment.reference_system for assignment in result.assignments}
        )
        fan_coils = result.model.getZoneHVACFourPipeFanCoils()
        self.assertEqual(5, len(fan_coils))
        self.assertEqual(
            sorted(fan_coil.nameString() for fan_coil in fan_coils),
            sorted(translation.marked_fan_coil_names(result.model)),
        )
        self.assertTrue(
            any(
                entry.get("ruling") == "D-106"
                for entry in result.audit.entries
            )
        )


@needs_engine
class TestSystem2HeatingDominatedSizing(unittest.TestCase):
    def test_heating_dominated_system_2_water_coils_size_cleanly(self):
        weather = {"epw": str(EPW), "ddy": str(DDY)}
        with tempfile.TemporaryDirectory(prefix="system2-fan-coil-sizing-") as tmp:
            for code in ("necb2020", "necb2025"):
                with self.subTest(code=code):
                    proposed = load_fixture()
                    modeling.build_system(
                        proposed, PROPOSED_SYSTEM, sorted_zones(proposed)
                    )
                    run_dir = Path(tmp) / code
                    result = performance_compliance(
                        proposed,
                        code=code,
                        simulate="sizing",
                        weather=weather,
                        building=_building(proposed, "data centre"),
                        run_dir=str(run_dir),
                        hdd=3890,
                        province_state="ONTARIO",
                    )

                    output = run_dir / "reference_sizing" / "run"
                    error_text = (output / "eplusout.err").read_text(
                        encoding="utf-8", errors="replace"
                    )
                    self.assertTrue(
                        runner.is_clean_run(output), error_text
                    )
                    self.assertNotIn("Bad starting values for UA", error_text)

                    fan_coils = (
                        result.reference_model
                        .getZoneHVACFourPipeFanCoils()
                    )
                    self.assertEqual(5, len(fan_coils))
                    self.assertEqual(
                        sorted(
                            fan_coil.nameString()
                            for fan_coil in fan_coils
                        ),
                        sorted(
                            translation.marked_fan_coil_names(
                                result.reference_model
                            )
                        ),
                    )
                    self._assert_mode_specific_airflows(
                        run_dir / "reference_sizing" / "run" / "eplusout.sql",
                        fan_coils,
                    )
                    expected_article = (
                        "Table 8.4.4.7.-B"
                        if code == "necb2020"
                        else "Table 8.4.5.7.-B"
                    )
                    entries = [
                        entry for entry in result.audit.entries
                        if entry.get("ruling") == "D-106"
                    ]
                    self.assertEqual(1, len(entries))
                    self.assertIn(expected_article, entries[0]["article"])

    def _assert_mode_specific_airflows(self, sql_path, fan_coils):
        connection = sqlite3.connect(sql_path)
        self.addCleanup(connection.close)
        zone_sizes = {
            (zone.upper(), load_type): flow
            for zone, load_type, flow in connection.execute(
                "SELECT ZoneName, LoadType, UserDesFlow FROM ZoneSizes"
            )
        }
        ratios = []
        for fan_coil in fan_coils:
            zone = fan_coil.thermalZone().get()
            cooling = zone_sizes[(zone.nameString().upper(), "Cooling")]
            heating = zone_sizes[(zone.nameString().upper(), "Heating")]
            ratios.append(heating / cooling)
            coil_name = (
                fan_coil.coolingCoil().to_CoilCoolingWater().get().nameString()
            )
            values = [
                row[0]
                for row in connection.execute(
                    "SELECT Value FROM ComponentSizes "
                    "WHERE CompType = 'Coil:Cooling:Water' "
                    "AND upper(CompName) = upper(?) "
                    "AND Description LIKE "
                    "'User-Specified%Design Air Flow Rate'",
                    (coil_name,),
                )
            ]
            self.assertEqual([cooling], values)
        self.assertGreater(
            max(ratios),
            5.0,
            "the fixture must remain heating-dominated enough to reach the "
            "former UA-inversion failure",
        )


if __name__ == "__main__":
    unittest.main()
