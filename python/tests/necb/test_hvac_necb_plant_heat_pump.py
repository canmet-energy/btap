import unittest
from types import SimpleNamespace

from tests.support import needs_sdk


def _plant(model, name, loop_type):
    import openstudio

    loop = openstudio.model.PlantLoop(model)
    loop.setName(name)
    loop.sizingPlant().setLoopType(loop_type)
    return loop


def _cooling_plant(model, equipment, *, source='air', paired=False):
    import openstudio

    chilled = _plant(model, 'Chilled Water', 'Cooling')
    unit = equipment(model)
    unit.setName('Cooling Equipment')
    assert chilled.addSupplyBranchForComponent(unit)

    if unit.to_HeatPumpPlantLoopEIRCooling().is_initialized():
        heat_pump = unit.to_HeatPumpPlantLoopEIRCooling().get()
        if source == 'water_loop':
            source_loop = _plant(model, 'Internal Source Loop', 'Condenser')
            assert source_loop.addDemandBranchForComponent(heat_pump)
            assert heat_pump.setCondenserType('WaterSource')
        else:
            assert heat_pump.setCondenserType('AirSource')

        if paired:
            unused = _plant(model, 'Companion Heating Loop', 'Heating')
            heating = openstudio.model.HeatPumpPlantLoopEIRHeating(model)
            assert heating.setCondenserType('AirSource')
            assert unused.addSupplyBranchForComponent(heating)
            assert heat_pump.setCompanionHeatingHeatPump(heating)
    return chilled, unit


def _model(route, equipment, *, source='air', paired=False):
    import openstudio

    model = openstudio.model.Model()
    zone = openstudio.model.ThermalZone(model)
    zone.setName('Zone')
    always_on = model.alwaysOnDiscreteSchedule()

    hot = _plant(model, 'Hot Water', 'Heating')
    boiler = openstudio.model.BoilerHotWater(model)
    assert boiler.setFuelType('NaturalGas')
    assert hot.addSupplyBranchForComponent(boiler)

    chilled, cooling_equipment = _cooling_plant(
        model, equipment, source=source, paired=paired)
    cooling = openstudio.model.CoilCoolingWater(model, always_on)
    heating = openstudio.model.CoilHeatingWater(model, always_on)
    assert chilled.addDemandBranchForComponent(cooling)
    assert hot.addDemandBranchForComponent(heating)

    if route == 'zonal':
        fan = openstudio.model.FanConstantVolume(model, always_on)
        fan_coil = openstudio.model.ZoneHVACFourPipeFanCoil(
            model, always_on, fan, cooling, heating)
        assert fan_coil.addToThermalZone(zone)
    else:
        air_loop = openstudio.model.AirLoopHVAC(model)
        fan = openstudio.model.FanConstantVolume(model, always_on)
        node = air_loop.supplyOutletNode()
        assert fan.addToNode(node)
        assert cooling.addToNode(node)
        assert heating.addToNode(node)
        terminal = (
            openstudio.model.AirTerminalSingleDuctConstantVolumeNoReheat(
                model, always_on))
        assert air_loop.addBranchForZone(zone, terminal)

    return model, cooling_equipment


def _select(model, code='necb2020'):
    from btap.audit import AuditLog
    from btap.codes.necb import hvac
    from btap.modeling.hvac import classify

    audit = AuditLog()
    facts = classify.characterize(model)
    assignments = list(hvac.select_reference_systems(
        facts=facts,
        building={'storeys': 1, 'zone_types': {'Zone': 'Office'}},
        code=code,
        audit=audit))
    return facts, assignments, audit


def _ahj_25(audit):
    return [entry for entry in audit.entries if entry.get('ahj') == 'AHJ-25']


