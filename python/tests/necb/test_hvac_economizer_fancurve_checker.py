"""Coverage-loop gate (hvac slices): 8.4.4.12 reference economizers, 8.4.4.17
fan power curves, and the Part 5 prescriptive checker.

The fan-power-curve case needs a SIZED model, so it runs EnergyPlus (Ruby skips
it without the openstudio CLI; the port skips it without a provisioned engine)."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import btap.modeling as modeling
from btap._compat import ruby_round
from btap.audit import AuditLog
from btap.necb import hvac
from btap.simulation import runner
from tests.necb.hvac_helpers import attach_weather, load_fixture, sorted_zones
from tests.support import needs_engine, needs_sdk


@needs_sdk
class TestEconomizerFancurveChecker(unittest.TestCase):

    def reference_for(self, system_zone_type, storeys=1):
        model = load_fixture()
        modeling.build_system(model, 'Baseboard gas boiler', sorted_zones(model))
        audit = AuditLog()
        result = hvac.reference_hvac(
            model, vintage='2020',
            building={'storeys': storeys,
                      'zone_types': {z.nameString(): system_zone_type
                                     for z in model.getThermalZones()},
                      'winter_design_temp_c': -20},
            audit=audit)
        return result, audit

    def test_reference_air_systems_get_economizers(self):
        result, audit = self.reference_for('Office - enclosed')  # sys3/PSZ with DX cooling
        economized = []
        for loop in result.model.getAirLoopHVACs():
            oa = loop.airLoopHVACOutdoorAirSystem()
            if (oa.is_initialized()
                    and oa.get().getControllerOutdoorAir().getEconomizerControlType()
                    == 'DifferentialEnthalpy'):
                economized.append(loop)
        self.assertTrue(economized,
                        '8.4.4.12: mechanically-cooled reference air systems get '
                        'DifferentialEnthalpy economizers')
        self.assertTrue(any('8.4.4.12' in str(e.get('article') or '') for e in audit.entries))

    @needs_engine
    def test_fan_power_curve_applied_after_sizing(self):
        # drive toward sys6/VAV if selected
        result, _ = self.reference_for('Office - open plan', storeys=5)
        reference = result.model
        if not len(reference.getFanVariableVolumes()):
            self.skipTest('no VAV fans in this reference selection')

        with tempfile.TemporaryDirectory() as tmp:
            attach_weather(reference)
            out = runner.run_energyplus(reference, str(Path(tmp) / 'sizing'), sizing_only=True)
            self.assertTrue(runner.is_clean_run(out), 'sizing run completes cleanly')
            audit = AuditLog()
            hvac.apply_efficiencies(reference, vintage='2020', audit=audit)

        fan = reference.getFanVariableVolumes()[0]
        self.assertAlmostEqual(0.227143, float(fan.fanPowerCoefficient1().get()), delta=1e-5,
                               msg='Table 8.4.4.17 row applied (small fan -> airfoil riding)')
        self.assertAlmostEqual(0.47, fan.fanPowerMinimumFlowFraction(), delta=1e-6,
                               msg='below-D floor via minimum-flow clamp')
        self.assertTrue(any('8.4.4.17' in str(e.get('article') or '') for e in audit.entries))

    def test_part5_checker(self):
        model = load_fixture()
        modeling.build_system(
            model, 'PSZ RTU with exhaust Gas and DX Coils and Hot Water Baseboard',
            sorted_zones(model))
        # cripple a DX coil below the code minimum (hard-sized: the 5.2.12 lookup
        # bins by capacity, so unsized equipment cannot be checked)
        coil = model.getCoilCoolingDXSingleSpeeds()[0]
        coil.setRatedTotalCoolingCapacity(10_000.0)
        coil.setRatedAirFlowRate(0.5)
        coil.setRatedCOP(1.5)
        # strip economizers; hard-size flows at 50% OA so the 5.2.10.1 table
        # trigger (continuous Always On, HDD >= 3000 -> Table -B "R") fires
        for loop in model.getAirLoopHVACs():
            oa = loop.airLoopHVACOutdoorAirSystem()
            if not oa.is_initialized():
                continue

            oa.get().getControllerOutdoorAir().setEconomizerControlType('NoEconomizer')
            loop.setDesignSupplyAirFlowRate(0.5)
            oa.get().getControllerOutdoorAir().setMinimumOutdoorAirFlowRate(0.25)

        audit = hvac.check_part5(model, vintage='2020', hdd=3890)
        warnings = [w['action'] for w in audit.warnings]
        self.assertTrue(any('NO economizer' in w for w in warnings), '5.2.2.8 violation flagged')
        self.assertTrue(any('NO heat/energy recovery' in w for w in warnings),
                        '5.2.10.1 table-trigger violation flagged')
        self.assertTrue(any('BELOW the NECB 2020 minimum' in w for w in warnings),
                        '5.2.12 violation flagged (COP 1.5)')
        self.assertTrue(any(e['step'] == 'check_part5' and e['level'] == 'decision'
                            for e in audit.entries))
        crippled = []
        for c in model.getCoilCoolingDXSingleSpeeds():
            value = c.ratedCOP()
            value = value.get() if hasattr(value, 'is_initialized') else value
            if ruby_round(value, 2) == 1.5:
                crippled.append(c)
        self.assertTrue(crippled, 'checker NEVER modifies the model')


if __name__ == '__main__':
    unittest.main()
