"""Two systems in ONE model do not take each other's plant or coils (#261 step 2).

Every catalogue test builds one system per model, so neither hazard below
could show there:

- `find_chilled_water` matched a loop on source, temperature profile and
  exclusions but never on compressor kind, so a centrifugal row and a scroll
  row built into one model shared ONE plant, whichever came first;
- `hp_plant_fancoils` attached every water coil in the model to its heat-pump
  plant, re-plumbing another hydronic system's coils, depending on order.

Each case is built in BOTH orders, as Astra's amendment requires, on the
five-zone fixture split in two. SDK only; nothing here runs EnergyPlus.
"""

import unittest

import btap.modeling as modeling
from tests.support import load_fixture, needs_sdk

CENTRIFUGAL = 'vav-hw-hwbb-gasboiler-centrifchiller'
SCROLL = 'vav-hw-hwbb-gasboiler-scrollchiller'
HEAT_PUMP_FAN_COILS = 'doas-fc4-hw-chw-awhp-elecboiler'


def _zones(model):
    from btap._compat import sorted_by_name
    return sorted_by_name(model.getThermalZones())


def _water_coils(model):
    return ({str(c.handle()): c for c in model.getCoilHeatingWaters()}
            | {str(c.handle()): c for c in model.getCoilCoolingWaters()})


def _build_pair(first, second):
    """Build `first` on the first two zones and `second` on the rest. Returns
    the model and, per system, the handles of the water coils its build made."""
    model = load_fixture()
    zones = _zones(model)
    made = {}
    for system, served in ((first, zones[:2]), (second, zones[2:])):
        before = set(_water_coils(model))
        modeling.build_system(model, system, served)
        made[system] = set(_water_coils(model)) - before
    return model, made


def _loop_handle(coil):
    from btap._compat import opt
    loop = opt(coil.plantLoop())
    return None if loop is None else str(loop.handle())


def _chilled_water_loops(model):
    from btap.modeling.hvac.systems import plant_loops
    return [loop for loop in model.getPlantLoops() if plant_loops._chillers(loop)]


def _kinds(loop):
    from btap._compat import opt
    from btap.modeling.hvac.systems.plant_loops import _chillers, chiller_compressor
    return {chiller_compressor(opt(c.to_ChillerElectricEIR())) for c in _chillers(loop)}


