"""Table 8.4.4.7.-B note (1) / Table 8.4.5.7.-B note (1) (D-55): "where present,
humidification systems in the reference building shall use the same energy source
as the corresponding humidification system in the proposed building".

Before D-55 this was a bare COUNT taken before the teardown plus a warning — and
nothing pinned it. Two defects came with it: the count also warned about
humidifiers that go on to survive untouched on 'copy_proposed' loops, and the ones
on replaced loops were destroyed as a side effect of `air_loop.remove` rather than
deliberately.

The gate that matters is at the bottom: EnergyPlus must actually OPERATE the
rebuilt humidifier, on the proposed's fuel."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import openstudio

import btap.modeling as modeling
from btap._compat import opt
from btap.audit import AuditLog
from btap.necb import hvac
from btap.simulation import runner
from tests.necb.hvac_helpers import attach_weather, load_fixture, sorted_zones
from tests.support import needs_engine, needs_sdk

MZ = 'MZ BU RTU Hot Water Heating Coil Scroll Chiller and Hot Water Baseboard'
FPFC = 'FPFC MAU Chilled Water Coils with Scroll Chiller'


@needs_sdk
class TestNecbHumidification(unittest.TestCase):

    def humidistat(self, model, zones, rh=30.0):
        from btap._compat import ruby_round
        schedule = openstudio.model.ScheduleRuleset(model)
        schedule.setName(f'Min RH {ruby_round(rh)}')
        schedule.defaultDaySchedule().addValue(openstudio.Time(0, 24, 0, 0), rh)
        for zone in zones:
            stat = openstudio.model.ZoneControlHumidistat(model)
            stat.setHumidifyingRelativeHumiditySetpointSchedule(schedule)
            zone.setZoneControlHumidistat(stat)
        return schedule

    def humidify(self, air_loop, kind='gas', control='humidistat', schedule=None):
        """Put a humidifier on an air loop, optionally with the control a real
        humidified proposed carries."""
        model = air_loop.model()
        humidifier = (openstudio.model.HumidifierSteamGas(model) if kind == 'gas'
                      else openstudio.model.HumidifierSteamElectric(model))
        humidifier.setName(f'proposed {kind} humidifier on {air_loop.nameString()}')
        humidifier.autosizeRatedCapacity()
        if hasattr(humidifier, 'autosizeRatedPower'):
            humidifier.autosizeRatedPower()
        self.assertTrue(humidifier.addToNode(air_loop.supplyOutletNode()),
                        'proposed humidifier accepted by the SDK')
        node = humidifier.outletModelObject().get().to_Node().get()

        if control == 'humidistat':
            manager = openstudio.model.SetpointManagerSingleZoneHumidityMinimum(model)
            manager.setControlZone(air_loop.thermalZones()[0])
            manager.addToNode(node)
        elif control == 'scheduled':
            manager = openstudio.model.SetpointManagerScheduled(model, schedule)
            manager.setControlVariable('MinimumHumidityRatio')
            manager.addToNode(node)
        return humidifier

    def reference(self, model, types, storeys=3, vintage='2020'):
        audit = AuditLog()
        result = hvac.reference_hvac(
            model, vintage=vintage,
            building={'storeys': storeys,
                      'zone_types': {z.nameString(): types for z in model.getThermalZones()}},
            audit=audit)
        return result, audit

    def humidified_office(self, kind='gas', control='humidistat'):
        """A 3-storey office proposed (System 6 reference) whose single air loop
        humidifies."""
        model = load_fixture()
        zones = sorted_zones(model)
        modeling.build_system(model, MZ, zones)
        schedule = self.humidity_schedule(model) if control == 'scheduled' else None
        if control == 'humidistat':
            self.humidistat(model, zones)
        for loop in model.getAirLoopHVACs():
            self.humidify(loop, kind=kind, control=control, schedule=schedule)
        return model

    @staticmethod
    def humidity_schedule(model):
        schedule = openstudio.model.ScheduleRuleset(model)
        schedule.setName('Proposed Min Humidity Ratio')
        schedule.defaultDaySchedule().addValue(openstudio.Time(0, 24, 0, 0), 0.004)
        return schedule

    @staticmethod
    def humidifiers(model):
        return ([('gas', h) for h in model.getHumidifierSteamGass()]
                + [('electric', h) for h in model.getHumidifierSteamElectrics()])

    @staticmethod
    def d55(audit):
        return [e for e in audit.entries if 'D-55' in str(e.get('ruling') or '')]

    # ---- the rebuild ----

    def test_gas_humidification_is_rebuilt_on_natural_gas(self):
        result, audit = self.reference(self.humidified_office(kind='gas'), 'Office - open plan')
        rebuilt = self.humidifiers(result.model)
        self.assertEqual(1, len(rebuilt), 'one reference humidifier for the one reference air loop')
        self.assertEqual('gas', rebuilt[0][0],
                         'note (1): the reference uses the PROPOSED energy source')
        self.assertTrue(rebuilt[0][1].isRatedCapacityAutosized(), 'never hard-sized (L-23)')

        entry = next((e for e in self.d55(audit)
                      if 'reference humidification rebuilt' in e['action']), None)
        self.assertIsNotNone(entry)
        self.assertEqual('decision', entry['level'], 'the T8 warning became a decision')
        self.assertEqual('Table 8.4.4.7.-B Note (1)', entry['article'])
        self.assertEqual('NaturalGas', entry['inputs']['energy_source'])

    def test_electric_humidification_is_rebuilt_on_electricity(self):
        result, audit = self.reference(self.humidified_office(kind='electric'),
                                       'Office - open plan')
        rebuilt = self.humidifiers(result.model)
        self.assertEqual(1, len(rebuilt))
        self.assertEqual('electric', rebuilt[0][0])
        entry = next(e for e in self.d55(audit)
                     if 'reference humidification rebuilt' in e['action'])
        self.assertEqual('Electricity', entry['inputs']['energy_source'])

    # An uncontrolled humidifier is silently inert — the rebuild is worthless without
    # a setpoint that actually reaches it.
    def test_rebuilt_humidifier_carries_a_working_control(self):
        result, audit = self.reference(self.humidified_office(kind='gas'), 'Office - open plan')
        managers = result.model.getSetpointManagerSingleZoneHumidityMinimums()
        self.assertEqual(1, len(managers))
        manager = managers[0]
        self.assertTrue(manager.controlZone().is_initialized(),
                        'the setpoint manager has a control zone')
        self.assertTrue(manager.controlZone().get().zoneControlHumidistat().is_initialized(),
                        'the control zone carries the humidistat that survived the teardown')
        self.assertTrue(manager.setpointNode().is_initialized(),
                        'the setpoint manager is on a node')

        humidifier = result.model.getHumidifierSteamGass()[0]
        self.assertEqual(str(humidifier.outletModelObject().get().handle()),
                         str(manager.setpointNode().get().handle()),
                         "the setpoint sits on the humidifier's own outlet node")
        entry = next(e for e in self.d55(audit)
                     if 'reference humidification rebuilt' in e['action'])
        self.assertIn('SetpointManagerSingleZoneHumidityMinimum', entry['inputs']['control'])

    # The proposed's own scheduled minimum-humidity setpoint is the fallback when no
    # zone humidistat exists — control still comes from the proposed, never invented.
    def test_scheduled_setpoint_is_the_fallback_control(self):
        result, audit = self.reference(
            self.humidified_office(kind='electric', control='scheduled'), 'Office - open plan')
        self.assertEqual(1, len(self.humidifiers(result.model)))
        scheduled = [s for s in result.model.getSetpointManagerScheduleds()
                     if s.controlVariable() == 'MinimumHumidityRatio']
        self.assertEqual(1, len(scheduled),
                         'the proposed loop control is gone with the loop; the reference has its own')
        self.assertEqual('Proposed Min Humidity Ratio', scheduled[0].schedule().nameString(),
                         "the rebuilt control uses the PROPOSED's setpoint schedule")
        entry = next(e for e in self.d55(audit)
                     if 'reference humidification rebuilt' in e['action'])
        self.assertIn('SetpointManagerScheduled', entry['inputs']['control'])

    # No humidistat, no scheduled setpoint: the source is known but the CONTROL is not.
    # Building an inert humidifier would misrepresent the reference as humidified.
    def test_undeterminable_control_warns_and_builds_nothing(self):
        result, audit = self.reference(self.humidified_office(kind='gas', control='none'),
                                       'Office - open plan')
        self.assertEqual([], self.humidifiers(result.model),
                         'no inert humidifier is left behind')
        warning = next((e for e in self.d55(audit) if e['level'] == 'warning'), None)
        self.assertIsNotNone(warning)
        self.assertIn('INERT', warning['action'])

    # ---- the pre-teardown over-count defect ----

    # A residential fan-coil block takes the 'copy_proposed' rule, so its MAU loop —
    # and the humidifier on it — is never replaced. The old code counted humidifiers
    # BEFORE the teardown and warned "NOT rebuilt" about this one too.
    def test_humidifier_surviving_on_a_copy_proposed_loop_does_not_warn(self):
        model = load_fixture()
        zones = sorted_zones(model)
        modeling.build_system(model, FPFC, zones)
        self.humidistat(model, zones)
        for loop in model.getAirLoopHVACs():
            self.humidify(loop, kind='gas')

        result, audit = self.reference(model, 'Multi-unit residential', storeys=3)
        self.assertEqual(['copy_proposed'], sorted({a.action for a in result.assignments}),
                         'precondition: nothing is replaced')
        self.assertEqual(1, len(self.humidifiers(result.model)),
                         'the proposed humidifier survives untouched')
        self.assertEqual([], [e for e in self.d55(audit) if e['level'] == 'warning'],
                         'a surviving humidifier is NOT a "not rebuilt" warning')
        retained = next((e for e in self.d55(audit)
                         if 'retained on this reference loop' in e['action']), None)
        self.assertIsNotNone(retained)
        self.assertEqual('info', retained['level'])

    # ---- merged systems and vintages ----

    # D-28 merges multizone selection groups onto one reference system. Where the
    # merged blocks disagree on energy source, note (1) can only be satisfied for one.
    def test_mixed_energy_sources_elect_the_majority_and_shout(self):
        model = load_fixture()
        zones = sorted_zones(model)
        modeling.build_system(model, MZ, zones[0:2])
        modeling.build_system(model, MZ, zones[2:5])
        self.humidistat(model, zones)
        loops = sorted(model.getAirLoopHVACs(), key=lambda loop: len(loop.thermalZones()))
        self.humidify(loops[0], kind='gas')        # 2 zones
        self.humidify(loops[-1], kind='electric')  # 3 zones

        result, audit = self.reference(model, 'Office - open plan')
        rebuilt = self.humidifiers(result.model)
        self.assertEqual(1, len(rebuilt), 'the merged reference system carries one humidifier')
        self.assertEqual('electric', rebuilt[0][0], 'majority of the merged thermal blocks')
        warning = next((e for e in self.d55(audit) if 'DIFFERENT' in e['action']), None)
        self.assertIsNotNone(warning, 'the divergence is shouted, not silent')
        self.assertEqual('warning', warning['level'])

    def test_2025_cites_the_renumbered_table(self):
        _, audit = self.reference(self.humidified_office(kind='gas'), 'Office - open plan',
                                  vintage='2025')
        entry = next((e for e in self.d55(audit)
                      if 'reference humidification rebuilt' in e['action']), None)
        self.assertIsNotNone(entry)
        self.assertEqual('Table 8.4.5.7.-B Note (1)', entry['article'])

    # ---- the gate that matters: EnergyPlus must actually OPERATE it ----

    @needs_engine
    def test_rebuilt_humidifier_consumes_its_energy_source_in_energyplus(self):
        model = attach_weather(self.humidified_office(kind='gas'))
        result, _ = self.reference(model, 'Office - open plan')
        with tempfile.TemporaryDirectory() as tmp:
            out = runner.run_energyplus(
                result.model, str(Path(tmp) / 'humid'), sizing_only=False,
                run_period={'begin_month': 1, 'begin_day': 1,
                            'end_month': 1, 'end_day': 7})
            self.assertTrue(runner.is_clean_run(out),
                            'reference with rebuilt gas humidification runs cleanly')
            sql = opt(result.model.sqlFile())
            gas = self.humidification_end_use(sql, 'Natural Gas')
            electricity = self.humidification_end_use(sql, 'Electricity')
        self.assertGreater(gas, 0.0, 'EnergyPlus actually RAN the rebuilt gas humidifier')
        self.assertAlmostEqual(0.0, electricity, delta=1e-9,
                               msg='and it burned gas, not electricity')

    @staticmethod
    def humidification_end_use(sql, column):
        value = sql.execAndReturnFirstDouble(
            "SELECT Value FROM TabularDataWithStrings WHERE "
            "ReportName='AnnualBuildingUtilityPerformanceSummary' "
            "AND TableName='End Uses' AND RowName='Humidification' "
            f"AND ColumnName='{column}'")
        return value.get() if value.is_initialized() else None


if __name__ == '__main__':
    unittest.main()
