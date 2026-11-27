"""The 8.4.x.13.(2)(g) auxiliary-fuel election sees a HOT-WATER heat pump (#244).

`classify.heating_election_inventory` recognised only DX air-loop coils and
zonal heat-pump coils as `hp`. On a heat-pump hot-water plant every terminal
read as `aux` with the plant's fuels joined, so `prepare_annual` saw no heat
pump, requested nothing, and an ANNUAL run's audit said "no proposed annual
data (simulate: :sizing/:none ...)" for every block (measured on a
`bb-hwbb-awhp-gasbu` proposed, 2026-11-27). Now the inventory names the
plant, and the umbrella splits each terminal's delivered heat by the plant's
own measured heat-pump / boiler split.
"""

from __future__ import annotations

import unittest
from unittest import mock

from tests.support import needs_sdk


def _built(system):
    from btap import modeling
    from btap._compat import sorted_by_name
    from tests.support import load_fixture
    model = load_fixture()
    modeling.build_system(model, system, sorted_by_name(model.getThermalZones()))
    return model


@needs_sdk
class TestTheInventory(unittest.TestCase):

    def test_hot_water_terminals_on_a_heat_pump_plant_name_it(self):
        from btap.modeling.hvac import classify
        inv = classify.heating_election_inventory(_built('vav-hw-hwbb-awhp-gasbu-scrollchiller'))
        self.assertEqual(['Heat Pump Hot Water Loop'], list(inv['plants']))
        self.assertEqual([{'name': 'Backup Boiler', 'fuel': 'NaturalGas'}],
                         inv['plants']['Heat Pump Hot Water Loop']['aux'])
        zone_entries = [e for es in inv['zones'].values() for e in es]
        loop_aux = [a for e in inv['loops'].values() for a in e['aux']]
        self.assertTrue(zone_entries and loop_aux)
        for e in zone_entries + loop_aux:
            self.assertEqual('Heat Pump Hot Water Loop', e.get('plant'), e)

    def test_a_boiler_plant_is_not_one(self):
        from btap.modeling.hvac import classify
        inv = classify.heating_election_inventory(_built('vav-hw-hwbb-gasboiler-scrollchiller'))
        self.assertEqual({}, inv['plants'])
        self.assertFalse(any('plant' in e for es in inv['zones'].values() for e in es))


@needs_sdk
class TestTheSplit(unittest.TestCase):
    """The arithmetic, with the run-period sums controlled (no simulation)."""

    def run_split(self, system, sums):
        from btap.audit import AuditLog
        from btap.codes.necb import path
        from btap.modeling.hvac import classify
        model = _built(system)
        inv = classify.heating_election_inventory(model)
        with mock.patch.object(path.runner, 'run_period_sums',
                               side_effect=lambda _m, variable: sums.get(variable, {})):
            return inv, path._heating_election_data(model, inv, AuditLog())

    def test_each_terminal_is_split_by_the_plants_own_shares(self):
        from btap.modeling.hvac import classify
        inv = classify.heating_election_inventory(_built('bb-hwbb-awhp-gasbu'))
        names = [e['name'].upper() for es in inv['zones'].values() for e in es]
        sums = {classify.BASEBOARD_VARIABLE: {n: 10e9 for n in names},          # 10 GJ each
                classify.PLANT_HEAT_PUMP_VARIABLE: {'AIR-TO-WATER HEAT PUMP': 30e9},
                classify.BOILER_VARIABLE: {'BACKUP BOILER': 10e9}}           # 75% / 25%
        _, data = self.run_split('bb-hwbb-awhp-gasbu', sums)
        for zone, entries in data['zones'].items():
            with self.subTest(zone=zone):
                by_role = {(e['role'], e['fuel']): e['j'] for e in entries}
                self.assertEqual({('hp', 'Electricity'), ('aux', 'NaturalGas')}, set(by_role))
                self.assertAlmostEqual(7.5e9, by_role[('hp', 'Electricity')])
                self.assertAlmostEqual(2.5e9, by_role[('aux', 'NaturalGas')])

    def test_an_air_loop_coil_on_the_plant_adds_to_the_loop_heat_pump(self):
        from btap.modeling.hvac import classify
        inv = classify.heating_election_inventory(_built('vav-hw-hwbb-awhp-gasbu-scrollchiller'))
        loop_coils = [a['name'].upper() for e in inv['loops'].values() for a in e['aux']]
        sums = {classify.COIL_VARIABLE: {n: 8e9 for n in loop_coils},
                classify.PLANT_HEAT_PUMP_VARIABLE: {'AIR-TO-WATER HEAT PUMP': 1e9},
                classify.BOILER_VARIABLE: {'BACKUP BOILER': 1e9}}            # 50% / 50%
        _, data = self.run_split('vav-hw-hwbb-awhp-gasbu-scrollchiller', sums)
        loop = next(iter(data['loops'].values()))
        self.assertAlmostEqual(4e9 * len(loop_coils), loop['hp_j'])
        self.assertEqual([('NaturalGas', 4e9)] * len(loop_coils),
                         [(a['fuel'], a['j']) for a in loop['aux']])

    def test_a_plant_that_delivered_nothing_is_left_unsplit(self):
        from btap.modeling.hvac import classify
        _, data = self.run_split('bb-hwbb-awhp-gasbu', {classify.BASEBOARD_VARIABLE: {}})
        for entries in data['zones'].values():
            self.assertEqual(['aux'], [e['role'] for e in entries])


