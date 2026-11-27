"""A heating plant heat pump's CAPACITY reaches the plant facts (#244).

8.4.4.9.(5) / 8.4.5.9.(5) ratio the proposed heating capacity allocation per
energy type. `classify` recorded a boiler's capacity but only a heat pump's
FUEL, so a hybrid heat-pump + boiler plant reported `{'NaturalGas': W}` with
no electricity entry, and the disclosure's capacity shares stayed
"unavailable without sizing" even on a sized model (Fable, review of #245).
"""

from __future__ import annotations

import tempfile
import unittest

from tests.support import DDY, EPW, load_fixture, needs_engine, needs_sdk


def _plant(model, kind='hot_water'):
    from btap import modeling
    facts = modeling.characterize(model, audit=None)
    plants = [p for p in facts['plants'] if p['type'] == kind and p['heat_pump']]
    assert len(plants) == 1, plants
    return facts, plants[0]


def _built(system):
    from btap import modeling
    from btap._compat import sorted_by_name
    model = load_fixture()
    modeling.build_system(model, system, sorted_by_name(model.getThermalZones()))
    return model


@needs_sdk
class TestBeforeSizing(unittest.TestCase):

    def test_an_autosized_heat_pump_is_UNKNOWN_not_absent(self):
        _, plant = _plant(_built('bb-hwbb-awhp-gasbu'))
        self.assertEqual({'Electricity': None, 'NaturalGas': None}, plant['fuel_capacities_w'])
        self.assertEqual(1, plant['boiler_count'], 'the heat pump is not counted as a boiler')


@needs_engine
class TestAfterSizing(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        from btap import simulation
        cls.tmp = tempfile.TemporaryDirectory()
        cls.model = _built('bb-hwbb-awhp-gasbu')
        simulation.run(cls.model, run_dir=cls.tmp.name,
                       weather={"epw": str(EPW), "ddy": str(DDY)}, sizing_only=True)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_both_energy_types_carry_their_sized_capacity(self):
        _, plant = _plant(self.model)
        watts = plant['fuel_capacities_w']
        self.assertEqual({'Electricity', 'NaturalGas'}, set(watts))
        hp = self.model.getHeatPumpPlantLoopEIRHeatings()[0]
        self.assertAlmostEqual(hp.autosizedReferenceCapacity().get(), watts['Electricity'], places=3)
        boiler = self.model.getBoilerHotWaters()[0]
        self.assertAlmostEqual(boiler.autosizedNominalCapacity().get(), watts['NaturalGas'], places=3)
        self.assertEqual(1, plant['boiler_count'])

    def test_the_disclosure_can_now_state_the_shares(self):
        from btap.codes.necb.hvac.reference import _heating_allocation
        facts, _ = _plant(self.model)
        group = facts['zone_groups'][0]
        allocation = _heating_allocation(group, facts)
        self.assertIsNotNone(allocation, 'a sized hybrid plant establishes its allocation')
        shares, watts = allocation
        self.assertEqual({'Electricity', 'NaturalGas'}, set(shares))
        self.assertAlmostEqual(1.0, sum(shares.values()), places=9)


@needs_sdk
class TestACoolingHeatPumpIsNotHeatingCapacity(unittest.TestCase):

    def test_the_chilled_water_side_records_no_heating_capacity(self):
        # hp_plant_fancoils builds a companion COOLING heat pump on the
        # chilled-water loop; it must not enter a heating ratio.
        _, plant = _plant(_built('doas-fc4-hw-chw-awhp-elecboiler'), kind='chilled_water')
        self.assertEqual({}, plant['fuel_capacities_w'])


if __name__ == "__main__":
    unittest.main()
