"""P4 gate: hvac.reference_hvac golden scenarios — proposed -> reference topology per
Table 8.4.4.7.-A/-B, fan specs per 8.4.4.18, oversizing caps per 8.4.4.8, HP rules
per 8.4.4.13, with the article-tagged audit trail."""

from __future__ import annotations

import json
import re
import unittest

import openstudio

import btap.modeling as modeling
from btap.audit import AuditLog
from btap.necb import hvac
from tests.necb.hvac_helpers import load_fixture, sorted_zones
from tests.support import needs_sdk


def types(model, type_):
    return {z.nameString(): type_ for z in model.getThermalZones()}


@needs_sdk
class TestNecbReference(unittest.TestCase):

    def proposed(self, name, block=None):
        model = load_fixture()
        modeling.build_system(model, name, sorted_zones(model))
        if block:
            block(model)
        return model

    # small office, electric heat -> System 3, electric variant; supply fans 640 Pa/40%
    def test_small_office_to_sys3_electric(self):
        model = self.proposed('Baseboard electric')
        result = hvac.reference_hvac(
            model, building={'storeys': 1, 'zone_types': types(model, 'Office - enclosed')})

        self.assertEqual([3], sorted({a.reference_system for a in result.assignments}))
        self.assertEqual(['electric'], sorted({a.energy_type for a in result.assignments}))
        self.assertTrue(len(result.model.getAirLoopHVACs()), 'reference builds PSZ RTUs')
        self.assertEqual(0, len(model.getAirLoopHVACs()), 'proposed model untouched')
        for fan in result.model.getFanConstantVolumes():
            self.assertAlmostEqual(640.0, fan.pressureRise(), delta=0.1)
            self.assertAlmostEqual(0.40, fan.fanTotalEfficiency(), delta=1e-6)
        # electric reference has no gas: heating from electric coil + electric baseboards
        self.assertEqual(0, len(result.model.getCoilHeatingGass()))

    # 3-storey gas VAV office -> System 6; supply 1000 Pa/55%, return 250 Pa/30%
    def test_three_storey_office_to_sys6(self):
        model = self.proposed(
            'MZ BU RTU Hot Water Heating Coil Scroll Chiller and Hot Water Baseboard')
        result = hvac.reference_hvac(
            model, building={'storeys': 3, 'zone_types': types(model, 'Office - open plan')})

        self.assertEqual([6], sorted({a.reference_system for a in result.assignments}))
        self.assertEqual(['gas'], sorted({a.energy_type for a in result.assignments}),
                         'energy type follows proposed boiler fuel')
        supply = [f for f in result.model.getFanVariableVolumes()
                  if not re.search(r'return', f.nameString(), re.IGNORECASE)]
        returns = [f for f in result.model.getFanVariableVolumes()
                   if re.search(r'return', f.nameString(), re.IGNORECASE)]
        self.assertTrue(supply)
        self.assertTrue(returns)
        for f in supply:
            self.assertAlmostEqual(1000.0, f.pressureRise(), delta=0.1)
        for f in returns:
            self.assertAlmostEqual(250.0, f.pressureRise(), delta=0.1)
            self.assertAlmostEqual(0.30, f.fanTotalEfficiency(), delta=1e-6)

    # D-34 (A1 ruled follow-legacy): residential PTHP is a HEAT PUMP -> the
    # 8.4.4.7.(4) ASHP redirect wins over the Table -A "(or heat pumps)"
    # identical-to-proposed parenthetical.
    def test_residential_pthp_redirects_to_ashp_reference(self):
        model = self.proposed('PTHP')
        result = hvac.reference_hvac(
            model, building={'storeys': 1, 'zone_types': types(model, 'Multi-unit residential')})

        self.assertEqual(['hp'], sorted({a.reference_system for a in result.assignments}))
        self.assertEqual(['build'], sorted({a.action for a in result.assignments}))
        self.assertEqual(0, len(result.model.getZoneHVACPackagedTerminalHeatPumps()),
                         'proposed PTHPs replaced by the ASHP reference')
        self.assertTrue(len(result.model.getAirLoopHVACs()), 'ASHP RTU reference built')

    # D-37 (A2 ruled: printed 8.4.4.13 split per Note A-8.4.4.13): the catalog
    # 'Water source heat pumps' system is by the note's definitions a
    # water-LOOP HP — internal loop with aux boiler + evaporative fluid cooler —
    # so it KEEPS its Table -A selection (office 1-storey -> System 3), with the
    # retention audited. Swapping the loop's internal sources for a ground HX
    # makes it ground-SOURCE -> the 8.4.4.13.(2) ASHP redirect fires.
    def test_water_loop_hp_keeps_selection_ground_source_redirects(self):
        model = self.proposed('Water source heat pumps')
        audit = AuditLog()
        result = hvac.reference_hvac(
            model, audit=audit,
            building={'storeys': 1, 'zone_types': types(model, 'Office - enclosed')})
        self.assertEqual([3], sorted({a.reference_system for a in result.assignments}),
                         'internal boiler+fluid-cooler loop = water-loop HP -> Table -A selection retained')
        self.assertTrue(any('Note A-8.4.4.13' in str(e.get('article') or '')
                            for e in audit.entries),
                        'retention decision cites the note')

        ground = self.proposed('Water source heat pumps')
        loop_ = next(loop for loop in ground.getPlantLoops()
                     if re.search(r'Heat Pump', loop.nameString(), re.IGNORECASE))
        for c in list(loop_.supplyComponents()):
            if c.to_BoilerHotWater().is_initialized():
                c.to_BoilerHotWater().get().remove()
            if c.to_EvaporativeFluidCoolerSingleSpeed().is_initialized():
                c.to_EvaporativeFluidCoolerSingleSpeed().get().remove()
        ghx = openstudio.model.GroundHeatExchangerVertical(ground)
        loop_.addSupplyBranchForComponent(ghx)
        result = hvac.reference_hvac(
            ground, building={'storeys': 1, 'zone_types': types(ground, 'Office - enclosed')})
        self.assertEqual(['hp'], sorted({a.reference_system for a in result.assignments}),
                         'ground HX on the source loop = ground-source HP -> ASHP redirect')

    # D-39 (A4 ruled conditional): an UNHEATED refrigerated proposed block gets
    # the Table -B literal — a cooling-only TPFC reference (no boiler, no MAU
    # heating coil, zone heating a zero-capacity always-off placeholder); a
    # HEATED one keeps the two-pipe changeover per 8.4.4.1.(5).
    def test_system5_cooling_only_when_proposed_unheated(self):
        model = load_fixture()
        zones = sorted_zones(model)
        # cooling-only proposed: DX + fan air loop, no heating coil anywhere
        loop_ = openstudio.model.AirLoopHVAC(model)
        openstudio.model.FanConstantVolume(
            model, model.alwaysOnDiscreteSchedule()).addToNode(loop_.supplyInletNode())
        openstudio.model.CoilCoolingDXSingleSpeed(model).addToNode(loop_.supplyInletNode())
        for z in zones:
            loop_.addBranchForZone(z, openstudio.model.AirTerminalSingleDuctConstantVolumeNoReheat(
                model, model.alwaysOnDiscreteSchedule()).to_StraightComponent())

        result = hvac.reference_hvac(
            model, building={'storeys': 1,
                             'zone_types': types(model, 'Warehouse - refrigerated'),
                             'refrigerated_zones': [z.nameString() for z in zones]})
        self.assertEqual([5], sorted({a.reference_system for a in result.assignments}))
        ref = result.model
        self.assertEqual(0, len(ref.getBoilerHotWaters()), 'Table -B "None": no heating plant')
        self.assertTrue(len(ref.getChillerElectricEIRs()), 'chilled-water cooling present')
        self.assertTrue(len(ref.getZoneHVACFourPipeFanCoils()))
        self.assertEqual(0, len(ref.getCoilHeatingWaters()), 'no hydronic heating coils anywhere')
        for c in ref.getCoilHeatingElectrics():
            self.assertAlmostEqual(0.0, c.nominalCapacity().get(), delta=1e-9,
                                   msg='placeholder zone heating coil at zero capacity')

    def test_system5_keeps_heating_when_proposed_heated(self):
        model = self.proposed('Baseboard electric')
        zones = sorted_zones(model)
        result = hvac.reference_hvac(
            model, building={'storeys': 1,
                             'zone_types': types(model, 'Warehouse - refrigerated'),
                             'refrigerated_zones': [z.nameString() for z in zones]})
        self.assertEqual([5], sorted({a.reference_system for a in result.assignments}))
        self.assertTrue(len(result.model.getBoilerHotWaters()),
                        '8.4.4.1.(5): proposed heated -> reference heats (changeover kept)')

    # residential PTAC (compatible NON-heat-pump cooling) -> reference identical
    # to proposed (copy rule): nothing rebuilt
    def test_residential_ptac_copies_proposed(self):
        model = self.proposed('PTAC with baseboard electric')
        result = hvac.reference_hvac(
            model, building={'storeys': 1, 'zone_types': types(model, 'Multi-unit residential')})

        self.assertEqual(['copy_proposed'], sorted({a.action for a in result.assignments}))
        self.assertTrue(len(result.model.getZoneHVACPackagedTerminalAirConditioners()),
                        'PTACs retained')
        self.assertEqual(0, len(result.model.getAirLoopHVACs()))

    # data centre with >20 kW cooling -> System 2 (4PFC + water-cooled chiller)
    def test_data_centre_to_sys2(self):
        def oversize(m):
            for c in m.getCoilCoolingDXSingleSpeeds():
                c.setRatedTotalCoolingCapacity(30_000.0)
        model = self.proposed('PSZ RTU Electric and DX Coils and Electric Baseboard', oversize)
        result = hvac.reference_hvac(
            model, building={'storeys': 1, 'zone_types': types(model, 'Data centre')})

        self.assertEqual([2], sorted({a.reference_system for a in result.assignments}))
        self.assertTrue(len(result.model.getZoneHVACFourPipeFanCoils()),
                        'System 2 = four-pipe fan coils')
        self.assertTrue(len(result.model.getChillerElectricEIRs()))

    # proposed AIR-SOURCE heat pumps -> Table 8.4.4.13 ASHP reference with the
    # -10 degC heating cutoff. (D-37: was 'Water source heat pumps', which is by
    # Note A-8.4.4.13 a water-LOOP system that now correctly keeps Table -A —
    # see test_water_loop_hp_keeps_selection_ground_source_redirects.)
    def test_heat_pump_proposed_to_ashp_reference(self):
        model = self.proposed('PTHP')
        result = hvac.reference_hvac(
            model, building={'storeys': 1, 'zone_types': types(model, 'Office - enclosed')})

        self.assertEqual(['hp'], sorted({a.reference_system for a in result.assignments}))
        # D-46: the reference ASHP is a STAGED unitary (multispeed heating + cooling),
        # so the -10 degC cutoff lands on the multispeed coil.
        hp_coils = result.model.getCoilHeatingDXMultiSpeeds()
        self.assertTrue(len(hp_coils))
        self.assertEqual(0, len(result.model.getCoilHeatingDXSingleSpeeds()),
                         'reference ASHP heating is staged, not single-speed')
        for c in hp_coils:
            self.assertAlmostEqual(
                -10.0, c.minimumOutdoorDryBulbTemperatureforCompressorOperation(), delta=1e-6)

    # 8.4.4.8: oversizing = lesser of proposed and 30%/10% caps
    def test_oversizing_caps_and_audit_trail(self):
        model = self.proposed('Baseboard gas boiler')
        model.getSizingParameters().setHeatingSizingFactor(1.5)
        model.getSizingParameters().setCoolingSizingFactor(1.25)
        result = hvac.reference_hvac(
            model, building={'storeys': 1, 'zone_types': types(model, 'Office - enclosed')})

        self.assertAlmostEqual(1.3, result.model.getSizingParameters().heatingSizingFactor(),
                               delta=1e-6)
        self.assertAlmostEqual(1.1, result.model.getSizingParameters().coolingSizingFactor(),
                               delta=1e-6)

        entry = next(e for e in result.audit.entries
                     if 'oversizing capped' in e['action'])
        self.assertRegex(entry['value'], r'min\(proposed 1\.5, cap 1\.3\)')
        self.assertEqual('8.4.4.8.(1)-(2)', entry['article'])

        # the audit narrates the whole pipeline and serializes
        steps = {e['step'] for e in result.audit.entries}
        for s in ('characterize', 'selection', 'build', 'rules', 'efficiency'):
            self.assertIn(s, steps)
        self.assertTrue(len(json.loads(result.audit.to_json())) > 0)


if __name__ == '__main__':
    unittest.main()
