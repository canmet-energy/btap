"""8.4.4.9.(7) / 8.4.4.10.(8) staged heating and cooling (D-46..D-50).

The SDK-only assertions run everywhere; the staging arithmetic itself needs a
SIZED model, so the capacity-driven cases either hard-set capacities (no E+) or
go through EnergyPlus and skip without a provisioned engine."""

from __future__ import annotations

import math
import re
import tempfile
import unittest
from pathlib import Path

import openstudio

import btap.modeling as modeling
from btap.audit import AuditLog
from btap.modeling.hvac.components import coils
from btap.necb import hvac
from btap.necb.hvac import efficiency
from btap.simulation import runner
from tests.necb.hvac_helpers import attach_weather, load_fixture, sorted_zones
from tests.support import needs_engine, needs_sdk

STAGED = {'staged_coils': True}
GAS_PSZ = 'PSZ RTU Gas and DX Coils and Electric Baseboard'
ELEC_PSZ = 'PSZ RTU Electric and DX Coils and Electric Baseboard'
ASHP_PSZ = ('PSZ RTU ASHP with Electric and ASHP with Electric Supp. Heat Coils and '
            'Electric Baseboard')


@needs_sdk
class TestNecbStaging(unittest.TestCase):

    def setUp(self):
        self._tmp = None

    def build(self, name, config=None, weather=False):
        model = load_fixture()
        if weather:
            attach_weather(model)
        zones = sorted_zones(model)
        modeling.build_system(model, name, zones, control_zone=zones[0],
                              config=STAGED if config is None else config)
        return model, zones

    def size(self, model, tag):
        if self._tmp is None:
            self._tmp = tempfile.TemporaryDirectory()
            self.addCleanup(self._tmp.cleanup)
        out = runner.run_energyplus(model, str(Path(self._tmp.name) / tag), sizing_only=True)
        self.assertTrue(runner.is_clean_run(out), f'{tag}: sizing run completes cleanly')
        return out

    @staticmethod
    def rules():
        return hvac.rules('2020')

    @staticmethod
    def stage_caps(coil):
        out = []
        for s in coil.stages():
            if hasattr(s, 'grossRatedTotalCoolingCapacity'):
                out.append(efficiency.optional_f(s.grossRatedTotalCoolingCapacity())
                           or efficiency.optional_f(s.autosizedGrossRatedTotalCoolingCapacity()))
            elif hasattr(s, 'grossRatedHeatingCapacity'):
                out.append(efficiency.optional_f(s.grossRatedHeatingCapacity())
                           or efficiency.optional_f(s.autosizedGrossRatedHeatingCapacity()))
            else:
                out.append(efficiency.optional_f(s.nominalCapacity())
                           or efficiency.optional_f(s.autosizedNominalCapacity()))
        return out

    # ---- topology: the flag gates it, and nothing else changes ----

    def test_flag_off_keeps_the_bare_single_speed_topology(self):
        model, _ = self.build(GAS_PSZ, config={})

        self.assertEqual(0, len(model.getAirLoopHVACUnitarySystems()),
                         'unflagged builds stay bare')
        self.assertEqual(1, len(model.getCoilCoolingDXSingleSpeeds()))
        self.assertEqual(1, len(model.getCoilHeatingGass()))
        self.assertEqual(0, len(model.getCoilCoolingDXMultiSpeeds()))

    def test_staged_gas_psz_builds_a_unitary_with_two_autosized_stages(self):
        model, _ = self.build(GAS_PSZ)

        self.assertEqual(1, len(model.getAirLoopHVACUnitarySystems()))
        unitary = model.getAirLoopHVACUnitarySystems()[0]
        self.assertEqual('Load', unitary.controlType())
        self.assertFalse(unitary.controllingZoneorThermostatLocation().empty(),
                         'Load control needs a control zone')

        cooling = coils.multispeed(unitary.coolingCoil())
        heating = coils.multispeed(unitary.heatingCoil())
        self.assertEqual('CoilCoolingDXMultiSpeed_dx', cooling.nameString())
        self.assertEqual('CoilHeatingGasMultiStage_gas', heating.nameString())
        self.assertEqual(2, len(cooling.stages()))
        self.assertEqual(2, len(heating.stages()))
        for s in cooling.stages():
            self.assertTrue(s.isGrossRatedTotalCoolingCapacityAutosized(),
                            'stage capacities stay autosized')
        for s in heating.stages():
            self.assertTrue(s.isNominalCapacityAutosized(), 'stage capacities stay autosized')

        ratios = unitary.designSpecificationMultispeedObject().get().supplyAirflowRatioFields()
        self.assertEqual([[0.5, 0.5], [1.0, 1.0]],
                         [[f.heatingRatio().get(), f.coolingRatio().get()] for f in ratios])
        # the SetpointManagerSingleZoneReheat stays on the loop outlet
        self.assertEqual(1, len(model.getSetpointManagerSingleZoneReheats()))

    # D-49: electric resistance is not a furnace.
    def test_staged_electric_psz_keeps_a_single_stage_electric_coil(self):
        model, _ = self.build(ELEC_PSZ)
        unitary = model.getAirLoopHVACUnitarySystems()[0]

        self.assertEqual(1, len(model.getCoilCoolingDXMultiSpeeds()),
                         '8.4.4.10.(8) still stages the DX cooling')
        self.assertEqual(0, len(model.getCoilHeatingGasMultiStages()))
        self.assertFalse(unitary.heatingCoil().get().to_CoilHeatingElectric().empty(),
                         'electric heat stays a plain coil')

    # The supplemental coil is a LOOP coil downstream of the unitary, not the
    # unitary's supplemental slot (D-46 deviation: the unitary sizes its
    # supplemental heater to the heat-pump capacity, starving the back-up heat).
    def test_staged_ashp_keeps_the_supplemental_coil_on_the_loop(self):
        model, _ = self.build(ASHP_PSZ)
        unitary = model.getAirLoopHVACUnitarySystems()[0]

        self.assertTrue(unitary.supplementalHeatingCoil().empty(),
                        'no supplemental coil inside the unitary')
        air_loop = model.getAirLoopHVACs()[0]
        supp = [c for c in air_loop.supplyComponents()
                if c.to_CoilHeatingElectric().is_initialized()]
        self.assertEqual(1, len(supp), 'supplemental electric coil sits on the air loop')
        self.assertEqual(1, len(model.getCoilHeatingDXMultiSpeeds()))
        self.assertEqual(1, len(model.getCoilCoolingDXMultiSpeeds()))
        self.assertAlmostEqual(
            -10.0,
            model.getCoilHeatingDXMultiSpeeds()[0]
                 .minimumOutdoorDryBulbTemperatureforCompressorOperation(),
            delta=1e-6)

    # coils.supply_components is the contract every consumer relies on.
    def test_supply_components_descends_into_the_unitary(self):
        model, _ = self.build(GAS_PSZ)
        air_loop = model.getAirLoopHVACs()[0]

        raw = [c.iddObjectType().valueName() for c in air_loop.supplyComponents()]
        self.assertIn('OS_AirLoopHVAC_UnitarySystem', raw)
        self.assertNotIn('OS_Coil_Cooling_DX_MultiSpeed', raw,
                         'the container hides the coils from a plain scan')

        deep = [c.iddObjectType().valueName() for c in coils.supply_components(air_loop)]
        self.assertIn('OS_Fan_ConstantVolume', deep)
        self.assertIn('OS_Coil_Cooling_DX_MultiSpeed', deep)
        self.assertIn('OS_Coil_Heating_Gas_MultiStage', deep)

    # ---- staging arithmetic (needs sized capacities) ----

    def test_stage_count_follows_the_vendored_thresholds(self):
        rule = self.rules()['furnace_staging']
        self.assertEqual(66, rule['two_stage_max_kw'])
        self.assertEqual(66, rule['stage_size_kw'])
        self.assertEqual(self.rules()['dx_staging']['two_stage_max_kw'],
                         rule['two_stage_max_kw'])

        # the rule as implemented: N = kW <= two_stage_max ? 2 : min(ceil(kW/size), 4)
        counts = []
        for kw in (10.0, 66.0, 66.1, 132.0, 132.1, 198.0, 264.0, 500.0):
            wanted = (2 if kw <= rule['two_stage_max_kw']
                      else math.ceil(kw / rule['stage_size_kw']))
            counts.append(min(wanted, efficiency.MAX_STAGES))
        self.assertEqual([2, 2, 2, 2, 3, 3, 4, 4], counts)

    # D-62 — 5.2.2.8.(4)-(5): an ECONOMIZER system's staged cooling gets a
    # stage-count floor (lowest stage <= 25% at >= 70 kW, <= 50% at > 25 kW).
    # Capacities hard-set so top_stage_capacity is readable without a sizing run.
    def test_economizer_staging_floor_5_2_2_8(self):
        spec = self.rules()['economizer_dx_staging']
        self.assertEqual(0.25, spec['ge_70_kw_lowest_fraction'])
        self.assertEqual(0.5, spec['over_25_kw_lowest_fraction'])

        for kw, expected in ((100.0, 4), (40.0, 2), (20.0, 2)):
            model, _ = self.build(GAS_PSZ)
            unitary = model.getAirLoopHVACUnitarySystems()[0]
            coil = coils.multispeed(unitary.coolingCoil())
            n = len(coil.stages())
            for i, s in enumerate(coil.stages()):
                s.setGrossRatedTotalCoolingCapacity(kw * 1000.0 * (i + 1) / n)
            for c in model.getControllerOutdoorAirs():
                c.setEconomizerControlType('DifferentialEnthalpy')

            audit = AuditLog()
            efficiency.apply_staging(model, self.rules(), '2020', audit)
            self.assertEqual(expected, len(coil.stages()),
                             f"{kw} kW economizer system: lowest stage must be <= "
                             f"{25 if kw >= 70 else 50}%")
            if kw >= 70:
                entry = next((e for e in audit.entries
                              if '5.2.2.8 economizer staging floor' in e['action']), None)
                self.assertIsNotNone(entry, 'the floor decision is audited')
                self.assertEqual('5.2.2.8.(4)-(5)', entry['article'])
                self.assertIn('D-62', str(entry.get('ruling') or ''))

        # No economizer -> the 8.4.4.10.(8) incremental rule alone (100 kW -> 2).
        model, _ = self.build(GAS_PSZ)
        unitary = model.getAirLoopHVACUnitarySystems()[0]
        coil = coils.multispeed(unitary.coolingCoil())
        n = len(coil.stages())
        for i, s in enumerate(coil.stages()):
            s.setGrossRatedTotalCoolingCapacity(100_000.0 * (i + 1) / n)
        for c in model.getControllerOutdoorAirs():
            c.setEconomizerControlType('NoEconomizer')
        efficiency.apply_staging(model, self.rules(), '2020', AuditLog())
        self.assertEqual(2, len(coil.stages()), 'no economizer: ceil(100/66) = 2, no floor')

    @needs_engine
    def test_staged_capacities_size_to_equal_increments_and_efficiencies_bin_on_the_total(self):
        model, _ = self.build(GAS_PSZ, weather=True)
        self.size(model, 'gas')

        cooling = model.getCoilCoolingDXMultiSpeeds()[0]
        heating = model.getCoilHeatingGasMultiStages()[0]
        for coil in (cooling, heating):
            caps = self.stage_caps(coil)
            self.assertNotIn(None, caps, f'{coil.nameString()}: sized stage capacities')
            self.assertAlmostEqual(0.5, caps[0] / caps[-1], delta=1e-3,
                                   msg=f'{coil.nameString()}: stage 1 = half the total')

        audit = AuditLog()
        hvac.apply_efficiencies(model, vintage='2020', audit=audit)

        # one table row, applied to EVERY stage
        cops = {s.grossRatedCoolingCOP()
                for s in model.getCoilCoolingDXMultiSpeeds()[0].stages()}
        self.assertEqual(1, len(cops))
        self.assertGreater(
            model.getCoilCoolingDXMultiSpeeds()[0].stages()[0].grossRatedCoolingCOP(), 2.0)
        burner = {s.gasBurnerEfficiency()
                  for s in model.getCoilHeatingGasMultiStages()[0].stages()}
        self.assertEqual(1, len(burner))
        self.assertGreaterEqual(next(iter(burner)), 0.75)

        staged = [e for e in audit.entries if 'equal stages' in str(e['action'])]
        self.assertTrue(staged, 'the staging decision is audited')
        self.assertTrue(all('D-46' in str(e.get('ruling') or '') for e in staged),
                        'staging entries cite D-46')
        self.assertTrue(all(re.search(r'8\.4\.4\.(9|10)\.', str(e.get('article') or ''))
                            for e in staged))

    # D-43 compatibility: the count can move after sizing and the capacities
    # follow on the next sizing run — nothing is hard-set.
    @needs_engine
    def test_stage_count_can_be_raised_after_sizing_and_recapacitates(self):
        model, _ = self.build(GAS_PSZ, weather=True)
        self.size(model, 'restage_a')
        cooling = model.getCoilCoolingDXMultiSpeeds()[0]
        total_before = self.stage_caps(cooling)[-1]

        unitary = model.getAirLoopHVACUnitarySystems()[0]
        efficiency.resize_stages(cooling, 3)
        coils.set_stage_flow_ratios(unitary)
        if hasattr(model, 'resetSqlFile'):
            model.resetSqlFile()
        self.size(model, 'restage_b')

        caps = self.stage_caps(model.getCoilCoolingDXMultiSpeeds()[0])
        self.assertEqual(3, len(caps))
        self.assertAlmostEqual(1.0 / 3, caps[0] / caps[2], delta=1e-3)
        self.assertAlmostEqual(2.0 / 3, caps[1] / caps[2], delta=1e-3)
        self.assertAlmostEqual(total_before, caps[-1], delta=total_before * 0.02,
                               msg='the total is unchanged by re-staging')

    # D-47: above the four-stage ceiling the count is clamped and SHOUTED.
    def test_clamp_at_the_four_stage_ceiling_warns_loudly(self):
        model, _ = self.build(GAS_PSZ)
        coil = model.getCoilHeatingGasMultiStages()[0]
        for s in coil.stages():
            s.setNominalCapacity(400_000.0)  # 400 kW -> 7 stages wanted

        audit = AuditLog()
        efficiency.apply_staging(model, self.rules(), '2020', audit)

        self.assertEqual(4, len(model.getCoilHeatingGasMultiStages()[0].stages()))
        clamp = next((e for e in audit.entries if 'CLAMPED' in str(e['action'])), None)
        self.assertIsNotNone(clamp, 'the clamp is audited')
        self.assertEqual('warning', clamp['level'], 'the clamp is a warning, not an info')
        self.assertIn('EXCEEDS', clamp['action'],
                      'violations are SHOUTED (report checklist parses case-sensitively)')
        self.assertEqual('D-47', clamp['ruling'])

    # Growing the stage count appends a stage EnergyPlus has never sized, so the
    # new top stage reads back None — the efficiency binning must use the total
    # measured BEFORE re-staging, not a re-read.
    def test_efficiencies_still_bin_when_staging_grows_the_stage_count(self):
        model, _ = self.build(GAS_PSZ)
        coil = model.getCoilHeatingGasMultiStages()[0]
        for s in coil.stages():
            s.setNominalCapacity(150_000.0)  # -> ceil(150/66) = 3 stages

        audit = AuditLog()
        hvac.apply_efficiencies(model, vintage='2020', audit=audit)

        grown = model.getCoilHeatingGasMultiStages()[0]
        self.assertEqual(3, len(grown.stages()))
        for stage in grown.stages():
            self.assertTrue(stage.isNominalCapacityAutosized(),
                            'the added stage is autosized, never hard-set')
            self.assertGreaterEqual(stage.gasBurnerEfficiency(), 0.75,
                                    'every stage got the table value')
        # the unsized DX cooling coil still warns loudly (nothing gave it a capacity);
        # the GAS coil, whose total was measured before re-staging, must not.
        gas_warnings = [w for w in audit.warnings
                        if 'CoilHeatingGasMultiStage' in f"{w.get('target')} {w['action']}"]
        self.assertEqual([], gas_warnings,
                         'no capacity-unavailable warning after a stage-count growth')

    # D-48: PTAC/PTHP terminals and make-up-air DX stay single-speed, audited.
    def test_zone_terminal_dx_is_skipped_and_audited(self):
        model, _ = self.build('PSZ MAU Electric and DX Coils and Electric Baseboard with PTAC',
                              config={})
        audit = AuditLog()
        efficiency.apply_staging(model, self.rules(), '2020', audit)

        skips = [e for e in audit.entries if e.get('ruling') == 'D-48']
        self.assertTrue(skips, 'the single-speed skips are audited')
        self.assertTrue(all(e['level'] == 'info' for e in skips))
        self.assertTrue(any('zone-terminal DX' in e['action'] for e in skips))
        self.assertTrue(len(model.getCoilCoolingDXSingleSpeeds()),
                        'terminals keep single-speed coils')

    # ---- D-50: the terminal/secondary split ----

    def test_make_up_air_systems_carry_dedicated_outdoor_air_zone_sizing(self):
        model, zones = self.build(
            'PSZ MAU Electric and DX Coils and Electric Baseboard with PTAC', config={})

        for zone in zones:
            sizing = zone.sizingZone()
            self.assertTrue(sizing.accountforDedicatedOutdoorAirSystem(),
                            f'{zone.nameString()}: DOAS accounting on')
            self.assertEqual('NeutralSupplyAir', sizing.dedicatedOutdoorAirSystemControlStrategy())
            low = sizing.dedicatedOutdoorAirLowSetpointTemperatureforDesign().get()
            high = sizing.dedicatedOutdoorAirHighSetpointTemperatureforDesign().get()
            self.assertLess(low, high, 'EnergyPlus rejects low >= high with a Severe')
            self.assertAlmostEqual(20.0, low, delta=1e-6)

    def test_mixed_air_systems_do_not_get_dedicated_outdoor_air_accounting(self):
        _model, zones = self.build(GAS_PSZ)

        for zone in zones:
            self.assertFalse(zone.sizingZone().accountforDedicatedOutdoorAirSystem(),
                             'sys 3/4 mix outdoor air into the supply stream — no DOAS accounting')

    def test_reference_transform_audits_the_split_for_both_shapes(self):
        model = load_fixture()
        zones = sorted_zones(model)
        modeling.build_system(model, 'Baseboard gas boiler', zones)
        types = {z.nameString(): 'Office - enclosed' for z in zones}
        result = hvac.reference_hvac(model, building={'storeys': 1, 'zone_types': types})

        split = [e for e in result.audit.entries if e.get('ruling') == 'D-50']
        self.assertTrue(split, 'the terminal/secondary split is audited')
        self.assertTrue(all('8.4.4.9.(3)' in e['article'] for e in split))

    # A staged unit reduces supply flow with capacity (the E+ multispeed coil
    # requires flow to track per-stage capacity), but must not stage below the
    # ventilation air it exists to deliver.
    def test_stage_flow_ratios_are_floored_at_the_outdoor_air_fraction(self):
        model = openstudio.model.Model()
        unitary = openstudio.model.AirLoopHVACUnitarySystem(model)
        coil = coils.dx_cooling_multi_speed(model, model.alwaysOnDiscreteSchedule())
        unitary.setCoolingCoil(coil)
        performance = openstudio.model.UnitarySystemPerformanceMultispeed(model)
        unitary.setDesignSpecificationMultispeedObject(performance)

        # Two stages, no floor: stage 1 rides at half flow.
        coils.set_stage_flow_ratios(unitary)
        ratios = [f.coolingRatio().get() for f in performance.supplyAirflowRatioFields()]
        self.assertAlmostEqual(0.5, ratios[0], delta=1e-6)
        self.assertAlmostEqual(1.0, ratios[-1], delta=1e-6)

        # A 70% outdoor-air unit cannot drop to 50% flow — the floor binds.
        coils.set_stage_flow_ratios(unitary, min_ratio=0.7)
        floored = [f.coolingRatio().get() for f in performance.supplyAirflowRatioFields()]
        self.assertAlmostEqual(0.7, floored[0], delta=1e-6,
                               msg='low stage floored at the ventilation fraction')
        self.assertAlmostEqual(1.0, floored[-1], delta=1e-6, msg='top stage still full flow')

        # A floor below the natural ratio changes nothing, and no ratio exceeds 1.
        coils.set_stage_flow_ratios(unitary, min_ratio=0.2)
        self.assertAlmostEqual(
            0.5, performance.supplyAirflowRatioFields()[0].coolingRatio().get(), delta=1e-6)
        coils.set_stage_flow_ratios(unitary, min_ratio=1.5)
        self.assertTrue(all(f.coolingRatio().get() <= 1.0 + 1e-9
                            for f in performance.supplyAirflowRatioFields()))


if __name__ == '__main__':
    unittest.main()
