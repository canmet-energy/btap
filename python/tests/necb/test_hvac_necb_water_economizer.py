"""8.4.4.12 / 8.4.5.12 Table -12 -> 5.2.2.9 (D-56): reference systems 2 and 5 get a
WATER-side economizer, not the air economizer of 5.2.2.8.

5.2.2.9.(1) — chilling the distribution fluid by direct/indirect EVAPORATION —
requires capability for 100% of the cooling load at outdoor WET-BULB <= 7 C.
(2) — by SENSIBLE heat transfer — uses outdoor DRY-BULB <= 10 C. The reference
rejects heat through an evaporative tower, so (1) binds.

Before D-56 `_apply_economizers` warned and returned for systems 2/5, the OA
controller stayed NoEconomizer, and check_part5 then flagged the very same loop for
having no economizer.

The gate at the bottom is the one that matters: EnergyPlus must actually
FREE-COOL below the 7 C wet-bulb capability point."""

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

# The shared DDY carries many design days; an unfiltered hourly series is mostly
# design-day hours, which are not the weather the criterion is about.
#
# Port note: Ruby writes `t.WarmupFlag = 0`. The EnergyPlus the Python engine
# provisions records WarmupFlag as NULL (not 0) on every Time row, so the literal
# comparison excludes EVERYTHING and the series comes back empty — a silently
# vacuous gate. `IS NULL` is accepted alongside 0: same intent (drop warmup rows),
# robust to both conventions.
RUN_PERIOD = ('t.EnvironmentPeriodIndex IN (SELECT EnvironmentPeriodIndex FROM '
              'EnvironmentPeriods WHERE EnvironmentType = 3) '
              'AND (t.WarmupFlag = 0 OR t.WarmupFlag IS NULL)')


