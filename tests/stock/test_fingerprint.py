"""Equipment fingerprints (#256): identify a zone's HVAC by what it is.

The full measurements live in `scripts/fingerprint_eval/` (every catalogue
row, leave-one-row-out, metamorphic pairs, the 28 archetypes, and the NECB
reference builder as ground truth). These tests pin the behaviours each
finding fixed, on the five-zone fixture.
"""

from __future__ import annotations

import unittest

from tests.support import needs_sdk


def _built(*rows, zones=None, config=None, mutate=None):
    from btap.modeling import build_system
    from tests.necb.hvac_helpers import load_fixture, sorted_zones
    model = load_fixture()
    served = sorted_zones(model) if zones is None else sorted_zones(model)[:zones]
    for row in rows:
        build_system(model, row, served, config=config)
    if mutate:
        mutate(model)
    for i, loop in enumerate(model.getAirLoopHVACs()):
        loop.setName(f'Air System {i + 1}')
    for i, loop in enumerate(model.getPlantLoops()):
        loop.setName(f'Plant {i + 1}')
    return model


def _zone(model, index=0):
    from btap.stock import fingerprint
    return fingerprint.model_components(model)[index][1]


_CATALOGUE = {}


def _catalogue(*rows):
    """Fingerprints of the named rows, built once per test run."""
    for row in rows:
        if row not in _CATALOGUE:
            _CATALOGUE[row] = _zone(_built(row))
    return {row: _CATALOGUE[row] for row in rows}


ROWS = ('psz-gas-hwbb-gasboiler', 'psz-gas-perzone', 'bb-hwbb-gasboiler', 'uh-hw-gasboiler',
        'uh-gas', 'doas-elec', 'psz-elec-perzone', 'mau-fc4-gas-gasboiler-scrollchiller',
        'mau-fc2-gas-gasboiler-scrollchiller', 'doas-acb-elec-elecbb-acscrollchiller',
        'doas-pcb-elec-elecbb-acscrollchiller')