@needs_sdk
class TestCoolingOnlyPlantHeatPumpArticle13Identity(unittest.TestCase):
    def test_both_serving_routes_keep_the_conservative_redirect_and_cite(self):
        import openstudio

        for route in ('zonal', 'air_loop'):
            for code, article in (
                    ('necb2020', '8.4.4.13.(2)(a)'),
                    ('necb2025', '8.4.5.13.(2)(a)')):
                with self.subTest(route=route, code=code):
                    model, heat_pump = _model(
                        route, openstudio.model.HeatPumpPlantLoopEIRCooling)
                    self.assertFalse(
                        heat_pump.companionHeatingHeatPump().is_initialized(),
                        'precondition: the equipment has no modeled heating '
                        'side')

                    facts, assignments, audit = _select(model, code)
                    group = facts['zone_groups'][0]
                    self.assertEqual(
                        ['NaturalGas'], group['heating_energy_types'],
                        'the proposed heating service is the gas boiler')
                    self.assertEqual(['air'], group['heat_pump_sources'])
                    self.assertEqual(
                        ['Cooling Equipment'],
                        group['unpaired_cooling_plant_heat_pumps'])
                    self.assertEqual('hp', assignments[0].reference_system)

                    citations = _ahj_25(audit)
                    self.assertEqual(1, len(citations))
                    self.assertEqual(article, citations[0]['article'])
                    self.assertIn('UNRESOLVED', citations[0]['action'])

    def test_a_water_loop_source_keeps_table_selection_without_a_condition(self):
        import openstudio

        model, heat_pump = _model(
            'zonal', openstudio.model.HeatPumpPlantLoopEIRCooling,
            source='water_loop')
        self.assertEqual('WaterSource', heat_pump.condenserType())

        facts, assignments, audit = _select(model)
        group = facts['zone_groups'][0]
        self.assertEqual(['water_loop'], group['heat_pump_sources'])
        self.assertNotEqual('hp', assignments[0].reference_system)
        self.assertEqual(
            [], _ahj_25(audit),
            'both equipment readings retain the Table -A reference, so no '
            'approval condition applies')

    def test_a_heating_companion_establishes_heat_pump_identity(self):
        import openstudio

        model, cooling = _model(
            'zonal', openstudio.model.HeatPumpPlantLoopEIRCooling,
            paired=True)
        self.assertTrue(cooling.companionHeatingHeatPump().is_initialized())

        facts, assignments, audit = _select(model)
        group = facts['zone_groups'][0]
        self.assertTrue(group['heating_capable_plant_heat_pump'])
        self.assertEqual('hp', assignments[0].reference_system)
        self.assertEqual([], _ahj_25(audit))

    def test_plain_chillers_remain_controls_on_both_routes(self):
        import openstudio

        for route in ('zonal', 'air_loop'):
            with self.subTest(route=route):
                model, chiller = _model(
                    route, openstudio.model.ChillerElectricEIR)
                self.assertEqual('AirCooled', chiller.condenserType())

                facts, assignments, audit = _select(model)
                group = facts['zone_groups'][0]
                self.assertFalse(group['heat_pump'])
                self.assertEqual([], group['heat_pump_sources'])
                self.assertNotEqual('hp', assignments[0].reference_system)
                self.assertEqual([], _ahj_25(audit))

    def test_the_cited_interim_choice_makes_an_annual_result_conditional(self):
        import openstudio

        from btap.codes.necb import path

        model, _heat_pump = _model(
            'zonal', openstudio.model.HeatPumpPlantLoopEIRCooling)
        _facts, _assignments, audit = _select(model)
        run = SimpleNamespace(
            report={'annual': True, 'code': 'necb2020'},
            ruleset=SimpleNamespace(code='necb2020'))

        path._resolve_ahj_conditions(run, audit)

        self.assertEqual(
            'conditional', run.report['compliance_determination'])
        reason = run.report['compliance_determination_reason']
        self.assertIn('AHJ-25', reason['ahj_ids'])
        self.assertEqual(
            [('AHJ-25', 'Zone')],
            [(condition['id'], condition['target'])
             for condition in reason['conditions']
             if condition['id'] == 'AHJ-25'])


if __name__ == '__main__':      # pragma: no cover
    unittest.main()
