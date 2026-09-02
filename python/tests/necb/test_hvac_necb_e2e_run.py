"""Full proposed -> reference -> EnergyPlus gate: the generated systems must actually
RUN (translate, size, and — for the controls case — simulate a week) with no Fatal
and no Severe errors. Pure package + provisioned engine; skips without one.

~4 EnergyPlus executions; expect a few minutes.

Port note (D-79): the Ruby suite drives the `openstudio` CLI through
FixtureHelper#run_energyplus!; the Python port drives btap.simulation's Local
backend (in-process ForwardTranslator + the provisioned engine). Same artifacts,
same parse surface (M2)."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import openstudio

import btap.modeling as modeling
from btap._compat import sorted_by_name
from btap.audit import AuditLog
from btap.necb import hvac
from btap.simulation import runner
from tests.necb.hvac_helpers import attach_weather, load_fixture, sorted_zones
from tests.support import needs_engine


def office_types(model):
    return {z.nameString(): 'Office - enclosed' for z in model.getThermalZones()}


@needs_engine
class TestNecbE2ERun(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)

    def run_energyplus(self, model, tag, sizing_only=True, run_period=None):
        out = runner.run_energyplus(model, str(self.dir / tag),
                                    sizing_only=sizing_only, run_period=run_period)
        self.assertTrue(runner.is_clean_run(out), f'{tag}: E+ did not complete cleanly')
        return out

    def assert_zones_conditioned(self, model, context, max_heating_hours, max_cooling_hours):
        """The comfort gate: the generated system must actually CONDITION the zones,
        not just simulate cleanly. Thresholds are for the simulated period (a broken
        system shows up as ~every occupied hour unmet, not a handful)."""
        unmet = runner.unmet_occupied_hours(model)
        self.assertIsNotNone(unmet['heating'], f'{context}: no unmet-hours data in SQL')
        self.assertLessEqual(unmet['heating'], max_heating_hours,
                             f"{context}: {unmet['heating']} occupied heating hours unmet "
                             f'(limit {max_heating_hours}) — system not conditioning')
        self.assertLessEqual(unmet['cooling'], max_cooling_hours,
                             f"{context}: {unmet['cooling']} occupied cooling hours unmet "
                             f'(limit {max_cooling_hours})')

    # Proposed CBECS baseboards runs in E+; its sys3-gas reference sizes cleanly and the
    # efficiency pass lands real capacity-binned values on the sized reference.
    def test_proposed_and_sys3_reference_size_cleanly(self):
        proposed = attach_weather(load_fixture())
        modeling.build_system(proposed, 'Baseboard gas boiler', sorted_zones(proposed))

        self.run_energyplus(proposed, 'proposed')

        result = hvac.reference_hvac(
            proposed, building={'storeys': 1, 'zone_types': office_types(proposed)})
        self.assertEqual([3], sorted({a.reference_system for a in result.assignments}))

        self.run_energyplus(result.model, 'reference')

        # efficiencies on the now-sized reference: no 'not sized' warnings, values applied
        audit = AuditLog()
        hvac.apply_efficiencies(result.model, vintage='2020', audit=audit)
        self.assertEqual([], [w for w in audit.warnings if 'not sized' in w['action']],
                         'all components sized after the reference E+ run')
        # D-46: the sys3 reference furnace is a STAGED Coil:Heating:Gas:MultiStage
        # inside the unitary; the burner efficiency lands on every stage.
        staged = sorted_by_name(result.model.getCoilHeatingGasMultiStages())
        self.assertTrue(staged, 'staged sys3 reference builds a multi-stage gas coil')
        gas_coil = staged[0]
        self.assertGreaterEqual(len(gas_coil.stages()), 2,
                                '8.4.4.9.(7): at least two equal stages')
        for stage in gas_coil.stages():
            self.assertGreaterEqual(stage.gasBurnerEfficiency(), 0.80)
        boiler = next(b for b in result.model.getBoilerHotWaters()
                      if 'Primary' in b.nameString())
        self.assertAlmostEqual(0.90, boiler.nominalThermalEfficiency(), delta=1e-6)

    def test_purchased_cooling_cop_survives_reference_sizing(self):
        proposed = attach_weather(load_fixture())
        modeling.build_system(
            proposed, 'DOAS with fan coil district chilled water with boiler',
            sorted_zones(proposed))
        types = {zone.nameString(): 'Museum archives'
                 for zone in proposed.getThermalZones()}
        result = hvac.reference_hvac(
            proposed, building={'storeys': 1, 'zone_types': types})

        self.run_energyplus(result.model, 'purchased_cooling_reference')
        audit = AuditLog()
        hvac.apply_efficiencies(result.model, vintage='2020', audit=audit)

        chillers = result.model.getChillerElectricEIRs()
        self.assertTrue(chillers)
        self.assertTrue(all(abs(chiller.referenceCOP() - 2.802) < 0.001
                            for chiller in chillers))
        self.assertTrue(any(entry['action'] ==
                            'purchased-cooling reference chiller COP applied'
                            and entry.get('article') == 'Table 8.4.3.5'
                            for entry in audit.entries))

    def test_vrf_table_i_applies_after_sizing(self):
        model = attach_weather(load_fixture())
        modeling.build_system(model, 'VRF', sorted_zones(model))

        self.run_energyplus(model, 'vrf_sizing')
        audit = AuditLog()
        hvac.apply_efficiencies(model, vintage='2020', audit=audit)

        unit = model.getAirConditionerVariableRefrigerantFlows()[0]
        decision = next(entry for entry in audit.entries
                        if entry['action'] == 'VRF minimum efficiency applied')
        self.assertEqual('heat_pump', decision['inputs']['equipment_class'])
        self.assertEqual('D-85', decision['ruling'])
        self.assertFalse(any('VRF' in warning['action'] and 'not sized' in warning['action']
                             for warning in audit.warnings))
        self.assertLess(unit.grossRatedCoolingCOP(), 4.0,
                        'the sized builder COP is replaced by the Table-I minimum')

    # Air-source HP proposed -> Table 8.4.4.13 ASHP reference: a January week in
    # Toronto forces operation BELOW the -10 C compressor cutoff, so unmet hours
    # prove the supplemental heat + baseboards actually carry the load when the
    # heat pump locks out. (D-37: the proposed is a PTHP — air-source, which
    # REDIRECTS; the old 'Water source heat pumps' proposed here is by Note
    # A-8.4.4.13 a water-LOOP system whose internal boiler+fluid-cooler loop now
    # correctly KEEPS its Table -A selection — see test_hvac_necb_reference.)
    def test_ashp_reference_conditions_through_a_cold_week(self):
        proposed = attach_weather(load_fixture())
        modeling.build_system(proposed, 'PTHP', sorted_zones(proposed))

        result = hvac.reference_hvac(
            proposed, building={'storeys': 1, 'zone_types': office_types(proposed)})
        self.assertEqual(['hp'], sorted({a.reference_system for a in result.assignments}))

        self.run_energyplus(result.model, 'ashp_week', sizing_only=False,
                            run_period={'begin_month': 1, 'begin_day': 1,
                                        'end_month': 1, 'end_day': 7})
        self.assert_zones_conditioned(result.model, 'ASHP reference week',
                                      max_heating_hours=24, max_cooling_hours=6)

        hvac.apply_efficiencies(result.model, vintage='2020')
        staged = sorted_by_name(result.model.getCoilHeatingDXMultiSpeeds())
        self.assertTrue(staged, 'staged reference ASHP builds a multispeed heating coil')
        hp = staged[0]
        for stage in hp.stages():
            self.assertGreater(stage.grossRatedHeatingCOP(), 2.0)
        self.assertAlmostEqual(
            -10.0, hp.minimumOutdoorDryBulbTemperatureforCompressorOperation(), delta=1e-6)

    # The controls gate: a sys6 reference WITH the 8.4.4.19 ERV simulates a January week
    # (VAV + boiler/chiller plants + rotary HX + OA-pretreat SPM all active at runtime).
    # Mirrors the umbrella flow: sizing run -> apply_energy_recovery on the SIZED
    # flows (Table 5.2.10.1 trigger) -> week run.
    def test_sys6_reference_with_erv_simulates_a_week(self):
        proposed = attach_weather(load_fixture())
        modeling.build_system(
            proposed, 'MZ BU RTU Hot Water Heating Coil Scroll Chiller and Hot Water Baseboard',
            sorted_zones(proposed))
        for space in proposed.getSpaces():
            spec = openstudio.model.DesignSpecificationOutdoorAir(proposed)
            # ~10%+ OA once sized; Always On -> continuous -> Table -B "R"
            spec.setOutdoorAirFlowperFloorArea(0.001)
            space.setDesignSpecificationOutdoorAir(spec)

        result = hvac.reference_hvac(
            proposed, building={'storeys': 3, 'zone_types': office_types(proposed)})
        self.assertEqual([6], sorted({a.reference_system for a in result.assignments}))

        self.run_energyplus(result.model, 'sys6_sizing')
        erv_audit = hvac.apply_energy_recovery(result.model, hdd=3890)
        self.assertTrue(len(result.model.getHeatExchangerAirToAirSensibleAndLatents()),
                        'ERV present')
        decision = next(e for e in erv_audit.entries
                        if 'energy recovery added' in e['action'])
        self.assertEqual('continuous', decision['inputs']['operation'])

        self.run_energyplus(result.model, 'sys6_week', sizing_only=False,
                            run_period={'begin_month': 1, 'begin_day': 1,
                                        'end_month': 1, 'end_day': 7})
        self.assert_zones_conditioned(result.model, 'sys6 reference week',
                                      max_heating_hours=24, max_cooling_hours=6)

        # the simulation produced actual HVAC energy use (end-uses summary)
        energy = runner.energy_results(result.model)
        end_uses = energy['end_uses_kwh']
        hvac_kwh = sum(float(end_uses.get(key) or 0.0)
                       for key in ('fans', 'cooling', 'heating', 'pumps'))
        self.assertGreater(hvac_kwh, 0.0,
                           'week run produced HVAC energy use (fans/pumps/heating/cooling)')


if __name__ == '__main__':
    unittest.main()