@needs_sdk
class TestTheFingerprint(unittest.TestCase):

    def test_a_built_row_matches_itself_on_every_zone(self):
        from btap.stock import fingerprint
        catalogue = _catalogue(*ROWS)
        for row in ROWS:
            model = _built(row)
            for zone_name, comps in fingerprint.model_components(model):
                with self.subTest(row=row, zone=zone_name):
                    result = fingerprint.explain(comps, catalogue)
                    self.assertEqual('match', result['outcome'], result)
                    self.assertIn(row, result['systems'])

    def test_rows_that_differ_are_told_apart(self):
        """Each pair was ONE class before its fix: 100% outdoor air vs a
        zone-following unit (both are 100% OA), two-pipe vs four-pipe
        (coil availability, identity only on fan coils), active vs passive
        beams (an identity field), gas vs hot-water unit heaters."""
        from btap.stock import fingerprint
        catalogue = _catalogue(*ROWS)
        for a, b in (('doas-elec', 'psz-elec-perzone'),
                     ('mau-fc4-gas-gasboiler-scrollchiller', 'mau-fc2-gas-gasboiler-scrollchiller'),
                     ('doas-acb-elec-elecbb-acscrollchiller', 'doas-pcb-elec-elecbb-acscrollchiller'),
                     ('uh-gas', 'uh-hw-gasboiler')):
            with self.subTest(pair=(a, b)):
                self.assertNotEqual(fingerprint.signature(catalogue[a]),
                                    fingerprint.signature(catalogue[b]))

    def test_what_authors_legitimately_change_does_not_change_the_answer(self):
        import openstudio

        from btap.stock import fingerprint

        def exhaust_fans(model):
            for zone in model.getThermalZones():
                openstudio.model.FanZoneExhaust(model).addToThermalZone(zone)

        def scheduled_plant(model):
            for loop in model.getPlantLoops():
                node = loop.supplyOutletNode()
                for spm in node.setpointManagers():
                    if spm.to_SetpointManagerOutdoorAirReset().is_initialized():
                        spm.remove()
                        schedule = openstudio.model.ScheduleConstant(model)
                        schedule.setValue(82.0)
                        openstudio.model.SetpointManagerScheduled(model, schedule).addToNode(node)

        catalogue = _catalogue(*ROWS)
        for label, model in (('one zone, not five', _built('psz-gas-hwbb-gasboiler', zones=1)),
                             ('exhaust fans', _built('psz-gas-hwbb-gasboiler', mutate=exhaust_fans)),
                             ('scheduled plant setpoint',
                              _built('psz-gas-hwbb-gasboiler', mutate=scheduled_plant)),
                             ('staged coils in a unitary wrapper',
                              _built('psz-gas-hwbb-gasboiler', config={'staged_coils': True}))):
            with self.subTest(label):
                result = fingerprint.explain(_zone(model), catalogue)
                self.assertEqual('match', result['outcome'], result)
                self.assertIn('psz-gas-hwbb-gasboiler', result['systems'])
                if label == 'scheduled plant setpoint':
                    self.assertIn('plant:heating:spm:SetpointManager_Scheduled',
                                  result['control_differences']['model_only'])

    def test_100_percent_outdoor_air_is_read_from_operation_not_sizing(self):
        """EnergyPlus uses the sizing "100% outdoor air" flags for SIZING only;
        the SDK's own Appendix G System 5 and 7 VAV set them while running on
        mixed air, and every independent VAV model failed to match until the
        controller was read instead (OpenStudio-resources, 2026-11-28)."""
        from btap.stock import fingerprint

        def sizing_flags(model):
            for loop in model.getAirLoopHVACs():
                loop.sizingSystem().setAllOutdoorAirinCooling(True)
                loop.sizingSystem().setAllOutdoorAirinHeating(True)

        plain = _zone(_built('psz-gas-hwbb-gasboiler'))
        flagged = _zone(_built('psz-gas-hwbb-gasboiler', mutate=sizing_flags))
        self.assertEqual(fingerprint.signature(plain), fingerprint.signature(flagged))
        # ...while a DOAS, whose controller runs on outdoor air only, keeps it
        doas = _zone(_built('doas-elec'))
        self.assertTrue(any('ahu:all_outdoor_air' in c.identity for c in doas))

    def test_a_different_fuel_is_a_different_system(self):
        from btap.stock import fingerprint
        catalogue = _catalogue(*ROWS)
        model = _built('bb-hwbb-gasboiler', config={'boiler_fuel': 'Electricity'})
        result = fingerprint.explain(_zone(model), catalogue)
        self.assertNotEqual('match', result['outcome'], result)

    def test_stacked_equipment_is_COMPOSED_from_several_rows(self):
        """A rooftop unit plus unit heaters: no row builds both, two do."""
        from btap.stock import fingerprint
        catalogue = _catalogue(*ROWS)
        model = _built('psz-gas-perzone', 'uh-hw-gasboiler')
        result = fingerprint.explain(_zone(model), catalogue)
        self.assertEqual('composed', result['outcome'], result)
        self.assertEqual({'psz-gas-perzone', 'uh-hw-gasboiler'},
                         {cls[0] for cls in result['systems']})
        # ...and a row that is not in the catalogue leaves an uncovered part
        partial = fingerprint.explain(_zone(model), _catalogue('psz-gas-perzone', 'uh-gas'))
        self.assertEqual('partial', partial['outcome'], partial)
        self.assertEqual([['psz-gas-perzone']], partial['systems'])
        self.assertEqual(1, len(partial['uncovered']))

    def test_the_cover_is_exact_not_greedy(self):
        """Fable, review of the prototype: zone {a, b, c} with rows {a, b},
        {b, c} and {a}. Greedy took {a, b} first and reported `partial`;
        {b, c} + {a} builds it exactly."""
        from btap.stock.fingerprint import Component, explain

        def comp(token):
            c = Component('unit')
            c.identity = {token}
            return c
        catalogue = {'ab': [comp('a'), comp('b')], 'bc': [comp('b'), comp('c')], 'a': [comp('a')]}
        result = explain([comp('a'), comp('b'), comp('c')], catalogue)
        self.assertEqual('composed', result['outcome'], result)
        self.assertEqual([['a'], ['bc']], sorted(result['systems']))

    def test_the_fingerprint_does_not_depend_on_walk_order(self):
        """The transient self-match failure: a condenser loop shared by a
        chiller and a heating heat pump was named by whichever coil the walk
        reached first, and that is the SDK's hash order. Reversing and
        shuffling every child list must not change the fingerprint."""
        import random

        from btap.stock import fingerprint
        model = _built('doas-fc4-hw-chw-gshp-elecboiler')
        baseline = [fingerprint.signature(c) for _, c in fingerprint.model_components(model)]
        original = fingerprint._children_by_container
        try:
            for seed in (None, 1, 2, 3):
                def shuffled(m, seed=seed):
                    out = original(m)
                    for kids in out.values():
                        if seed is None:
                            kids.reverse()
                        else:
                            random.Random(seed).shuffle(kids)
                    return out
                fingerprint._children_by_container = shuffled
                with self.subTest(order='reversed' if seed is None else f'shuffle {seed}'):
                    self.assertEqual(baseline, [fingerprint.signature(c)
                                                for _, c in fingerprint.model_components(model)])
        finally:
            fingerprint._children_by_container = original

    def test_nothing_known_is_NONE_with_the_differences(self):
        from btap.stock import fingerprint
        model = _built('uh-gas')
        result = fingerprint.explain(_zone(model), _catalogue('bb-hwbb-gasboiler'))
        self.assertEqual('none', result['outcome'])
        self.assertEqual(['bb-hwbb-gasboiler'], result['systems'])
        self.assertTrue(result['nearest_differences'])

    def test_an_unserved_zone_says_so(self):
        from btap.stock import fingerprint
        model = _built('bb-hwbb-gasboiler', zones=1)
        self.assertEqual('unserved', fingerprint.explain(_zone(model, index=1), _catalogue(*ROWS))['outcome'])


