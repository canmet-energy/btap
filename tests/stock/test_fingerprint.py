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
                        # the same hottest temperature, a different kind of manager
                        reset = spm.to_SetpointManagerOutdoorAirReset().get()
                        hottest = max(reset.setpointatOutdoorLowTemperature(),
                                      reset.setpointatOutdoorHighTemperature())
                        spm.remove()
                        schedule = openstudio.model.ScheduleConstant(model)
                        schedule.setValue(hottest)
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

    def test_identical_units_are_one_system_and_the_count_is_reported(self):
        """phylroy (2026-11-28): a unit count is a control. Two identical
        baseboards in a zone match the one-baseboard row, with the count
        listed; they were "composed" from the same row twice before."""
        from btap.stock import fingerprint
        model = _built('bb-hwbb-gasboiler', 'bb-hwbb-gasboiler')
        comps = _zone(model)
        self.assertEqual(2, sum(1 for c in comps if c.role == 'unit'))
        result = fingerprint.explain(comps, _catalogue(*ROWS))
        self.assertEqual('match', result['outcome'], result)
        self.assertEqual(['bb-hwbb-gasboiler'], result['systems'])
        self.assertIn('unit:count=2:unit:ZoneHVAC_Baseboard_Convective_Water',
                      result['control_differences']['model_only'])

    def test_boiler_lift_is_a_different_system(self):
        """phylroy (2026-11-28): boiler lift is identity. Same equipment as a
        low-temperature heat-pump plant; the loop is held above the heat
        pump's own setpoint, which the setpoint managers state."""
        from btap.stock import fingerprint
        low = _zone(_built('bb-hwbb-awhp-gasbu'))
        lift = _zone(_built('bb-hwbb-awhp-gasbu-lift'))
        self.assertNotEqual(fingerprint.signature(low), fingerprint.signature(lift))
        self.assertTrue(any('plant:heating:boiler_lifts_above_heat_pump' in c.identity for c in lift))
        self.assertFalse(any('plant:heating:boiler_lifts_above_heat_pump' in c.identity for c in low))

    def test_a_cold_climate_heat_pump_is_identified_by_its_performance(self):
        """#257: ENERGY STAR Cold Climate (COP >= 1.75 and capacity >= 70% at
        5 F) is identity, read from the coil's own curves. No catalogue row
        meets it today (the `ccashp` rows keep 53%), so a flat capacity curve
        stands in for a real cold-climate unit."""
        import openstudio

        from btap.stock import fingerprint

        def cold_climate(model):
            for coil in model.getCoilHeatingDXSingleSpeeds():
                flat = openstudio.model.CurveCubic(model)
                flat.setCoefficient1Constant(1.0)
                flat.setCoefficient2x(0.0)
                flat.setCoefficient3xPOW2(0.0)
                flat.setCoefficient4xPOW3(0.0)
                flat.setMinimumValueofx(-30.0)
                flat.setMaximumValueofx(30.0)
                coil.setTotalHeatingCapacityFunctionofTemperatureCurve(flat)
                coil.setMinimumOutdoorDryBulbTemperatureforCompressorOperation(-18.0)
            # the PTHP unit carries its own lockout (default -8 C, IDD minimum
            # -20 C), and the stricter of the two governs
            for unit in model.getZoneHVACPackagedTerminalHeatPumps():
                assert unit.setMinimumOutdoorDryBulbTemperatureforCompressorOperation(-18.0)

        plain = _zone(_built('pthp'))
        cold = _zone(_built('pthp', mutate=cold_climate))
        token = 'unit:Coil_Heating_DX:cold_climate[ENERGY STAR]'
        self.assertFalse(any(token in c.identity for c in plain))
        self.assertTrue(any(token in c.identity for c in cold))
        self.assertNotEqual(fingerprint.signature(plain), fingerprint.signature(cold))
        # ...and the reported facts say why, with NEEP alongside
        self.assertTrue(any('NEEP ccASHP v4.0 not met' in x for c in cold for x in c.controls),
                        'one speed: not variable capacity, whatever the curve')

    def test_outdoor_air_is_read_from_each_operating_rule(self):
        """Each way a loop runs on 100% outdoor air, and the one that is not:
        equal FIXED flows below the supply are fixed outdoor air (Fable, final
        review: 0.2 of 1.0 m3/s was read as 100%)."""
        import openstudio

        def oa(model):
            loop = model.getAirLoopHVACs()[0]
            return loop, loop.airLoopHVACOutdoorAirSystem().get().getControllerOutdoorAir()

        def fixed_partial(model):
            loop, c = oa(model)
            loop.setDesignSupplyAirFlowRate(1.0)
            c.setMinimumOutdoorAirFlowRate(0.2)
            c.setMaximumOutdoorAirFlowRate(0.2)

        def fixed_full(model):
            loop, c = oa(model)
            loop.setDesignSupplyAirFlowRate(0.5)
            c.setMinimumOutdoorAirFlowRate(0.5)
            c.setMaximumOutdoorAirFlowRate(0.5)

        def fraction_always(model):
            _, c = oa(model)
            always = openstudio.model.ScheduleConstant(model)
            always.setValue(1.0)
            c.setMinimumFractionofOutdoorAirSchedule(always)

        def has_all_oa(model):
            return any('ahu:all_outdoor_air' in c.identity for c in _zone(model))
        row = 'psz-gas-perzone'
        self.assertFalse(has_all_oa(_built(row)), 'mixed air as built')
        self.assertFalse(has_all_oa(_built(row, zones=1, mutate=fixed_partial)), 'fixed outdoor air')
        self.assertTrue(has_all_oa(_built(row, zones=1, mutate=fixed_full)), 'fixed flows == supply')
        self.assertTrue(has_all_oa(_built(row, zones=1, mutate=fraction_always)), 'fraction 1 every hour')

    def test_cold_climate_arithmetic(self):
        """Each half of ENERGY STAR Cold Climate, the EIR normalisation and
        the compressor lockout decide it on their own (Fable, final review:
        the COP threshold, the normalisation and the capacity RATIO could all
        be removed with the suite green)."""
        import openstudio

        def cubic(model, a, b=0.0):
            curve = openstudio.model.CurveCubic(model)
            curve.setCoefficient1Constant(a)
            curve.setCoefficient2x(b)
            curve.setCoefficient3xPOW2(0.0)
            curve.setCoefficient4xPOW3(0.0)
            curve.setMinimumValueofx(-30.0)
            curve.setMaximumValueofx(30.0)
            return curve

        def coil_with(cap=(1.0, 0.0), eir=(1.0, 0.0), cop=5.0, lockout=-18.0, unit_lockout=-18.0):
            def mutate(model):
                for coil in model.getCoilHeatingDXSingleSpeeds():
                    coil.setTotalHeatingCapacityFunctionofTemperatureCurve(cubic(model, *cap))
                    coil.setEnergyInputRatioFunctionofTemperatureCurve(cubic(model, *eir))
                    coil.setRatedCOP(cop)
                    coil.setMinimumOutdoorDryBulbTemperatureforCompressorOperation(lockout)
                for unit in model.getZoneHVACPackagedTerminalHeatPumps():
                    unit.setMinimumOutdoorDryBulbTemperatureforCompressorOperation(unit_lockout)
            return mutate

        def line(at_47, at_5):
            """A linear curve through (8.33 C, at_47) and (-15 C, at_5)."""
            slope = (at_47 - at_5) / (8.33 + 15.0)
            return (at_47 - slope * 8.33, slope)

        token = 'unit:Coil_Heating_DX:cold_climate[ENERGY STAR]'

        def cold(**kw):
            return any(token in c.identity for c in _zone(_built('pthp', zones=1, mutate=coil_with(**kw))))
        self.assertTrue(cold(), 'flat capacity, COP 5')
        self.assertFalse(cold(cop=1.5), 'COP below 1.75')
        # COP at 5 F is what EnergyPlus computes, rated / EIR-f(5 F), with no
        # renormalisation at 47 F. Each case is decided by that alone: the
        # first fails if the curve is ignored, the second if it is
        # renormalised (Fable, re-review: a constant EIR could not tell).
        self.assertFalse(cold(eir=line(1.0, 2.0), cop=3.0), 'COP 3 / 2 = 1.5')
        self.assertTrue(cold(eir=line(0.5, 1.0), cop=3.0), 'COP 3 / 1 = 3, not 3 * 0.5 / 1')
        # capacity 1.5 at 47 F and 0.9 at 5 F: a 60% RATIO, though 0.9 >= 0.7
        self.assertFalse(cold(cap=(1.5 - 0.6 * 8.33 / 23.33, 0.6 / 23.33)), 'capacity ratio 60%')
        self.assertFalse(cold(lockout=-5.0), 'compressor locked out above 5 F')
        self.assertFalse(cold(unit_lockout=-5.0), "the PTHP unit's own lockout counts too")
        locked = _zone(_built('pthp', zones=1, mutate=coil_with(lockout=-5.0)))
        self.assertTrue(any('compressor locked out below -5 C' in x for c in locked for x in c.controls),
                        'a lockout is reported as one, not as a COP of zero')

    def test_boiler_lift_is_read_from_any_schedule_or_named(self):
        """Fable, final review: a boiler-lift plant on ruleset-scheduled
        setpoints silently matched the LOW-TEMPERATURE row. Ruleset schedules
        are now read; a manager that cannot be read is named in a note."""
        import openstudio

        def ruleset(model, value):
            schedule = openstudio.model.ScheduleRuleset(model)
            schedule.defaultDaySchedule().addValue(openstudio.Time(0, 24, 0, 0), value)
            return schedule

        def reauthor(follow=False):
            def mutate(model):
                for loop in model.getPlantLoops():
                    for node in loop.supplyComponents(openstudio.model.Node.iddObjectType()):
                        node = node.to_Node().get()
                        for spm in node.setpointManagers():
                            reset = spm.to_SetpointManagerOutdoorAirReset()
                            scheduled = spm.to_SetpointManagerScheduled()
                            if reset.is_initialized():
                                r = reset.get()
                                top = max(r.setpointatOutdoorLowTemperature(),
                                          r.setpointatOutdoorHighTemperature())
                            elif scheduled.is_initialized():
                                top = scheduled.get().schedule().to_ScheduleConstant().get().value()
                            else:
                                continue
                            spm.remove()
                            if follow and node == loop.supplyOutletNode():
                                openstudio.model.SetpointManagerFollowOutdoorAirTemperature(
                                    model).addToNode(node)
                            else:
                                openstudio.model.SetpointManagerScheduled(
                                    model, ruleset(model, top)).addToNode(node)
            return mutate

        token = 'plant:heating:boiler_lifts_above_heat_pump'
        lift = _zone(_built('bb-hwbb-awhp-gasbu-lift', zones=1, mutate=reauthor()))
        self.assertTrue(any(token in c.identity for c in lift), 'ruleset setpoints are read')
        unread = _zone(_built('bb-hwbb-awhp-gasbu-lift', zones=1, mutate=reauthor(follow=True)))
        self.assertFalse(any(token in c.identity for c in unread))
        self.assertTrue(any('boiler lift not determined' in n
                            and 'SetpointManager_FollowOutdoorAirTemperature' in n
                            for c in unread for n in c.notes), 'the unread manager is NAMED')
        # ...and explain names BOTH rows it cannot tell apart, not one
        from btap.stock import fingerprint
        catalogue = {r: _zone(_built(r)) for r in ('bb-hwbb-awhp-gasbu', 'bb-hwbb-awhp-gasbu-lift')}
        result = fingerprint.explain(unread, catalogue)
        self.assertEqual('match', result['outcome'], result)
        self.assertEqual(['bb-hwbb-awhp-gasbu', 'bb-hwbb-awhp-gasbu-lift'], result['systems'])
        self.assertEqual([token], result['undetermined'])

    def test_collapse_keeps_every_duplicate_and_rows_collapse_too(self):
        from btap.stock.fingerprint import Component, collapse, explain

        def comp(token, control=None):
            c = Component('unit')
            c.identity = {token}
            if control:
                c.controls = {control}
            return c
        merged = collapse([comp('unit:a', 'fan:OnOff'), comp('unit:a', 'fan:Constant')])
        self.assertEqual(1, len(merged))
        self.assertTrue({'fan:OnOff', 'fan:Constant', 'unit:count=2:unit:a'} <= merged[0].controls)
        # a row with two identical units covers a zone with two (Fable: it
        # could not, while rows were left uncollapsed)
        result = explain([comp('unit:a'), comp('unit:a'), comp('unit:b')],
                         {'aa': [comp('unit:a'), comp('unit:a')], 'b': [comp('unit:b')]})
        self.assertEqual('composed', result['outcome'], result)

    def test_equal_covers_are_reported_not_left_to_catalogue_order(self):
        from btap.stock.fingerprint import Component, explain

        def comp(token):
            c = Component('unit')
            c.identity = {token}
            return c
        rows = {'ab': ['a', 'b'], 'c': ['c'], 'a': ['a'], 'bc': ['b', 'c']}
        answers = []
        for order in (list(rows), list(reversed(rows))):
            catalogue = {k: [comp(t) for t in rows[k]] for k in order}
            answers.append(explain([comp('a'), comp('b'), comp('c')], catalogue))
        self.assertEqual(answers[0]['systems'], answers[1]['systems'])
        self.assertEqual(1, len(answers[0]['alternatives']), answers[0])

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
