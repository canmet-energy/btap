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


def _loop(model, name):
    return next(loop for loop in model.getPlantLoops()
                if loop.nameString() == name)


def _zone(model):
    return model.getThermalZones()[0]


def _add_fan_coil(model, chilled):
    import openstudio

    always_on = model.alwaysOnDiscreteSchedule()
    cooling = openstudio.model.CoilCoolingWater(model, always_on)
    heating = openstudio.model.CoilHeatingWater(model, always_on)
    assert chilled.addDemandBranchForComponent(cooling)
    assert _loop(model, 'Hot Water').addDemandBranchForComponent(heating)
    fan = openstudio.model.FanConstantVolume(model, always_on)
    unit = openstudio.model.ZoneHVACFourPipeFanCoil(
        model, always_on, fan, cooling, heating)
    assert unit.addToThermalZone(_zone(model))
    return unit


def _add_internal_loop_zone_heat_pump(model):
    import openstudio

    source = _plant(model, 'Internal WSHP Source', 'Condenser')
    heating = openstudio.model.CoilHeatingWaterToAirHeatPumpEquationFit(model)
    cooling = openstudio.model.CoilCoolingWaterToAirHeatPumpEquationFit(model)
    assert source.addDemandBranchForComponent(heating)
    assert source.addDemandBranchForComponent(cooling)
    fan = openstudio.model.FanOnOff(model)
    supplemental = openstudio.model.CoilHeatingElectric(
        model, model.alwaysOnDiscreteSchedule())
    unit = openstudio.model.ZoneHVACWaterToAirHeatPump(
        model, model.alwaysOnDiscreteSchedule(), fan, heating, cooling,
        supplemental)
    assert unit.addToThermalZone(_zone(model))
    return unit


def _add_internal_loop_heating_plant_heat_pump(model):
    import openstudio

    source = _plant(model, 'Internal Heating HP Source', 'Condenser')
    unit = openstudio.model.HeatPumpWaterToWaterEquationFitHeating(model)
    unit.setName('Internal-loop Heating HP')
    assert _loop(model, 'Hot Water').addSupplyBranchForComponent(unit)
    assert source.addDemandBranchForComponent(unit)
    return unit


def _add_unclassified_heating_plant_heat_pump(model):
    import openstudio

    unit = openstudio.model.HeatPumpWaterToWaterEquationFitHeating(model)
    unit.setName('Unclassified Heating HP')
    assert _loop(model, 'Hot Water').addSupplyBranchForComponent(unit)
    return unit


