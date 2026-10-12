"""The SDK's DedicatedOutdoorAirSystem, and the three preconditions it hides.

`CentralDoas` is the first system in this catalogue to build
`AirLoopHVACDedicatedOutdoorAirSystem` — the SDK object, as distinct from the
`doas` family's 100% outdoor-air loop serving zones directly.

Everything asserted below about the SDK's requirements was MEASURED by
running it, and all three are invisible in process: the SDK accepts the wrong
arrangement and either EnergyPlus refuses it or the translator crashes. That
is the same shape as the defect
`test_system_simulation_status.py` guards — a field the SDK models as merely
absent — which is why those assertions live here rather than in a comment.
"""
import unittest

from tests.support import load_fixture, needs_sdk

NAME = 'Central DOAS with per-zone air loops'
WATER_NAME = 'Central DOAS with chilled-water precooling'


@needs_sdk
class TestCentralDoasBuilds(unittest.TestCase):
    def _build(self):
        import btap.modeling as modeling
        from btap._compat import sorted_by_name

        model = load_fixture()
        zones = sorted_by_name(model.getThermalZones())
        result = modeling.build_system(model, NAME, zones)
        return model, zones, result

    def test_one_dedicated_unit_feeds_every_zone_loop(self):
        model, zones, result = self._build()
        self.assertEqual(len(zones), len(result.air_loops),
                         'one air loop per zone, each with its own OA inlet '
                         'for the dedicated unit to feed')
        self.assertEqual('central_doas', result.family)

        units = model.getAirLoopHVACDedicatedOutdoorAirSystems()
        self.assertEqual(
            1, len(units),
            'ONE central unit — a per-loop unit would be an ordinary OA '
            'system and would not produce the graph this row exists for')
        self.assertEqual(
            len(result.air_loops), len(units[0].airLoops()),
            'the unit must feed every loop it was built for')

    def test_each_served_loop_has_its_OWN_outdoor_air_system(self):
        """A hard SDK precondition that fails as a CRASH, not an error.

        Without one on each served loop, the forward translator hits
        `BOOST_ASSERT: Assertion oas failed` and the process DUMPS CORE —
        no exception, no translator error, nothing to catch. Measured both
        ways on a two-zone model: without it the translator crashes, with it
        the model translates to 73 objects and zero errors.

        So this is not a style assertion. It is the difference between a
        model that can be simulated and one that kills the process reading
        it.
        """
        model, _zones, result = self._build()
        for air_loop in result.air_loops:
            with self.subTest(loop=air_loop.nameString()):
                own = [component for component in air_loop.supplyComponents()
                       if 'OutdoorAirSystem' in component.iddObject().name()]
                self.assertEqual(
                    1, len(own),
                    f'{air_loop.nameString()} is fed by the dedicated unit '
                    'and must still carry its own outdoor-air system; '
                    'without it the forward translator aborts the process')

    def test_the_preconditioning_order_is_outdoors_inward(self):
        """Preheat, then precool, then the fan — and the coil ends up deep.

        `addToNode(outboardOANode())` inserts at the outdoor-air inlet, so
        each component pushes the previous ones inboard and the LAST added
        is nearest the outdoors. The builder adds fan, precool, preheat, so
        the stream reads preheat/precool/fan from outdoors in: freeze
        protection first, then conditioning, then distribution.
        """
        model, _zones, _result = self._build()
        unit = model.getAirLoopHVACDedicatedOutdoorAirSystems()[0]
        stream = [component.iddObject().name()
                  for component in
                  unit.airLoopHVACOutdoorAirSystem().oaComponents()
                  if 'Node' not in component.iddObject().name()]
        self.assertEqual(
            ['OS:Coil:Heating:Electric',
             'OS:Coil:Cooling:DX:SingleSpeed',
             'OS:Fan:SystemModel'], stream,
            'outdoors inward: preheat, precool, fan')

    def test_the_fan_is_a_SYSTEM_model_because_EnergyPlus_refuses_others(self):
        """`Fan:ConstantVolume` is rejected, and only a run says so.

        "When AirLoopHVAC:OutdoorAirSystem:EquipmentList = DOAS SUPPLY FAN is
        used in AirLoopHVAC:DedicatedOutdoorAirSystem the FAN:CONSTANTVOLUME
        can not be used as a component. Please remove it." The SDK accepts
        it silently.
        """
        model, _zones, _result = self._build()
        self.assertEqual(
            1, len(model.getFanSystemModels()),
            'the dedicated unit needs a Fan:SystemModel; the constant- and '
            'variable-volume fans are refused by EnergyPlus in this '
            'position')

    def test_every_controlled_node_on_the_stream_has_a_setpoint(self):
        """One setpoint for the stream left the heating coil Fatal.

        EnergyPlus reads a setpoint at each coil's OWN outlet: "Missing
        temperature setpoint for heating coil ... use a Setpoint Manager to
        establish a setpoint at the coil temperature setpoint node". A
        manager on the stream's inboard end satisfied the DX coil's system
        and not the heating coil.
        """
        model, _zones, _result = self._build()
        unit = model.getAirLoopHVACDedicatedOutdoorAirSystems()[0]
        nodes = [component.to_Node().get()
                 for component in
                 unit.airLoopHVACOutdoorAirSystem().oaComponents()
                 if component.to_Node().is_initialized()]
        self.assertGreater(len(nodes), 1)
        managed = {manager.setpointNode().get().handle()
                   for manager in model.getSetpointManagerScheduleds()
                   if manager.setpointNode().is_initialized()}
        # The outdoor-air inlet itself is raw outdoor air with nothing to
        # control; every node inboard of it carries a coil's outlet.
        for node in nodes[1:]:
            with self.subTest(node=node.nameString()):
                self.assertIn(
                    node.handle(), managed,
                    'each controlled node needs its own setpoint manager, '
                    'or the coil at its inlet is uncontrolled and the run '
                    'is Fatal')

    def test_the_precool_coil_takes_a_PLANT_when_the_ROW_asks_for_one(self):
        """DX by default; a chilled-water plant when the row requests it.

        A `Coil:Cooling:Water` with no plant is accepted by the SDK and
        refused by EnergyPlus — "Missing required property
        'water_inlet_node_name'" and a Fatal — so the default row, which
        requests no chiller, must use DX.

        The water variant is a SECOND ROW with `needs_chiller`, because that
        flag is how the builder decides to create a chilled-water loop and
        pass it in. My first version took a `chw_loop=` keyword that
        `build_system` does not accept, which made the branch dead code no
        catalogue row could reach — the mirror image of a data field nothing
        reads.
        """
        import btap.modeling as modeling
        from btap._compat import sorted_by_name

        model = load_fixture()
        zones = sorted_by_name(model.getThermalZones())
        modeling.build_system(model, WATER_NAME, zones)

        water = [coil for coil in model.getCoilCoolingWaters()
                 if 'DOAS' in coil.nameString()]
        self.assertEqual(
            1, len(water),
            f'{WATER_NAME} must precool with a water coil')
        self.assertTrue(
            water[0].plantLoop().is_initialized(),
            'and the coil must actually be ON that loop — an unconnected '
            'water coil is what EnergyPlus refuses')
        self.assertEqual(
            0, len([coil for coil in model.getCoilCoolingDXSingleSpeeds()
                    if 'DOAS Precool' in coil.nameString()]),
            'the DX coil must be replaced, not left beside the water one')

    def test_the_DEFAULT_row_precools_with_DX_and_needs_no_plant(self):
        """The control for the case above, and the row that ships alone.

        Without it, "always build a water coil" would satisfy the test above
        while making the default row unsimulatable.
        """
        model, _zones, _result = self._build()
        self.assertEqual(
            1, len([coil for coil in model.getCoilCoolingDXSingleSpeeds()
                    if 'DOAS Precool' in coil.nameString()]),
            'the default row requests no chiller, so its precool coil must '
            'be DX')
        self.assertEqual(
            0, len([coil for coil in model.getCoilCoolingWaters()
                    if 'DOAS' in coil.nameString()]),
            'and no water coil may be left behind with no plant')
