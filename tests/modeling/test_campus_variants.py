"""Catalogue variants for Campus model reconstruction — issue #152.

Six requirements came out of a structural review of 31 Campus models (134 air
loops). The assessment on that issue found five needed no new equipment
implementation. These cover the three landed here:

- **#4 hydronic unit heaters** — a catalogue row and NOTHING else.
  `unit_heaters.py` already declared "gas/electric/hot-water" and already
  passed `hw_loop` into `coils.heating_coil`; only the row was missing.
- **#1 heating-only hydronic CAV air handler** (19 loops / 7 models) and
  **#3 shared furnace with DX and no central outdoor air** (12 loops) — the
  SAME gap, that `furnace.py` built one loop per zone, so one `per_zone`
  option serves both.

The reconstruction point throughout: 87 of the 134 existing loops serve
MULTIPLE zones, so one system per zone would change their behaviour. These
tests therefore assert the served-zone relationship, not just the equipment.

No energy-equivalence claim: this pins topology and equipment, which is what
the assessment promised and all it promised.
"""

import unittest

import btap.modeling as modeling
from tests.support import load_fixture, needs_sdk


@needs_sdk
class TestCampusVariants(unittest.TestCase):

    def _build(self, name):
        from btap._compat import sorted_by_name

        model = load_fixture()
        zones = sorted_by_name(model.getThermalZones())
        self.assertGreater(len(zones), 1,
                           'a shared loop is only meaningful on several zones')
        result = modeling.build_system(model, name, zones)
        return model, zones, result

    # ------------------------------------------------------------------ #4
    def test_hydronic_unit_heaters_need_NO_builder_change(self):
        """A water coil per zone off a boiler plant, and no air loop at all."""
        model, zones, _ = self._build('Hot water unit heaters')
        self.assertEqual(len(zones), len(model.getCoilHeatingWaters()),
                         'one hydronic coil per zone')
        self.assertEqual(0, len(model.getCoilHeatingGass()),
                         'a hydronic unit heater is NOT a gas-fired one, even '
                         'when its upstream boiler burns gas (#152)')
        self.assertEqual(0, len(model.getCoilHeatingElectrics()))
        self.assertEqual(1, len(model.getPlantLoops()), 'a hot-water loop')
        self.assertTrue(model.getBoilerHotWaters())
        self.assertEqual(len(zones), len(model.getZoneHVACUnitHeaters()))
        self.assertEqual(0, len(model.getAirLoopHVACs()),
                         'zone equipment, not an air system')

    # ------------------------------------------------------------------ #1
    def test_heating_only_hydronic_air_handler_is_SHARED_and_has_no_cooling(self):
        """Requirement 1. Introducing cooling is the error #152 warns against."""
        model, zones, result = self._build(
            'Shared hot water heating-only air handler')
        self.assertEqual(1, len(result.air_loops),
                         'ONE loop, not one per zone — 87 of 134 Campus loops '
                         'serve multiple zones')
        self.assertEqual(
            len(zones), len(result.air_loops[0].thermalZones()),
            'and it must serve every zone it was given')
        self.assertEqual(1, len(model.getCoilHeatingWaters()), 'hydronic')
        self.assertEqual(0, len(model.getCoilHeatingGass()))
        self.assertEqual(0, len(model.getCoilCoolingDXSingleSpeeds()),
                         'HEATING-ONLY: adding cooling would change what the '
                         'reconstructed model can do')
        self.assertEqual(0, len(model.getCoilCoolingWaters()))
        self.assertTrue(model.getBoilerHotWaters(), 'needs_boiler provisions it')
        self.assertEqual(1, len(model.getAirLoopHVACOutdoorAirSystems()),
                         'this one does ventilate')

    # ------------------------------------------------------------------ #3
    def test_shared_furnace_with_DX_has_NO_central_outdoor_air(self):
        """Requirement 3, and the OA absence is the whole point of the row."""
        model, zones, result = self._build(
            'Shared furnace with DX cooling and no outdoor air')
        self.assertEqual(1, len(result.air_loops), 'shared, not per zone')
        self.assertEqual(len(zones),
                         len(result.air_loops[0].thermalZones()))
        self.assertEqual(1, len(model.getCoilHeatingGass()), 'one furnace')
        self.assertEqual(1, len(model.getCoilCoolingDXSingleSpeeds()), 'DX')
        self.assertEqual(0, len(model.getAirLoopHVACOutdoorAirSystems()),
                         'NO central outdoor-air system — the observed Campus '
                         'Office-Small loops have none')
        self.assertEqual(0, len(model.getPlantLoops()),
                         'a gas furnace needs no plant')

    # ------------------------------------------------------------------ #2
    def test_water_REHEAT_terminals_on_a_shared_hydronic_handler(self):
        """Requirement 2. Neither the terminal nor the coil is new — mau_ptac
        already builds this pair — so this row is requirement 1 plus `reheat`
        rather than a separate family."""
        model, zones, result = self._build(
            'Shared hot water air handler with water reheat')
        self.assertEqual(1, len(result.air_loops), 'shared')
        self.assertEqual(
            len(zones),
            len(model.getAirTerminalSingleDuctConstantVolumeReheats()),
            'a CV reheat terminal per served zone')
        self.assertEqual(
            0, len(model.getAirTerminalSingleDuctUncontrolleds()),
            'reheat REPLACES the uncontrolled diffuser')
        self.assertEqual(len(zones) + 1, len(model.getCoilHeatingWaters()),
                         'one main coil plus one reheat coil per zone')
        self.assertEqual(0, len(model.getCoilCoolingDXSingleSpeeds()))

    def test_reheat_on_a_PER_ZONE_loop_is_REFUSED(self):
        """A per-zone loop already tracks its own zone, so a reheat terminal
        has nothing to correct. Refused rather than silently ignored, which is
        the policy #152 asks for: "reject unsupported combinations"."""
        from btap._compat import sorted_by_name
        from btap.modeling.hvac.systems.furnace import Furnace

        model = load_fixture()
        zones = sorted_by_name(model.getThermalZones())
        config = {'name': 'probe', 'heating': True, 'reheat': 'Hot Water',
                  'per_zone': True}
        with self.assertRaises(ValueError) as caught:
            Furnace(config).preflight(model, zones, control_zone=zones[0])
        self.assertIn('nothing to correct', str(caught.exception))

    def test_the_refusal_leaves_the_model_UNTOUCHED(self):
        """WHERE it is refused is the point, not merely that it is.

        `build_system` tears down the existing HVAC and only then calls
        `build`, so a refusal raised mid-build leaves the submitter with
        neither their original system nor a complete new one. This counts the
        objects a partial build would have left behind — Fable witnessed air
        loops, fans and gas coils going 0 to 1 and staying (PR #153 review).
        """
        from btap._compat import sorted_by_name
        from btap.modeling.hvac.systems.furnace import Furnace

        model = load_fixture()
        zones = sorted_by_name(model.getThermalZones())
        before = (len(model.getAirLoopHVACs()), len(model.getFanConstantVolumes()),
                  len(model.getCoilHeatingGass()))
        config = {'name': 'probe', 'heating': True, 'reheat': 'Hot Water',
                  'per_zone': True}
        with self.assertRaises(ValueError):
            Furnace(config).preflight(model, zones, control_zone=zones[0])
        after = (len(model.getAirLoopHVACs()), len(model.getFanConstantVolumes()),
                 len(model.getCoilHeatingGass()))
        self.assertEqual(before, after,
                         'a refusal must not leave a half-built system behind')

    # ------------------------------------------------------------------ #5
    def test_the_PTAC_heating_section_can_be_ACTIVE_water(self):
        """Requirement 5. The NECB port deliberately disables that section;
        a Campus Office PTAC really heats, so it must be switchable."""
        model, zones, _ = self._build(
            'PSZ MAU Hot Water with water-heated PTAC')
        ptacs = model.getZoneHVACPackagedTerminalAirConditioners()
        self.assertEqual(len(zones), len(ptacs))
        for ptac in ptacs:
            with self.subTest(ptac=ptac.nameString()):
                self.assertTrue(
                    ptac.heatingCoil().to_CoilHeatingWater().is_initialized(),
                    'the heating section must be a water coil, not the '
                    'always-off electric one')
        self.assertEqual(0, len(model.getCoilHeatingElectrics()),
                         'no always-off electric sections remain')
        self.assertEqual(0, len(model.getZoneHVACBaseboardConvectiveWaters())
                         + len(model.getZoneHVACBaseboardConvectiveElectrics()),
                         'optional baseboards: the row omits baseboard_type, '
                         'which baseboards.add already reads as "none"')

    def test_the_SHIPPED_mau_ptac_rows_keep_a_DISABLED_section(self):
        """Behaviour preservation: `ptac_heating_type` defaults to None."""
        model, zones, _ = self._build(
            'PSZ MAU Hot Water and DX Coils and Hot Water Baseboard '
            'with PTAC')
        ptacs = model.getZoneHVACPackagedTerminalAirConditioners()
        self.assertEqual(len(zones), len(ptacs))
        for ptac in ptacs:
            with self.subTest(ptac=ptac.nameString()):
                self.assertTrue(
                    ptac.heatingCoil().to_CoilHeatingElectric()
                    .is_initialized(),
                    'the NECB port requires the always-off electric section')
        self.assertTrue(model.getZoneHVACBaseboardConvectiveWaters(),
                        'and this row does have baseboards')

    # ------------------------------------------- behaviour preservation
    def test_the_SHIPPED_furnace_row_is_unchanged(self):
        """`per_zone` and `heating_type` default so an existing row is intact.

        `furnace.py` defaults `per_zone` TRUE, unlike `psz` where shared is the
        default, precisely because this row has always built per zone.
        Preserving a shipped row outranks consistency between families.
        """
        model, zones, result = self._build('Forced air furnace')
        self.assertEqual(len(zones), len(result.air_loops), 'still per zone')
        self.assertEqual(len(zones), len(model.getCoilHeatingGass()),
                         'still a GAS coil — heating_type defaults to Gas')
        self.assertEqual(0, len(model.getCoilHeatingWaters()))
        self.assertEqual(0, len(model.getCoilCoolingDXSingleSpeeds()))

    def test_every_furnace_and_unit_heater_name_is_DISTINCT(self):
        """`catalog.py` raises on a canonical collision, so a shared row that
        still read "per-zone" could not be added at all. That guard is what
        forces the scope word into the name; this asserts it stayed honest."""
        rows = [r for r in modeling.systems()
                if r['family'] in ('furnace', 'unit_heaters')]
        canon = [r['canonical_name'] for r in rows]
        self.assertEqual(len(canon), len(set(canon)), f'collision in {canon}')
        by_name = {r['name']: r['canonical_name'] for r in rows}
        self.assertEqual('per-zone gas furnace',
                         by_name['Forced air furnace'],
                         'the shipped name must not drift')
        self.assertIn('shared',
                      by_name['Shared hot water heating-only air handler'])
        self.assertIn('hot water',
                      by_name['Hot water unit heaters'])


if __name__ == '__main__':
    unittest.main()