def _add_paired_water_loop_cooling_heat_pump(model):
    import openstudio

    chilled = _loop(model, 'Chilled Water')
    source = _plant(model, 'Paired HP Source', 'Condenser')
    heating_loop = _plant(model, 'Paired HP Heating', 'Heating')
    cooling = openstudio.model.HeatPumpPlantLoopEIRCooling(model)
    cooling.setName('Paired Water-loop Cooling HP')
    heating = openstudio.model.HeatPumpPlantLoopEIRHeating(model)
    heating.setName('Paired Water-loop Heating HP')
    assert chilled.addSupplyBranchForComponent(cooling)
    assert source.addDemandBranchForComponent(cooling)
    assert cooling.setCondenserType('WaterSource')
    assert heating_loop.addSupplyBranchForComponent(heating)
    assert source.addDemandBranchForComponent(heating)
    assert heating.setCondenserType('WaterSource')
    assert cooling.setCompanionHeatingHeatPump(heating)
    return cooling


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
                        [{'name': 'Cooling Equipment', 'source': 'air'}],
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

    def test_internal_loop_zone_hp_does_not_hide_a_decisive_unpaired_source(self):
        import openstudio

        model, _cooling = _model(
            'zonal', openstudio.model.HeatPumpPlantLoopEIRCooling)
        _add_internal_loop_zone_heat_pump(model)

        facts, assignments, audit = _select(model)
        self.assertEqual(
            [['Zone']], [group['zones'] for group in facts['zone_groups']],
            'precondition: both contributors serve the same selection group')
        group = facts['zone_groups'][0]
        self.assertCountEqual(
            ['air', 'water_loop'], group['heat_pump_sources'])
        self.assertTrue(group['resolved_heat_pump'])
        self.assertEqual(
            ['water_loop'], group['resolved_heat_pump_sources'],
            'precondition: without the unpaired air-source object, the '
            'resolved zone heat pump keeps Table -A')
        self.assertEqual('hp', assignments[0].reference_system)
        self.assertEqual(1, len(_ahj_25(audit)))

    def test_internal_loop_heating_hp_does_not_hide_a_decisive_unpaired_source(self):
        import openstudio

        model, _cooling = _model(
            'zonal', openstudio.model.HeatPumpPlantLoopEIRCooling)
        _add_internal_loop_heating_plant_heat_pump(model)

        facts, assignments, audit = _select(model)
        self.assertEqual(
            [['Zone']], [group['zones'] for group in facts['zone_groups']],
            'precondition: both contributors serve the same selection group')
        group = facts['zone_groups'][0]
        self.assertCountEqual(
            ['air', 'water_loop'], group['heat_pump_sources'])
        self.assertTrue(group['resolved_heat_pump'])
        self.assertEqual(
            ['water_loop'], group['resolved_heat_pump_sources'],
            'precondition: without the unpaired air-source object, the '
            'resolved heating heat pump keeps Table -A')
        self.assertEqual('hp', assignments[0].reference_system)
        self.assertEqual(1, len(_ahj_25(audit)))

    def test_sources_are_attributed_per_contributor_on_one_plant(self):
        import openstudio

        model, _cooling = _model(
            'zonal', openstudio.model.HeatPumpPlantLoopEIRCooling)
        _add_paired_water_loop_cooling_heat_pump(model)

        facts, assignments, audit = _select(model)
        group = facts['zone_groups'][0]
        self.assertCountEqual(
            ['air', 'water_loop'], group['heat_pump_sources'])
        self.assertEqual(
            ['water_loop'], group['resolved_heat_pump_sources'],
            'the paired contributor keeps its own source even when an '
            'unpaired air-source object shares the load plant')
        self.assertEqual(
            [{'name': 'Cooling Equipment', 'source': 'air'}],
            group['unpaired_cooling_plant_heat_pumps'])
        self.assertEqual('hp', assignments[0].reference_system)
        self.assertEqual(1, len(_ahj_25(audit)))

    def test_an_unclassified_unpaired_source_remains_decisive(self):
        import openstudio

        model, _cooling = _model(
            'zonal',
            openstudio.model.HeatPumpWaterToWaterEquationFitCooling)
        _add_internal_loop_zone_heat_pump(model)

        facts, assignments, audit = _select(model)
        group = facts['zone_groups'][0]
        self.assertEqual(['water_loop'], group['heat_pump_sources'])
        self.assertTrue(group['heat_pump_source_unclassified'])
        self.assertEqual(
            [{'name': 'Cooling Equipment', 'source': None}],
            group['unpaired_cooling_plant_heat_pumps'])
        self.assertEqual('hp', assignments[0].reference_system)
        self.assertEqual(1, len(_ahj_25(audit)))

    def test_an_unclassified_resolved_source_elects_without_the_unpaired_one(self):
        import openstudio

        model, _cooling = _model(
            'zonal', openstudio.model.HeatPumpPlantLoopEIRCooling)
        _add_internal_loop_zone_heat_pump(model)
        _add_unclassified_heating_plant_heat_pump(model)

        facts, assignments, audit = _select(model)
        group = facts['zone_groups'][0]
        self.assertEqual(['water_loop'], group['resolved_heat_pump_sources'])
        self.assertTrue(group['resolved_heat_pump_source_unclassified'])
        self.assertEqual('hp', assignments[0].reference_system)
        self.assertEqual(
            [], _ahj_25(audit),
            'resolved unclassified evidence conservatively redirects even '
            'without the unpaired cooling contributor')

    def test_a_heating_companion_establishes_heat_pump_identity(self):
        import openstudio

        model, cooling = _model(
            'zonal', openstudio.model.HeatPumpPlantLoopEIRCooling,
            paired=True)
        self.assertTrue(cooling.companionHeatingHeatPump().is_initialized())

        facts, assignments, audit = _select(model)
        group = facts['zone_groups'][0]
        self.assertTrue(
            group['resolved_heat_pump'],
            'the modeled companion declares reversible package capability '
            'even though its heating loop has no demand equipment')
        self.assertEqual(['air'], group['resolved_heat_pump_sources'])
        self.assertEqual('hp', assignments[0].reference_system)
        self.assertEqual([], _ahj_25(audit))

    def test_a_resolved_air_contributor_controls_the_shared_source_value(self):
        import openstudio

        model, _cooling = _model(
            'zonal', openstudio.model.HeatPumpPlantLoopEIRCooling)
        paired_loop, _paired = _cooling_plant(
            model, openstudio.model.HeatPumpPlantLoopEIRCooling, paired=True)
        _add_fan_coil(model, paired_loop)

        facts, assignments, audit = _select(model)
        group = facts['zone_groups'][0]
        self.assertEqual(
            ['air'], group['heat_pump_sources'],
            'source values are de-duplicated even though two contributors '
            'supplied them')
        self.assertEqual(['air'], group['resolved_heat_pump_sources'])
        self.assertEqual(1, len(group['unpaired_cooling_plant_heat_pumps']))
        self.assertEqual('hp', assignments[0].reference_system)
        self.assertEqual(
            [], _ahj_25(audit),
            'the paired air-source contributor elects the same reference '
            'without the unpaired contributor')

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
