"""P4 gate: the bare-geometry on-ramp produces a SIMULABLE model — strip the
fixture's loads entirely, rebuild them from NECB data, run EnergyPlus for a
January week on ideal air, and prove the loads are live (people/equipment
energy) and the NECB set-points condition the zones. Plus the three-gem
composition smoke: loads -> hvac -> envelope with ONE audit.

Port of btap-necb/test/test_loads_e2e_run.rb. The Ruby test read the End Uses
rows straight out of the SQL; here the same TabularData rows arrive through
btap.simulation's energy_results (the ported runner parses exactly those GJ
rows), so the assertions are the same quantities.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tests.support import DDY, EPW, load_fixture, needs_engine, needs_sdk

OFFICE = ['Space Function', 'Office enclosed > 25 m2']


def bare_geometry():
    """The fixture minus every load: space types, thermostats, internal loads."""
    model = load_fixture()
    for collection in (model.getThermostatSetpointDualSetpoints(),
                       model.getPeoples(), model.getPeopleDefinitions(),
                       model.getElectricEquipments(),
                       model.getElectricEquipmentDefinitions(),
                       model.getLightss(), model.getLightsDefinitions(),
                       model.getSpaceInfiltrationDesignFlowRates(),
                       model.getDesignSpecificationOutdoorAirs(),
                       model.getDefaultScheduleSets(), model.getSpaceTypes()):
        for obj in list(collection):
            obj.remove()
    return model


def office_map(model):
    return {s.nameString(): OFFICE for s in model.getSpaces()}


@needs_engine
class TestE2ERun(unittest.TestCase):
    def test_bare_geometry_to_clean_energyplus_run(self):
        from btap.audit import AuditLog
        from btap.necb import loads
        from btap.simulation import run

        model = bare_geometry()
        self.assertEqual([], list(model.getPeoples()))
        self.assertFalse(any(z.thermostatSetpointDualSetpoint().is_initialized()
                             for z in model.getThermalZones()))

        audit = AuditLog()
        loads.assign_space_types(model, office_map(model), vintage='2020', audit=audit)
        loads.apply_loads(model, vintage='2020', audit=audit)

        self.assertTrue(all(z.thermostatSetpointDualSetpoint().is_initialized()
                            for z in model.getThermalZones()),
                        'space-type thermostats hooked to every zone')

        for zone in model.getThermalZones():
            zone.setUseIdealAirLoads(True)
        with tempfile.TemporaryDirectory(prefix='osloads-e2e-') as tmp:
            result = run(model, run_dir=str(Path(tmp) / 'loads'),
                         weather={'epw': str(EPW), 'ddy': str(DDY)},
                         run_period={'begin_month': 1, 'begin_day': 1,
                                     'end_month': 1, 'end_day': 7})
            self.assertTrue(result.is_clean(), 'NECB loads on bare geometry')

            end_uses = result.energy['end_uses_kwh']
            self.assertGreater(end_uses['interior_equipment'], 0, 'plug loads are alive')
            self.assertGreater(
                end_uses['heating'], 0,
                'NECB heating set-points drive conditioning in a Toronto January week')


@needs_sdk
class TestThreeDomainComposition(unittest.TestCase):
    def test_three_gem_composition_one_audit(self):
        import json

        import btap.modeling as modeling
        from btap._compat import sorted_by_name
        from btap.audit import AuditLog

        # Plain import: M5 delivered this. A guard here would let a
        # regression that removes apply_prescriptive pass as a green skip.
        from btap.necb import envelope, loads
        apply_prescriptive = envelope.apply_prescriptive

        model = bare_geometry()
        audit = AuditLog()
        loads.assign_space_types(model, office_map(model), vintage='2020', audit=audit)
        loads.apply_loads(model, vintage='2020', audit=audit)
        modeling.build_system(model, 'Baseboard gas boiler',
                              sorted_by_name(model.getThermalZones()))
        apply_prescriptive(model, vintage='2020', hdd=3890, audit=audit)

        steps = list(dict.fromkeys(e['step'] for e in audit.entries))
        for step in ('loads', 'schedules', 'coverage', 'prescriptive'):
            self.assertIn(step, steps)
        self.assertNotEqual([], list(model.getPlantLoops()),
                            'HVAC built on the loaded model')
        self.assertNotEqual([], list(model.getPeoples()), 'loads present')
        wall = next(s for s in model.getSurfaces()
                    if s.outsideBoundaryCondition() == 'Outdoors'
                    and s.surfaceType() == 'Wall')
        # D-23: table 0.265 is OVERALL U (incl. films) — constructions are named by
        # the construction-only conductance 1/(1/0.265 - R_films) = 0.2759.
        self.assertRegex(
            wall.construction().get().nameString(), r':U-0\.2759',
            'prescriptive CONSTRUCTION-ONLY target for the 0.265 overall table value '
            '(HDD 3890 wall target)')
        entries = json.loads(audit.to_json())
        self.assertGreater(len(entries), 20, 'ONE audit spans loads + envelope decisions')
        self.assertTrue(any(e['step'] == 'loads' for e in audit.entries)
                        and any(e['step'] == 'prescriptive' for e in audit.entries))


if __name__ == '__main__':
    unittest.main()
