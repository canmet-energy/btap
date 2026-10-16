import unittest

import btap.modeling as modeling
from tests.support import load_fixture, needs_sdk

RADIANT = (
    'DOAS with hydronic radiant floors, gas boiler and air-cooled chiller')
REPLACEMENT = 'PSZ RTU Electric and DX Coils and Electric Baseboard'


@needs_sdk
class TestRadiantFloor(unittest.TestCase):
    def fixture(self, limit=None):
        from btap._compat import sorted_by_name

        model = load_fixture()
        zones = sorted_by_name(model.getThermalZones())
        return model, zones if limit is None else zones[:limit]

    def floors(self, zones):
        return [
            surface
            for zone in zones
            for space in zone.spaces()
            for surface in space.surfaces()
            if surface.surfaceType() == 'Floor'
        ]

    def test_object_graph_internal_sources_and_translation(self):
        import openstudio

        from btap.modeling.hvac.systems import plant_loops

        model, zones = self.fixture(limit=2)
        untouched_zone = sorted(
            model.getThermalZones(), key=lambda zone: zone.nameString())[2]
        untouched_floor = self.floors([untouched_zone])[0]
        untouched_construction = untouched_floor.construction().get().handle()
        original_floor = self.floors(zones)[0]
        original_construction = (
            original_floor.construction().get().to_Construction().get())
        original_layers = [
            layer.handle() for layer in original_construction.layers()
        ]
        original_conductance = (
            original_construction.thermalConductance().get())

        result = modeling.build_system(model, RADIANT, zones)

        self.assertEqual('radiant', result.family)
        self.assertEqual(1, len(result.air_loops))
        self.assertEqual(
            len(zones), len(model.getZoneHVACLowTempRadiantVarFlows()))
        self.assertEqual(
            len(zones), len(model.getCoilHeatingLowTempRadiantVarFlows()))
        self.assertEqual(
            len(zones), len(model.getCoilCoolingLowTempRadiantVarFlows()))
        self.assertEqual(
            len(zones), len(model.getZoneHVACPackagedTerminalAirConditioners()))
        self.assertEqual(
            len(zones) + 1, len(model.getCoilCoolingDXSingleSpeeds()))
        self.assertEqual(
            len(zones), len(model.getZoneHVACBaseboardConvectiveWaters()))
        self.assertEqual(
            len(zones), len(model.getCoilHeatingWaterBaseboards()))
        self.assertEqual(
            len(zones),
            len(model.getAirTerminalSingleDuctConstantVolumeNoReheats()))

        for surface in self.floors(zones):
            internal = (
                surface.construction().get()
                .to_ConstructionWithInternalSource())
            self.assertTrue(internal.is_initialized())
            construction = internal.get()
            self.assertEqual(1, construction.sourcePresentAfterLayerNumber())
            self.assertEqual(
                1, construction.temperatureCalculationRequestedAfterLayerNumber())
            self.assertAlmostEqual(0.2, construction.tubeSpacing())
            self.assertEqual(
                original_layers,
                [layer.handle() for layer in construction.layers()],
                'radiant conversion must preserve the slab layer stack')
            self.assertAlmostEqual(
                original_conductance,
                construction.thermalConductance().get(),
                places=9,
                msg='radiant conversion must preserve slab conductance')
        self.assertEqual(
            untouched_construction,
            untouched_floor.construction().get().handle(),
            'an unselected zone keeps its shared original construction')

        for radiant in model.getZoneHVACLowTempRadiantVarFlows():
            self.assertTrue(radiant.radiantSurfaceType().is_initialized())
            self.assertEqual(
                'Floors', radiant.radiantSurfaceType().get())
            self.assertEqual('MeanAirTemperature',
                             radiant.temperatureControlType())
            self.assertTrue(radiant.isHydronicTubingLengthAutosized())
            self.assertTrue(radiant.surfaces())
        for coil in model.getCoilCoolingLowTempRadiantVarFlows():
            self.assertEqual('VariableOff', coil.condensationControlType())
            self.assertEqual(2.0, coil.condensationControlDewpointOffset())

        profiles = [
            plant_loops.temperature_profile(loop)
            for loop in model.getPlantLoops()
            if plant_loops.temperature_profile(loop) is not None
        ]
        self.assertEqual(
            ['low_temperature_heating', 'tempered_chilled_water'],
            sorted(profile['name'] for profile in profiles))
        always_off = model.alwaysOffDiscreteSchedule()
        for unit in model.getZoneHVACPackagedTerminalAirConditioners():
            heating = unit.heatingCoil().to_CoilHeatingElectric()
            self.assertTrue(heating.is_initialized())
            self.assertEqual(
                always_off.handle(),
                heating.get().availabilitySchedule().handle())
            self.assertEqual(
                always_off.handle(),
                unit.supplyAirFanOperatingModeSchedule().handle())
            self.assertEqual(
                1.0e-5,
                unit.outdoorAirFlowRateDuringCoolingOperation().get())
            self.assertEqual(
                1.0e-5,
                unit.outdoorAirFlowRateDuringHeatingOperation().get())
            self.assertEqual(
                1.0e-5,
                unit.outdoorAirFlowRateWhenNoCoolingorHeatingisNeeded().get())
        hot_loop = next(
            loop for loop in model.getPlantLoops()
            if (
                plant_loops.temperature_profile(loop) or {}
            ).get('name') == 'low_temperature_heating')
        self.assertTrue(all(
            coil.plantLoop().is_initialized()
            and coil.plantLoop().get().handle() == hot_loop.handle()
            for coil in model.getCoilHeatingWaterBaseboards()))
        self.assertEqual(1, len(model.getChillerElectricEIRs()))

        workspace = openstudio.energyplus.ForwardTranslator().translateModel(
            model)
        self.assertEqual(
            len(zones),
            len(workspace.getObjectsByType(openstudio.IddObjectType(
                'ZoneHVAC:LowTemperatureRadiant:VariableFlow'))))
        self.assertEqual(
            1,
            len(workspace.getObjectsByType(openstudio.IddObjectType(
                'ConstructionProperty:InternalHeatSource'))))
        self.assertEqual(
            len(zones),
            len(workspace.getObjectsByType(openstudio.IddObjectType(
                'ZoneHVAC:PackagedTerminalAirConditioner'))))

    def test_invalid_controls_fail_before_existing_hvac_is_removed(self):
        model, zones = self.fixture(limit=2)
        modeling.build_system(model, REPLACEMENT, zones)
        before = {str(obj.handle()) for obj in model.modelObjects()}

        with self.assertRaisesRegex(
                ValueError, 'outside_diameter must exceed'):
            modeling.build_system(
                model, RADIANT, zones, remove_existing=True,
                config={'radiant_tubing_outside_diameter': 0.01})

        self.assertEqual(
            before, {str(obj.handle()) for obj in model.modelObjects()})

    def test_adjacent_floor_is_rejected_before_mutation(self):
        import openstudio

        model, zones = self.fixture(limit=1)
        floor = self.floors(zones)[0]
        adjacent_space = openstudio.model.Space(model)
        adjacent_space.setName('Unselected Adjacent Space')
        adjacent_zone = openstudio.model.ThermalZone(model)
        adjacent_space.setThermalZone(adjacent_zone)
        opposite = openstudio.model.Surface(
            list(reversed(floor.vertices())), model)
        opposite.setName('Unselected Adjacent Ceiling')
        opposite.setSurfaceType('RoofCeiling')
        opposite.setSpace(adjacent_space)
        opposite.setConstruction(floor.construction().get())
        floor.setAdjacentSurface(opposite)
        before = {str(obj.handle()) for obj in model.modelObjects()}

        with self.assertRaisesRegex(ValueError, 'adjacent to another space'):
            modeling.build_system(model, RADIANT, zones)

        self.assertEqual(
            before, {str(obj.handle()) for obj in model.modelObjects()})

    def test_subset_replacement_restores_only_builder_owned_surfaces(self):
        import openstudio

        model, zones = self.fixture(limit=2)
        floors = self.floors(zones)
        originals = {
            surface.handle(): surface.construction().get().handle()
            for surface in floors
        }
        modeling.build_system(model, RADIANT, zones)

        caller_material = openstudio.model.MasslessOpaqueMaterial(model)
        caller_material.setThermalResistance(1.5)
        caller_construction = openstudio.model.Construction(model)
        caller_construction.setName('Caller Replacement Floor')
        caller_construction.setLayers([caller_material])
        floors[0].setConstruction(caller_construction)

        modeling.build_system(
            model, REPLACEMENT, [zones[0]], remove_existing=True)
        self.assertEqual(
            caller_construction.handle(),
            floors[0].construction().get().handle(),
            'a later caller construction edit is not overwritten')
        self.assertEqual(
            1, len(model.getZoneHVACLowTempRadiantVarFlows()))
        self.assertEqual(1, len(
            model.getZoneHVACPackagedTerminalAirConditioners()))
        self.assertEqual(
            1, len(model.getZoneHVACBaseboardConvectiveWaters()))
        self.assertEqual(
            1, len(model.getConstructionWithInternalSources()))
        self.assertEqual(2, len(model.getEnergyManagementSystemSensors()))

        modeling.build_system(
            model, REPLACEMENT, [zones[1]], remove_existing=True)
        self.assertEqual(
            originals[floors[1].handle()],
            floors[1].construction().get().handle())
        self.assertEqual(
            0, len(model.getZoneHVACLowTempRadiantVarFlows()))
        self.assertEqual(
            0, len(model.getCoilHeatingLowTempRadiantVarFlows()))
        self.assertEqual(
            0, len(model.getCoilCoolingLowTempRadiantVarFlows()))
        self.assertEqual(
            0, len(model.getZoneHVACPackagedTerminalAirConditioners()))
        self.assertEqual(
            0, len(model.getZoneHVACBaseboardConvectiveWaters()))
        self.assertEqual(0, len(model.getCoilHeatingWaterBaseboards()))
        self.assertEqual(0, len(model.getChillerElectricEIRs()))
        self.assertEqual(0, len(model.getConstructionWithInternalSources()))

    def test_foreign_radiant_topology_is_classified_structurally(self):
        model, zones = self.fixture(limit=2)
        result = modeling.build_system(model, RADIANT, zones)
        result.air_loops[0].setName('Imported Radiant DOAS')

        facts = modeling.characterize(model)
        group = next(group for group in facts['zone_groups']
                     if group['air_loop'] == 'Imported Radiant DOAS')
        self.assertIsNone(group['catalog_name'])
        self.assertEqual('radiant_floor', group['family_guess'])
        self.assertIn('radiant_floor', group['zonal_units'])
        self.assertTrue(group['heated'])
        self.assertTrue(group['cooled'])
        self.assertIn('NaturalGas', group['heating_energy_types'])
        self.assertIn('Electricity', group['cooling_energy_types'])

    def test_prescriptive_envelope_pass_preserves_internal_source(self):
        from btap.audit import AuditLog
        from btap.codes.necb.envelope import apply_prescriptive

        model, zones = self.fixture(limit=1)
        modeling.build_system(model, RADIANT, zones)
        floor = self.floors(zones)[0]
        before = floor.construction().get().handle()
        audit = AuditLog()

        apply_prescriptive(
            model, code='necb2020', hdd=7000.0, audit=audit)

        self.assertEqual(before, floor.construction().get().handle())
        self.assertTrue(
            floor.construction().get()
            .to_ConstructionWithInternalSource().is_initialized())
        self.assertTrue(any(
            entry['target'] == floor.nameString()
            and 'no layered construction' in entry['action']
            for entry in audit.warnings))


if __name__ == '__main__':
    unittest.main()
