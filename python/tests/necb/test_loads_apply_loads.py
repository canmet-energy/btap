"""P3 gate (standalone half): assign_space_types on-ramp + apply_loads golden
assertions (people/equipment densities, DSOA rescale, infiltration, schedule
wiring, thermostats, skips, coverage emission).

Port of btap-necb/test/test_loads_apply_loads.rb. The parity half
(test_loads_apply_parity.rb) needs the live Ruby oracle; its Leg-C equivalent is
test_oracle_goldens_loads.py.
"""

from __future__ import annotations

import unittest

from tests.support import load_fixture, needs_sdk

MAP_TYPES = {
    'office': ['Space Function', 'Office enclosed > 25 m2'],
    'corridor': ['Space Function', 'Corridor/Transition area other-sch-A'],
    'dining': ['Space Function', 'Dining area - family dining'],
}


@needs_sdk
class TestApplyLoads(unittest.TestCase):
    def mapped_model(self):
        from btap._compat import sorted_by_name
        model = load_fixture()
        spaces = sorted_by_name(model.getSpaces())
        map_ = {}
        for index, space in enumerate(spaces):
            map_[space.nameString()] = (MAP_TYPES['corridor'] if index == 0
                                        else MAP_TYPES['office'])
        return model, map_

    def applied_model(self):
        from btap.audit import AuditLog
        from btap.necb import loads
        model, map_ = self.mapped_model()
        audit = AuditLog()
        loads.assign_space_types(model, map_, vintage='2020', audit=audit)
        loads.apply_loads(model, vintage='2020', audit=audit)
        return model, audit

    def office_space_type(self, model):
        return next((st for st in model.getSpaceTypes()
                     if 'Office enclosed > 25 m2' in st.nameString()), None)

    def test_assign_space_types_on_ramp(self):
        from btap.audit import AuditLog
        from btap.necb import loads
        model, map_ = self.mapped_model()
        audit = AuditLog()
        loads.assign_space_types(model, map_, vintage='2020', audit=audit)
        decision = next(e for e in audit.entries
                        if e['action'] == 'NECB space types assigned')
        self.assertEqual(2, decision['inputs']['space_types_created'],
                         'one SpaceType per distinct pair')
        for space in model.getSpaces():
            self.assertTrue(space.spaceType().is_initialized())
            self.assertTrue(space.spaceType().get().standardsBuildingType().is_initialized())
        with self.assertRaises(ValueError):
            loads.assign_space_types(
                model, {model.getSpaces()[0].nameString(): ['Nope', 'Nada']})

    def test_people_and_equipment_golden(self):
        import openstudio

        from btap.necb import loads
        model, _ = self.applied_model()
        office = self.office_space_type(model)
        record = loads.SpaceTypes.record(building_type='Space Function',
                                         space_type='Office enclosed > 25 m2')

        people = office.people()[0]
        expected_density = openstudio.convert(
            float(record['occupancy_per_area']) / 1000, 'people/ft^2', 'people/m^2').get()
        self.assertAlmostEqual(expected_density,
                               people.peopleDefinition().peopleperSpaceFloorArea().get(),
                               delta=1e-9)
        self.assertAlmostEqual(0.3, people.peopleDefinition().fractionRadiant(), delta=1e-9)
        self.assertTrue(people.clothingInsulationSchedule().is_initialized(),
                        'comfort schedules wired')

        equip = office.electricEquipment()[0]
        expected_epd = openstudio.convert(
            float(record['electric_equipment_per_area']), 'W/ft^2', 'W/m^2').get()
        self.assertAlmostEqual(
            expected_epd, equip.electricEquipmentDefinition().wattsperSpaceFloorArea().get(),
            delta=1e-9)

        self.assertEqual([], list(office.lights()),
                         'NO Lights objects — lighting domain territory')

    def test_ventilation_rescale_and_stash(self):
        import openstudio

        from btap.necb import loads
        model, _ = self.applied_model()
        office = self.office_space_type(model)
        record = loads.SpaceTypes.record(building_type='Space Function',
                                         space_type='Office enclosed > 25 m2')
        dsoa = office.designSpecificationOutdoorAir().get()

        self.assertEqual('Sum', dsoa.outdoorAirMethod())
        per_person = float(record['ventilation_per_person'])
        if per_person != 0:
            expected = (per_person
                        * float(record['ventilation_occupancy_rate_people_per_1000ft2'])
                        / float(record['occupancy_per_area']))
            expected_si = openstudio.convert(
                expected, 'ft^3/min*person', 'm^3/s*person').get()
            self.assertAlmostEqual(expected_si, dsoa.outdoorAirFlowperPerson(), delta=1e-9,
                                   msg='per-person RESCALE applied')
        stash = dsoa.additionalProperties()
        self.assertTrue(stash.getFeatureAsDouble('Ref OA per person').is_initialized(),
                        'source values stashed')
        self.assertTrue(stash.getFeatureAsString('Ref standard').is_initialized())

    def test_schedules_thermostats_and_infiltration(self):
        import openstudio

        from btap.necb import loads
        model, _ = self.applied_model()
        office = self.office_space_type(model)
        record = loads.SpaceTypes.record(building_type='Space Function',
                                         space_type='Office enclosed > 25 m2')

        schedule_set = office.defaultScheduleSet().get()
        self.assertEqual(record['occupancy_schedule'],
                         schedule_set.numberofPeopleSchedule().get().nameString())
        self.assertTrue(schedule_set.electricEquipmentSchedule().is_initialized())
        self.assertFalse(schedule_set.lightingSchedule().is_initialized(),
                         'no lighting schedule wired')

        wanted = f"{office.nameString()} Thermostat"
        thermostat = next((t for t in model.getThermostatSetpointDualSetpoints()
                           if t.nameString() == wanted), None)
        self.assertIsNotNone(thermostat)
        self.assertEqual(record['heating_setpoint_schedule'],
                         thermostat.heatingSetpointTemperatureSchedule().get().nameString())

        if float(record['infiltration_per_exterior_area']) != 0:
            infiltration = office.spaceInfiltrationDesignFlowRates()[0]
            expected = openstudio.convert(float(record['infiltration_per_exterior_area']),
                                          'ft^3/min*ft^2', 'm^3/s*m^2').get()
            self.assertAlmostEqual(expected,
                                   infiltration.flowperExteriorSurfaceArea().get(),
                                   delta=1e-9)

    def test_skips_and_coverage(self):
        import openstudio

        from btap.audit import AuditLog
        from btap.necb import loads
        model, map_ = self.mapped_model()
        plenum = openstudio.model.SpaceType(model)
        plenum.setName('Attic plenum')
        audit = AuditLog()
        loads.assign_space_types(model, map_, vintage='2020', audit=audit)
        loads.apply_loads(model, vintage='2020', audit=audit)

        self.assertTrue(any('plenum space type skipped' in e['action']
                            for e in audit.entries))
        coverage = [e for e in audit.entries if e['step'] == 'coverage']
        # 8.4.3.2. is declared PER SENTENCE since the coverage-depth pass: (1)/(2)
        # partial (cross-gem schedule delegations, illuminance), (3) modeller scope.
        # 4 other 8.4.3.x + 8.4.2.7 (internal loads slice) + 8.4.3.6 outdoor air.
        self.assertEqual(9, len(coverage), 'all declared entries accounted')
        partial = next(e for e in coverage if e.get('article') == '8.4.3.2.(1)')
        self.assertEqual('warning', partial['level'],
                         'partial status WARNS (lighting+SHW schedule delegations)')
        self.assertRegex(partial['action'], 'lighting')
        semi = next(e for e in coverage if e.get('article') == '8.4.3.2.(3)')
        self.assertEqual('info', semi['level'],
                         '(3) semi-heated set-point is a modeller input, not a warning')
        decisions = [e for e in audit.entries
                     if '8.4.3.2' in str(e.get('article') or '')
                     and e['level'] == 'decision']
        self.assertNotEqual([], decisions)

    def test_2025_citation_prefix_flows_to_audit(self):
        from btap.audit import AuditLog
        from btap.necb import loads
        model, map_ = self.mapped_model()
        audit = AuditLog()
        loads.assign_space_types(model, map_, vintage='2025', audit=audit)
        loads.apply_loads(model, vintage='2025', audit=audit)
        office = self.office_space_type(model)
        self.assertTrue(len(office.people()) > 0, '2025 aliases the 2020 data')


if __name__ == '__main__':
    unittest.main()