@needs_sdk
class TestTheReadersAreExact(unittest.TestCase):

    def test_always_on_is_read_from_the_values_not_the_name(self):
        import openstudio

        from btap.stock.fingerprint import _schedule_is_always_on
        model = openstudio.model.Model()
        for name, value, expected in (('Always_On', 1.0, True), ('whatever', 1.0, True),
                                      ('Always On', 0.0, False)):
            schedule = openstudio.model.ScheduleConstant(model)
            schedule.setName(name)
            schedule.setValue(value)
            with self.subTest(name=name, value=value):
                self.assertIs(expected, _schedule_is_always_on(schedule))

    def test_the_cast_table_reaches_the_classes_the_SDK_abbreviates(self):
        """`ZoneHVAC:LowTemperatureRadiant:VariableFlow` is the SDK's
        `ZoneHVACLowTempRadiantVarFlow`: name-mangling the IDD name missed
        it, and the radiant coils with it."""
        from btap.stock.fingerprint import _cast_table
        table = _cast_table()
        for kind in ('ZoneHVAC_LowTemperatureRadiant_VariableFlow',
                     'ZoneHVAC_LowTemperatureRadiant_ConstantFlow',
                     'Coil_Heating_LowTemperatureRadiant_VariableFlow'):
            with self.subTest(kind=kind):
                self.assertIn(kind, table)

    def test_a_multistage_gas_coil_is_natural_gas(self):
        """EnergyPlus's Coil:Heating:Gas:MultiStage has no fuel field: the
        staged NECB reference lost its fuel, and stopped matching its row."""
        import openstudio

        from btap.stock.fingerprint import _concrete, _token
        model = openstudio.model.Model()
        coil = openstudio.model.CoilHeatingGasMultiStage(model)
        self.assertEqual('Coil_Heating_Gas[fuelType=NaturalGas]',
                         _token('Coil_Heating_Gas_MultiStage', _concrete(coil)))


if __name__ == '__main__':
    unittest.main()