@needs_sdk
class TestChillerKindsDoNotShareAPlant(unittest.TestCase):

    def test_a_centrifugal_and_a_scroll_row_build_two_plants_in_either_order(self):
        for first, second in ((CENTRIFUGAL, SCROLL), (SCROLL, CENTRIFUGAL)):
            with self.subTest(first=first):
                model, made = _build_pair(first, second)
                loops = _chilled_water_loops(model)
                self.assertEqual(sorted(sorted(_kinds(loop)) for loop in loops),
                                 [['Centrifugal'], ['Scroll']])
                coil_loops = _water_coils(model)
                for system, kind in ((CENTRIFUGAL, 'Centrifugal'), (SCROLL, 'Scroll')):
                    cooling = [coil_loops[h] for h in made[system]
                               if coil_loops[h].iddObjectType().valueName() == 'OS_Coil_Cooling_Water']
                    self.assertTrue(cooling, system)
                    for coil in cooling:
                        loop = next(lp for lp in loops if str(lp.handle()) == _loop_handle(coil))
                        self.assertEqual(_kinds(loop), {kind}, system)

    def test_two_rows_of_the_same_kind_still_share_one_plant(self):
        """The kind PERMITS reuse; it does not stop the sharing that was right."""
        model, _ = _build_pair(SCROLL, SCROLL)
        self.assertEqual(len(_chilled_water_loops(model)), 1)

    def test_a_loop_whose_kind_cannot_be_read_is_still_reused(self):
        """A user's plant, or one built before the declaration, with no kind in
        its chillers' names: admitted as before, never refused for being unread."""
        from btap.modeling.hvac.systems.plant_loops import CHILLER_COMPRESSOR_FEATURE
        model = load_fixture()
        zones = _zones(model)
        modeling.build_system(model, SCROLL, zones[:2])
        for chiller in model.getChillerElectricEIRs():
            chiller.additionalProperties().resetFeature(CHILLER_COMPRESSOR_FEATURE)
            chiller.setName('User Chiller')
        modeling.build_system(model, CENTRIFUGAL, zones[2:])
        self.assertEqual(len(_chilled_water_loops(model)), 1)

    def test_a_renamed_chiller_keeps_its_declared_kind(self):
        """The reason for declaring it: a user may rename a chiller, and the
        name was the kind's only carrier."""
        model = load_fixture()
        zones = _zones(model)
        modeling.build_system(model, CENTRIFUGAL, zones[:2])
        for chiller in model.getChillerElectricEIRs():
            chiller.setName('Basement Chiller')
        modeling.build_system(model, SCROLL, zones[2:])
        self.assertEqual(sorted(sorted(_kinds(loop)) for loop in _chilled_water_loops(model)),
                         [['Centrifugal'], ['Scroll']])

    def test_an_undeclared_chiller_is_read_from_its_name(self):
        """A model built before the declaration keeps its kind through the name."""
        from btap.modeling.hvac.systems.plant_loops import CHILLER_COMPRESSOR_FEATURE
        model = load_fixture()
        zones = _zones(model)
        modeling.build_system(model, CENTRIFUGAL, zones[:2])
        for chiller in model.getChillerElectricEIRs():
            chiller.additionalProperties().resetFeature(CHILLER_COMPRESSOR_FEATURE)
        modeling.build_system(model, SCROLL, zones[2:])
        self.assertEqual(sorted(sorted(_kinds(loop)) for loop in _chilled_water_loops(model)),
                         [['Centrifugal'], ['Scroll']])

    def test_a_kind_in_the_name_wins_and_the_declaration_fills_in(self):
        """The name keeps precedence, so no existing efficiency result moves;
        the declaration answers only when the name says nothing."""
        from btap.modeling.hvac.systems.plant_loops import (
            CHILLER_COMPRESSOR_FEATURE,
            chiller_compressor,
        )
        model = load_fixture()
        modeling.build_system(model, SCROLL, _zones(model))
        chiller = model.getChillerElectricEIRs()[0]
        self.assertEqual(chiller_compressor(chiller), 'Scroll')
        chiller.additionalProperties().setFeature(CHILLER_COMPRESSOR_FEATURE, 'Centrifugal')
        self.assertEqual(chiller_compressor(chiller), 'Scroll')
        self.assertEqual(chiller_compressor(chiller, name='Basement Chiller'), 'Centrifugal')
        chiller.additionalProperties().resetFeature(CHILLER_COMPRESSOR_FEATURE)
        self.assertIsNone(chiller_compressor(chiller, name='Basement Chiller'))


@needs_sdk
class TestTheHeatPumpFanCoilPlantTakesOnlyItsOwnCoils(unittest.TestCase):

    def test_another_systems_water_coils_stay_on_its_own_plant_in_either_order(self):
        for first, second in ((SCROLL, HEAT_PUMP_FAN_COILS), (HEAT_PUMP_FAN_COILS, SCROLL)):
            with self.subTest(first=first):
                model, made = _build_pair(first, second)
                coils = _water_coils(model)
                own = {system: {_loop_handle(coils[h]) for h in handles}
                       for system, handles in made.items()}
                for system, loops in own.items():
                    self.assertNotIn(None, loops, f"{system} has an unattached water coil")
                # No plant loop serves coils of both systems.
                self.assertFalse(own[SCROLL] & own[HEAT_PUMP_FAN_COILS],
                                 "a plant serves both systems' water coils")


if __name__ == '__main__':
    unittest.main()
