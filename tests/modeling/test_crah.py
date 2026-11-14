"""The cooling-only computer-room air handler (#152 requirement 6).

The two properties that make a CRAH a CRAH are both ABSENCES — no heating coil
and no outdoor-air system — so each is asserted as a count of zero rather than
by the presence of something else. An absence is exactly what a wrong default
restores quietly.
"""

import unittest

import openstudio

from btap.modeling import build_system
from btap.modeling.hvac import catalog
from btap.modeling.hvac.systems.crah import Crah
from tests.necb.hvac_helpers import load_fixture, sorted_zones

ROW = 'Recirculating CRAH chilled water with humidity control'


def _humidity_managers(model):
    return [s for s in model.getSetpointManagerScheduleds()
            if s.controlVariable() == 'MaximumHumidityRatio']


class TestCrahTopology(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.model = load_fixture()
        build_system(cls.model, ROW, sorted_zones(cls.model))

    def test_one_shared_loop_serves_every_zone(self):
        loops = self.model.getAirLoopHVACs()
        self.assertEqual(1, len(loops))
        self.assertEqual(5, len(loops[0].thermalZones()))

    def test_cooling_is_a_CHILLED_WATER_coil_on_a_chiller_plant(self):
        self.assertEqual(1, len(self.model.getCoilCoolingWaters()))
        self.assertEqual(0, len(self.model.getCoilCoolingDXSingleSpeeds()))
        self.assertEqual(1, len(self.model.getChillerElectricEIRs()))

    def test_it_is_COOLING_ONLY___no_heating_coil_of_any_kind(self):
        """The defining absence. A furnace or reheat coil arriving by default
        would make this an ordinary air handler that happens to dehumidify."""
        self.assertEqual(0, len(self.model.getCoilHeatingGass()))
        self.assertEqual(0, len(self.model.getCoilHeatingElectrics()))
        self.assertEqual(0, len(self.model.getCoilHeatingWaters()))
        self.assertEqual(
            0, len(self.model.getZoneHVACBaseboardConvectiveWaters()),
            'and no zonal heating either')

    def test_it_RECIRCULATES___no_outdoor_air_system(self):
        """The second defining absence, and the inversion from a DOAS: a CRAH
        conditions ROOM air, where a DOAS conditions 100% outdoor air."""
        self.assertEqual(0, len(self.model.getAirLoopHVACOutdoorAirSystems()))


class TestHumidityControl(unittest.TestCase):
    def setUp(self):
        self.model = load_fixture()
        build_system(self.model, ROW, sorted_zones(self.model))

    def test_the_humidity_ceiling_exists_and_carries_the_rows_value(self):
        managers = _humidity_managers(self.model)
        self.assertEqual(1, len(managers))
        schedule = managers[0].schedule().to_ScheduleConstant()
        self.assertTrue(schedule.is_initialized())
        self.assertAlmostEqual(
            catalog.resolve(ROW)['crah_maximum_humidity_ratio'],
            schedule.get().value(), places=6)

    def test_the_manager_sits_on_the_COOLING_COILS_OWN_air_outlet(self):
        """Necessary, and NOT sufficient — see the translated-field test below.

        The manager has to control the coil's own air outlet. On the loop
        outlet it would sit downstream of the only component that can act on
        it, and on a water-to-air coil the air side is reached by
        `airOutletModelObject` — the water side would put the ceiling on a
        WATER node.
        """
        coil = self.model.getCoilCoolingWaters()[0]
        air_outlet = coil.airOutletModelObject()
        self.assertTrue(air_outlet.is_initialized())

        node = _humidity_managers(self.model)[0].setpointNode()
        self.assertTrue(node.is_initialized())
        self.assertEqual(air_outlet.get().nameString(), node.get().nameString())

        loop_outlet = self.model.getAirLoopHVACs()[0].supplyOutletNode()
        self.assertNotEqual(
            loop_outlet.nameString(), node.get().nameString(),
            'the loop outlet is the plausible wrong node, so it is named here')


class TestCrahRefusals(unittest.TestCase):
    """Refused in `preflight`, which runs BEFORE any existing HVAC is removed."""

    def _crah(self, **overrides):
        config = dict(catalog.resolve(ROW), **overrides)
        return Crah(config)

    def test_an_unknown_cooling_type_is_refused(self):
        with self.assertRaises(ValueError) as caught:
            self._crah(cooling_type='Evaporative').preflight(
                load_fixture(), [])
        self.assertIn('Evaporative', str(caught.exception))

    def test_an_out_of_range_humidity_ratio_is_refused(self):
        for bad in (0.0005, 0.05):
            with self.subTest(ratio=bad):
                with self.assertRaises(ValueError):
                    self._crah(crah_maximum_humidity_ratio=bad).preflight(
                        load_fixture(), [])

    def test_an_out_of_range_supply_temperature_is_refused(self):
        for bad in (2.0, 40.0):
            with self.subTest(temp=bad):
                with self.assertRaises(ValueError):
                    self._crah(crah_supply_air_temperature=bad).preflight(
                        load_fixture(), [])

    def test_hydronic_cooling_without_a_chilled_water_loop_is_refused(self):
        """`needs_chiller` is what provisions the loop, so a row that asks for
        hydronic cooling and forgets it must fail loudly rather than build an
        unconnected coil that autosizes to nothing."""
        model = load_fixture()
        with self.assertRaises(ValueError) as caught:
            self._crah().build(model, sorted_zones(model), chw_loop=None)
        self.assertIn('needs_chiller', str(caught.exception))


class TestTheCeilingACTUALLYCONTROLSTheCoil(unittest.TestCase):
    """The defect the node assertion could not see.

    EnergyPlus reads a maximum-humidity-ratio setpoint only when the COIL's
    controller is told to track it. `Controller:WaterCoil` defaults to
    `Temperature`, so a correctly placed manager leaves the coil meeting the
    sensible load alone and the ceiling inert. Nothing reports that: an unused
    node setpoint is not a Severe, and the model is otherwise valid, so the
    catalogue sizing gate passes it.

    This reads the TRANSLATED object rather than the OpenStudio one, because
    the translated field is what EnergyPlus actually obeys (Fable, PR #153).
    """

    def test_the_translated_water_controller_tracks_HUMIDITY_not_just_temperature(self):
        model = load_fixture()
        build_system(model, ROW, sorted_zones(model))
        workspace = openstudio.energyplus.ForwardTranslator().translateModel(model)

        controllers = workspace.getObjectsByType(
            openstudio.IddObjectType('Controller:WaterCoil'))
        self.assertTrue(controllers, 'the chilled-water coil has a controller')
        variables = {c.getString(1).get() for c in controllers
                     if c.getString(1).is_initialized()}
        self.assertIn(
            'TemperatureAndHumidityRatio', variables,
            'the humidity ceiling is inert unless the controller tracks it; '
            f'control variables present: {sorted(variables)}')


class TestDxIsRefused(unittest.TestCase):
    """A cooling-only DX CRAH cannot hold a humidity ceiling at all.

    EnergyPlus delivers DX dehumidification through `CoolReheat`, which needs a
    REHEAT coil this system does not have. Building it would attach a setpoint
    manager that EnergyPlus ignores, which is the inert ceiling in a different
    costume, so the combination is refused rather than shipped.
    """

    def test_a_DX_row_is_refused_in_preflight(self):
        config = dict(catalog.resolve(ROW), cooling_type='DX')
        with self.assertRaises(ValueError) as caught:
            Crah(config).preflight(load_fixture(), [])
        message = str(caught.exception)
        self.assertIn('DX', message)
        self.assertIn('cooling-only', message,
                      'the message says WHY, not just that it is unsupported')


if __name__ == '__main__':
    unittest.main()