@needs_sdk
class TestTheElectionPoolsThePlantsBlocks(unittest.TestCase):
    """(g)(i): "the thermal blocks ... served by that heat pump" — ALL of them.
    Fable's case: one air-to-water plant on five blocks plus an electric
    baseboard in Zone 1. Per block, Zones 2-5 elected gas at a 40% share; pooled
    over the plant's five blocks the share is 25%, under the 33% proviso, so
    the clause elects nothing and the structural proxy decides."""

    def selection(self, sums):
        import openstudio

        from btap._compat import sorted_by_name
        from btap.audit import AuditLog
        from btap.codes.necb import hvac, path
        from btap.modeling.hvac import classify
        model = _built('bb-hwbb-awhp-gasbu')
        zone1 = sorted_by_name(model.getThermalZones())[0]
        extra = openstudio.model.ZoneHVACBaseboardConvectiveElectric(model)
        extra.setName('Zone 1 Electric Baseboard')
        extra.addToThermalZone(zone1)
        inv = classify.heating_election_inventory(model)
        with mock.patch.object(path.runner, 'run_period_sums',
                               side_effect=lambda _m, variable: sums(inv).get(variable, {})):
            data = path._heating_election_data(model, inv, AuditLog())
        audit = AuditLog()
        hvac.reference_hvac(model, code='necb2020', audit=audit, proposed_annual=data)
        return data, audit

    @staticmethod
    def mixed(inv):
        from btap.modeling.hvac import classify
        water = [e['name'].upper() for es in inv['zones'].values() for e in es if e.get('plant')]
        return {classify.BASEBOARD_VARIABLE: {**{n: 10e9 for n in water},
                                              'ZONE 1 ELECTRIC BASEBOARD': 30e9},
                classify.PLANT_HEAT_PUMP_VARIABLE: {'AIR-TO-WATER HEAT PUMP': 4e9},
                classify.BOILER_VARIABLE: {'BACKUP BOILER': 6e9}}          # 40% / 60%

    def test_the_plant_names_all_five_blocks(self):
        data, _ = self.selection(self.mixed)
        self.assertEqual(5, len(data['plant_members']['Heat Pump Hot Water Loop']['zones']))

    def test_pooled_below_the_proviso_no_block_elects(self):
        _, audit = self.selection(self.mixed)
        elected = [e for e in audit.entries if 'ELECTED' in e['action']]
        refused = [e for e in audit.entries if 'NOT above' in e['action']]
        self.assertEqual([], elected, 'no block may elect: the pooled share is 25%')
        self.assertTrue(refused)
        for e in refused:
            self.assertIn('25.0%', e['action'], e['action'])


@needs_sdk
class TestAPlantWithAnUnmeasuredSourceIsNotSplit(unittest.TestCase):
    """District heat (or another heat-pump type) on the loop would otherwise be
    attributed pro rata to the heat pump and boiler, or read as 0 J."""

    def test_district_heat_on_the_loop_leaves_it_unsplit(self):
        import openstudio

        from btap.modeling.hvac import classify
        model = _built('bb-hwbb-awhp-gasbu')
        loop = next(pl for pl in model.getPlantLoops() if pl.nameString() == 'Heat Pump Hot Water Loop')
        district = openstudio.model.DistrictHeatingWater(model)
        loop.addSupplyBranchForComponent(district)
        self.assertEqual({}, classify.heating_election_inventory(model)['plants'])


@needs_sdk
class TestPrepareAnnualAsksForThem(unittest.TestCase):
    """The call site: without this, nothing is requested and the election
    never runs on an annual run, which is the defect."""

    def prepare(self, system):
        import types

        from btap.codes.necb import path
        run = types.SimpleNamespace(proposed=_built(system), report={"proposed": {}}, state={})
        asked = []
        with mock.patch.object(path.runner, 'request_run_period_variables',
                               side_effect=lambda _m, variables: asked.extend(variables)):
            path.prepare_annual(run)
        return run, asked

    def test_a_heat_pump_hot_water_plant_requests_the_plant_sums(self):
        from btap.modeling.hvac import classify
        run, asked = self.prepare('bb-hwbb-awhp-gasbu')
        self.assertIsNotNone(run.state["heating_election_inventory"])
        self.assertIn(classify.PLANT_HEAT_PUMP_VARIABLE, asked)
        self.assertIn(classify.BOILER_VARIABLE, asked)

    def test_a_boiler_only_building_requests_nothing(self):
        run, asked = self.prepare('bb-hwbb-gasboiler')
        self.assertIsNone(run.state["heating_election_inventory"])
        self.assertEqual([], asked)


if __name__ == "__main__":
    unittest.main()
