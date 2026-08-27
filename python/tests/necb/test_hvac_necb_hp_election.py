"""D-52 — 8.4.4.13.(2)(g): the reference heat pump's auxiliary-heating energy
type is elected from the proposed building's annual delivered-heat data, with
the 33% proviso, (g)(i)/(g)(ii) scoping, and the audited structural-proxy
fallback. The election itself is pure data logic; the inventory half is
exercised against a real SYS3-ASHP build."""

from __future__ import annotations

import re
import unittest

import btap.modeling as modeling
from btap.audit import AuditLog
from btap.modeling.hvac import classify
from btap.necb import hvac
from tests.necb.hvac_helpers import load_fixture, sorted_zones
from tests.support import needs_sdk

SYS3_ASHP = 'PSZ RTU ASHP with Gas and ASHP with Gas Supp. Heat Coils and Electric Baseboard'

HP_RULES = {'aux_energy_type_threshold_fraction': 0.33}


def group(zones=None, air_loop='Loop 1', sources=None, source_loops=None):
    return {'zones': zones or ['Zone A'], 'air_loop': air_loop, 'heat_pump': True,
            'heat_pump_sources': ['air'] if sources is None else sources,
            'heat_pump_source_loops': source_loops or []}


def facts_for(*groups):
    return {'zone_groups': list(groups)}


class TestNecbHpElection(unittest.TestCase):
    """The election half — pure data logic, no SDK."""

    def test_gate_passes_and_the_largest_terminal_fuel_is_elected(self):
        audit = AuditLog()
        g = group()
        annual = {'loops': {'Loop 1': {'hp_j': 60e9,
                                       'aux': [{'fuel': 'NaturalGas', 'j': 30e9}]}},
                  'zones': {'Zone A': [{'fuel': 'Electricity', 'j': 10e9, 'role': 'aux'}]}}
        elected = hvac.heat_pump_aux_energy_type(g, facts_for(g), HP_RULES, annual, audit)
        self.assertEqual('gas', elected,
                         'gas terminal energy (30 GJ) beats electric (10 GJ); HP share 60% > 33%')
        entry = next(e for e in audit.entries if 'ELECTED' in e['action'])
        self.assertEqual('8.4.4.13.(2)(g)(i)', entry['article'])
        self.assertIn('D-52', str(entry.get('ruling') or ''))

    def test_gate_fails_falls_back_to_the_structural_proxy(self):
        audit = AuditLog()
        g = group()
        annual = {'loops': {'Loop 1': {'hp_j': 10e9,
                                       'aux': [{'fuel': 'NaturalGas', 'j': 90e9}]}},
                  'zones': {}}
        elected = hvac.heat_pump_aux_energy_type(g, facts_for(g), HP_RULES, annual, audit)
        self.assertIsNone(elected,
                          'share 10% <= 33% — the proviso is unmet, sentence (g) does not elect')
        entry = next((e for e in audit.entries if 'NOT above' in e['action']), None)
        self.assertIsNotNone(entry, 'the gate failure is an audited decision naming the proxy')

    def test_no_terminal_heating_falls_back(self):
        audit = AuditLog()
        g = group()
        annual = {'loops': {'Loop 1': {'hp_j': 50e9, 'aux': []}}, 'zones': {}}
        self.assertIsNone(hvac.heat_pump_aux_energy_type(g, facts_for(g), HP_RULES, annual, audit))
        self.assertTrue(any('nothing to elect' in e['action'] for e in audit.entries))

    def test_no_annual_data_falls_back_with_the_sizing_note(self):
        audit = AuditLog()
        g = group()
        self.assertIsNone(hvac.heat_pump_aux_energy_type(g, facts_for(g), HP_RULES, None, audit))
        self.assertTrue(any('no proposed annual data' in e['action'] for e in audit.entries))

    def test_g_ii_aggregates_over_groups_sharing_the_source_water_loop(self):
        audit = AuditLog()
        a = group(zones=['Zone A'], air_loop='Loop 1', sources=['external'],
                  source_loops=['GHX Loop'])
        b = group(zones=['Zone B'], air_loop='Loop 2', sources=['external'],
                  source_loops=['GHX Loop'])
        annual = {'loops': {'Loop 1': {'hp_j': 40e9,
                                       'aux': [{'fuel': 'Electricity', 'j': 10e9}]},
                            'Loop 2': {'hp_j': 40e9,
                                       'aux': [{'fuel': 'NaturalGas', 'j': 30e9}]}},
                  'zones': {}}
        elected = hvac.heat_pump_aux_energy_type(a, facts_for(a, b), HP_RULES, annual, audit)
        self.assertEqual('gas', elected,
                         "(g)(ii): group A alone would elect electric; the shared-loop union "
                         "brings in B's 30 GJ of gas")
        entry = next(e for e in audit.entries if 'ELECTED' in e['action'])
        self.assertEqual('8.4.4.13.(2)(g)(ii)', entry['article'])
        self.assertEqual(['Loop 1', 'Loop 2'], entry['inputs']['scope_loops'])