@needs_sdk
class TestNecbWaterEconomizer(unittest.TestCase):

    def sys2_proposed(self):
        """a data centre above the 20 kW cooling threshold selects reference System 2"""
        model = load_fixture()
        modeling.build_system(model, 'PSZ RTU Electric and DX Coils and Electric Baseboard',
                              sorted_zones(model))
        for c in model.getCoilCoolingDXSingleSpeeds():
            c.setRatedTotalCoolingCapacity(30_000.0)
        return model

    def reference(self, model, types, vintage='2020', storeys=1):
        audit = AuditLog()
        result = hvac.reference_hvac(
            model, vintage=vintage,
            building={'storeys': storeys,
                      'zone_types': {z.nameString(): types for z in model.getThermalZones()}},
            audit=audit)
        return result, audit

    def sys2_reference(self, vintage='2020'):
        return self.reference(self.sys2_proposed(), 'Data centre', vintage=vintage)

    @staticmethod
    def d56(audit):
        return [e for e in audit.entries if 'D-56' in str(e.get('ruling') or '')]

    # ---- topology ----

    def test_system_2_reference_gets_a_water_side_economizer(self):
        result, audit = self.sys2_reference()
        self.assertEqual([2], sorted({a.reference_system for a in result.assignments}),
                         'precondition: System 2')
        hxs = result.model.getHeatExchangerFluidToFluids()
        self.assertEqual(1, len(hxs), 'one economizer heat exchanger on the chilled-water plant')
        hx = hxs[0]

        chw = next((loop for loop in result.model.getPlantLoops()
                    if loop.nameString() == 'Chilled Water Loop'), None)
        cw = next((loop for loop in result.model.getPlantLoops()
                   if loop.nameString() == 'Condenser Water Loop'), None)
        self.assertIsNotNone(chw)
        self.assertIsNotNone(cw)
        self.assertTrue(len(chw.supplyComponents(
            openstudio.model.HeatExchangerFluidToFluid.iddObjectType())),
            'the exchanger is SUPPLY equipment on the chilled-water loop (the load)')
        self.assertTrue(len(cw.demandComponents(
            openstudio.model.HeatExchangerFluidToFluid.iddObjectType())),
            'and DEMAND equipment on the condenser loop (the evaporatively-cooled source)')

        entry = next((e for e in self.d56(audit)
                      if 'water-side economizer built' in e['action']), None)
        self.assertIsNotNone(entry)
        self.assertEqual('decision', entry['level'])
        self.assertEqual('8.4.4.12. (Table -12 -> 5.2.2.9)', entry['article'])
        self.assertEqual(7.0, entry['inputs']['capability_wet_bulb_c'])
        self.assertIsNotNone(hx)

    # "Capable of ... 100% of the cooling load" is sizing, and the reference never
    # hard-sizes (L-23): sizing factor 1.0 on autosized UA and both design flows.
    def test_economizer_is_sized_for_the_full_design_load_and_never_hard_sized(self):
        result, _ = self.sys2_reference()
        hx = result.model.getHeatExchangerFluidToFluids()[0]
        self.assertTrue(hx.isHeatExchangerUFactorTimesAreaValueAutosized())
        self.assertTrue(hx.isLoopSupplySideDesignFlowRateAutosized())
        self.assertTrue(hx.isLoopDemandSideDesignFlowRateAutosized())
        self.assertAlmostEqual(1.0, hx.sizingFactor(), delta=1e-9)
        self.assertEqual('CoolingSetpointModulated', hx.controlType())
        self.assertEqual('FreeCooling', hx.heatTransferMeteringEndUseType())

    # The control needs a setpoint to modulate onto, and it is the loop's OWN
    # 8.4.4.10.(6) design exit temperature, not an invented number.
    def test_economizer_control_setpoint_is_the_loop_design_exit_temperature(self):
        result, _ = self.sys2_reference()
        hx = result.model.getHeatExchangerFluidToFluids()[0]
        chw = next(loop for loop in result.model.getPlantLoops()
                   if loop.nameString() == 'Chilled Water Loop')
        node = hx.supplyOutletModelObject().get().to_Node().get()
        managers = [m.to_SetpointManagerScheduled().get() for m in node.setpointManagers()
                    if m.to_SetpointManagerScheduled().is_initialized()]
        self.assertEqual(1, len(managers),
                         'the modulated control has a setpoint on the exchanger outlet')
        day = managers[0].schedule().to_ScheduleRuleset().get().defaultDaySchedule()
        self.assertAlmostEqual(chw.sizingPlant().designLoopExitTemperature(),
                               day.values()[0], delta=1e-9)

    # Without this the economizer is inert: the builder pins the condenser loop at 29 C,
    # so the source is never colder than the chilled-water return.
    def test_condenser_setpoint_is_reset_to_the_outdoor_wet_bulb(self):
        result, audit = self.sys2_reference()
        cw = next(loop for loop in result.model.getPlantLoops()
                  if loop.nameString() == 'Condenser Water Loop')
        managers = cw.supplyOutletNode().setpointManagers()
        self.assertEqual(1, len(managers), 'the constant 29 C setpoint is REPLACED, not stacked')
        reset = managers[0].to_SetpointManagerFollowOutdoorAirTemperature()
        self.assertTrue(reset.is_initialized())
        reset = reset.get()
        self.assertEqual('OutdoorAirWetBulb', reset.referenceTemperatureType(),
                         'an evaporative tower tracks the wet bulb, not the dry bulb')
        tower = result.model.getCoolingTowerSingleSpeeds()[0]
        self.assertAlmostEqual(tower.designApproachTemperature().get(),
                               reset.offsetTemperatureDifference(), delta=1e-9,
                               msg="the offset is the tower's OWN design approach")
        chw = next(loop for loop in result.model.getPlantLoops()
                   if loop.nameString() == 'Chilled Water Loop')
        self.assertAlmostEqual(chw.sizingPlant().designLoopExitTemperature(),
                               reset.minimumSetpointTemperature(), delta=1e-9)
        self.assertAlmostEqual(cw.sizingPlant().designLoopExitTemperature(),
                               reset.maximumSetpointTemperature(), delta=1e-9)

        entry = next((e for e in self.d56(audit)
                      if 'condenser loop setpoint reset' in e['action']), None)
        self.assertIsNotNone(entry)
        self.assertEqual('5.2.2.9.', entry['article'])

    # Sentence (2) is declared inapplicable, not silently ignored.
    def test_sentence_2_sensible_criterion_is_declared_inapplicable(self):
        _, audit = self.sys2_reference()
        entry = next((e for e in self.d56(audit)
                      if 'sensible-transfer criterion' in e['action']), None)
        self.assertIsNotNone(entry)
        self.assertEqual('info', entry['level'])
        self.assertEqual(10.0, entry['inputs']['capability_dry_bulb_c'])

    def test_2025_cites_the_renumbered_article(self):
        _, audit = self.sys2_reference(vintage='2025')
        entry = next((e for e in self.d56(audit)
                      if 'water-side economizer built' in e['action']), None)
        self.assertIsNotNone(entry)
        self.assertEqual('8.4.5.12. (Table -12 -> 5.2.2.9)', entry['article'])

    # ---- articles that must NOT change ----

    # Systems 1/3/4/6 + HP keep the 5.2.2.8 AIR economizer and gain no heat exchanger.
    def test_air_economizer_systems_are_untouched(self):
        model = load_fixture()
        modeling.build_system(model, 'Baseboard gas boiler', sorted_zones(model))
        result, _ = self.reference(model, 'Office - enclosed')
        self.assertEqual([3], sorted({a.reference_system for a in result.assignments}))
        self.assertEqual(0, len(result.model.getHeatExchangerFluidToFluids()),
                         'no water economizer on an air-economizer system')
        kinds = []
        for loop in result.model.getAirLoopHVACs():
            oa = loop.airLoopHVACOutdoorAirSystem()
            if oa.is_initialized():
                kinds.append(oa.get().getControllerOutdoorAir().getEconomizerControlType())
        self.assertEqual(['DifferentialEnthalpy'], sorted(set(kinds)))

    # 8.4.4.12 is IMPLEMENTED since D-62 closed the 5.2.2.8.(4)-(5) DX staging
    # floor (this pin previously asserted 'partial' and was missed when
    # test_hvac_necb_energy_recovery.py's twin pin moved with the D-62 commit —
    # caught by the 2026-08 clarity-review verification pass).
    def test_8_4_4_12_is_implemented_and_no_longer_warns(self):
        for vintage in ('2020', '2025'):
            prefix = '8.4.4' if vintage == '2020' else '8.4.5'
            entry = next(a for a in hvac.rules(vintage)['article_coverage']['articles']
                         if a['article'] == f'{prefix}.12.')
            self.assertEqual('implemented', entry['status'])
            self.assertNotRegex(str(entry.get('gaps') or ''), r'5\.2\.2\.8\.\(4\)-\(5\)',
                                'the DX staging clauses are closed (D-62) — no longer declared as gaps')
        _, audit = self.sys2_reference()
        coverage = next((e for e in audit.entries
                         if e['step'] == 'coverage' and e.get('article') == '8.4.4.12.'), None)
        self.assertIsNotNone(coverage)
        self.assertEqual('info', coverage['level'])

    # ---- the QAQC checker must stop contradicting the builder ----

    def test_checker_no_longer_flags_a_loop_that_has_a_water_economizer(self):
        result, _ = self.sys2_reference()
        audit = hvac.check_part5(result.model, vintage='2020')
        flagged = [w for w in audit.warnings if 'NO economizer' in w['action']]
        self.assertEqual([], flagged, 'the checker no longer contradicts the reference builder')
        note = next((e for e in audit.entries
                     if 'water-side economizer' in e['action'] and e['step'] == 'check_part5'),
                    None)
        self.assertIsNotNone(note)
        self.assertEqual('info', note['level'])
        self.assertEqual('5.2.2.9.', note['article'])
        self.assertEqual('D-56', note['ruling'])

    # ...but a genuinely un-economized water-cooled loop is STILL a finding.
    def test_checker_still_flags_a_loop_with_no_economizer_at_all(self):
        result, _ = self.sys2_reference()
        for hx in list(result.model.getHeatExchangerFluidToFluids()):
            hx.remove()
        audit = hvac.check_part5(result.model, vintage='2020')
        self.assertTrue(any('NO economizer' in w['action'] for w in audit.warnings),
                        'removing the exchanger restores the 5.2.2.8 finding — the suppression '
                        'is scoped, not blanket')

    # ---- the capability gate: EnergyPlus must actually free-cool ----

    # 5.2.2.9.(1) verified as CAPABILITY, not as "an exchanger exists": in every hour of
    # an April run with a chilled-water load and outdoor wet-bulb <= 7 C, the economizer
    # must carry 100% of that load (chiller off).
    @needs_engine
    def test_energyplus_economizer_carries_the_whole_load_below_7c_wet_bulb(self):
        result, _ = self.sys2_reference()
        model = attach_weather(result.model)
        for name in ('Site Outdoor Air Wetbulb Temperature',
                     'Fluid Heat Exchanger Heat Transfer Rate',
                     'Chiller Evaporator Cooling Rate'):
            openstudio.model.OutputVariable(name, model).setReportingFrequency('Hourly')
        with tempfile.TemporaryDirectory() as tmp:
            out = runner.run_energyplus(
                model, str(Path(tmp) / 'wse'), sizing_only=False,
                run_period={'begin_month': 4, 'begin_day': 1,
                            'end_month': 4, 'end_day': 30})
            self.assertTrue(runner.is_clean_run(out),
                            'System 2 reference with the 5.2.2.9 water economizer runs cleanly')
            sql = opt(model.sqlFile())
            wb = self.run_period_series(sql, 'Site Outdoor Air Wetbulb Temperature')
            hx = self.run_period_series(sql, 'Fluid Heat Exchanger Heat Transfer Rate')
            chiller = self.chiller_load(sql)
        n = min(len(wb), len(hx), len(chiller))
        self.assertGreater(n, 100, 'a full month of hourly data')

        band = [{'wb': wb[i], 'hx': hx[i], 'load': hx[i] + chiller[i]} for i in range(n)]
        band = [r for r in band if r['load'] > 100.0 and r['wb'] <= 7.0]
        self.assertTrue(band,
                        'the run period must contain loaded hours at or below 7 C wet-bulb')
        shortfall = [r for r in band if not r['hx'] / r['load'] > 0.999]
        self.assertEqual([], shortfall,
                         f'5.2.2.9.(1): {len(shortfall)} of {len(band)} in-band hours were NOT '
                         'carried 100% by the economizer')

    @staticmethod
    def run_period_series(sql, name, key=None):
        query = ('SELECT d.Value FROM ReportData d '
                 'JOIN ReportDataDictionary dd ON '
                 'd.ReportDataDictionaryIndex = dd.ReportDataDictionaryIndex '
                 'JOIN Time t ON t.TimeIndex = d.TimeIndex '
                 f"WHERE dd.Name = '{name}' AND dd.ReportingFrequency = 'Hourly' "
                 f'AND {RUN_PERIOD}')
        if key:
            query += f" AND dd.KeyValue = '{key}'"
        query += ' ORDER BY d.TimeIndex'
        value = sql.execAndReturnVectorOfDouble(query)
        return list(value.get()) if value.is_initialized() else []

    def chiller_load(self, sql):
        keys = sql.execAndReturnVectorOfString(
            'SELECT DISTINCT dd.KeyValue FROM ReportDataDictionary dd '
            "WHERE dd.Name = 'Chiller Evaporator Cooling Rate' "
            "AND dd.ReportingFrequency = 'Hourly'")
        keys = list(keys.get()) if keys.is_initialized() else []
        series = [self.run_period_series(sql, 'Chiller Evaporator Cooling Rate', k)
                  for k in keys]
        if not series:
            return []

        return [sum(s[i] for s in series) for i in range(min(len(s) for s in series))]


if __name__ == '__main__':
    unittest.main()