@needs_sdk
class TestNecbHpElectionWiring(unittest.TestCase):
    """The finalize wiring and the inventory half — needs a real build."""

    def load_and_build(self):
        model = load_fixture()
        modeling.build_system(model, SYS3_ASHP, sorted_zones(model))
        return model

    def test_election_wires_into_finalize_through_reference_hvac(self):
        model = load_fixture()
        zones = sorted_zones(model)
        modeling.build_system(model, SYS3_ASHP, zones)

        # Hand-built annual data naming the proposed loop: electric baseboards carry
        # far more energy than the gas supplemental, and the HP clears the gate —
        # the elected variant must be ELECTRIC even though the structural proxy
        # (gas supplemental present) would elect gas.
        loop_name = model.getAirLoopHVACs()[0].nameString()
        zone_data = {z.nameString(): [{'fuel': 'Electricity', 'j': 20e9, 'role': 'aux'}]
                     for z in zones}
        annual = {'loops': {loop_name: {'hp_j': 200e9,
                                        'aux': [{'fuel': 'NaturalGas', 'j': 5e9}]}},
                  'zones': zone_data}

        audit = AuditLog()
        result = hvac.reference_hvac(model, vintage='2020', audit=audit, proposed_annual=annual)
        hp = next((a for a in result.assignments if a.reference_system == 'hp'), None)
        self.assertIsNotNone(hp, 'the ASHP proposed redirects to the hp reference')
        self.assertEqual('electric', hp.energy_type,
                         'annual election (electric baseboards dominate) overrides the '
                         'structural gas proxy')
        without = hvac.reference_hvac(self.load_and_build(), vintage='2020', audit=AuditLog())
        proxy = next(a for a in without.assignments if a.reference_system == 'hp')
        self.assertEqual('gas', proxy.energy_type,
                         'control: the structural proxy elects gas without annual data')

    def test_inventory_finds_hp_aux_and_baseboards_on_a_real_build(self):
        model = self.load_and_build()
        inventory = classify.heating_election_inventory(model)

        loop_name = model.getAirLoopHVACs()[0].nameString()
        entry = inventory['loops'].get(loop_name)
        self.assertIsNotNone(entry, 'the ASHP loop appears in the inventory')
        self.assertTrue(any(re.search(r'HeatingDX', n, re.IGNORECASE) for n in entry['hp']),
                        f"DX heating coil in hp: {entry['hp']}")
        self.assertTrue(any(a['fuel'] == 'NaturalGas' for a in entry['aux']),
                        'gas supplemental coil in aux')

        flat = [e for entries in inventory['zones'].values() for e in entries]
        baseboards = [e for e in flat if e['variable'] == classify.BASEBOARD_VARIABLE]
        self.assertTrue(baseboards, 'electric baseboards inventoried per zone')
        self.assertTrue(all(e['fuel'] == 'Electricity' and e['role'] == 'aux'
                            for e in baseboards))


if __name__ == '__main__':
    unittest.main()
