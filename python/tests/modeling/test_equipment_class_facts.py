"""Equipment-IDENTITY facts an ARBITRARY OSM carries, and what the NECB
residential branch does with them.

`btap.modeling.hvac.classify` records two facts that nothing downstream can
reconstruct, because `coils.supply_components` is lossy BY DESIGN: it replaces
an `AirLoopHVACUnitarySystem` with the coils inside it so a staged reference
system's coils are findable at all. A real packaged rooftop unit and a
field-erected built-up DX coil then both read as `loop_dx_cooling`.

That matters for the feature that takes ANY osm and derives a reference
building from it. A model this library authored is recognized by its loop NAME,
so it keeps its family whatever the structure says; a model from a design firm
has only its structure, and the standard OpenStudio representation of a
packaged rooftop unit is exactly the container the flattener unwraps.

Every fixture here is built from BARE OpenStudio objects rather than a catalog
row, because the arbitrary-OSM case is the point. No catalog row sets
`staged_coils` — only the NECB selectors do — so a catalog-built model can
never witness the container at all.
"""

import unittest

import openstudio

from btap.codes.necb.hvac.reference import (
    _residential_compatible_cooling,
    _residential_cooling_route,
)
from btap.modeling import build_system
from btap.modeling.hvac import classify
from tests.necb.hvac_helpers import load_fixture, sorted_zones


def _loop_with_zone(model, name):
    """An air loop serving one zone, with no coils and no terminal yet."""
    loop = openstudio.model.AirLoopHVAC(model)
    loop.setName(name)
    zone = openstudio.model.ThermalZone(model)
    zone.setName(f'{name} Zone')
    space = openstudio.model.Space(model)
    space.setThermalZone(zone)
    return loop, zone


def _dx_coil(model):
    return openstudio.model.CoilCoolingDXSingleSpeed(model)


class TestPackagedUnitaryFact(unittest.TestCase):
    """`packaged_unitary` is positive evidence of factory-packaged equipment."""

    def _characterize(self, model):
        groups = classify.characterize(model, audit=None)['zone_groups']
        return next(g for g in groups if g.get('air_loop') is not None)

    def test_a_unitary_container_on_the_supply_path_is_recorded(self):
        """The container the flattener unwraps is seen BEFORE it is unwrapped."""
        model = openstudio.model.Model()
        loop, zone = _loop_with_zone(model, 'Packaged RTU')
        always_on = model.alwaysOnDiscreteSchedule()
        unitary = openstudio.model.AirLoopHVACUnitarySystem(model)
        unitary.setCoolingCoil(_dx_coil(model))
        unitary.setControllingZoneorThermostatLocation(zone)
        unitary.addToNode(loop.supplyOutletNode())
        term = openstudio.model.AirTerminalSingleDuctConstantVolumeNoReheat(
            model, always_on)
        loop.addBranchForZone(zone, term.to_HVACComponent().get())

        group = self._characterize(model)
        self.assertTrue(group['packaged_unitary'],
                        'an AirLoopHVACUnitarySystem is packaged equipment')
        self.assertTrue(group['loop_dx_cooling'],
                        'and the flattener still finds the coil inside it')
        self.assertTrue(
            any('packaged equipment' in e for e in group['evidence']),
            'the fact states its own basis in the evidence trail')

    def test_a_BARE_dx_coil_is_NOT_packaged_evidence(self):
        """The divergent case: identical cooling, no equipment-identity fact.

        This is the built-up DX air handler. It must NOT claim the packaged
        fact, or the fact means nothing — every DX loop would carry it.
        """
        model = openstudio.model.Model()
        loop, zone = _loop_with_zone(model, 'Built-up AHU')
        always_on = model.alwaysOnDiscreteSchedule()
        _dx_coil(model).addToNode(loop.supplyOutletNode())
        term = openstudio.model.AirTerminalSingleDuctConstantVolumeNoReheat(
            model, always_on)
        loop.addBranchForZone(zone, term.to_HVACComponent().get())

        group = self._characterize(model)
        self.assertTrue(group['loop_dx_cooling'], 'the DX coil is still found')
        self.assertFalse(group['packaged_unitary'],
                         'but nothing says it is packaged equipment')


class TestVentilationSizedFact(unittest.TestCase):
    """`ventilation_sized` separates make-up-air tempering from zone cooling."""

    def _group(self, model):
        groups = classify.characterize(model, audit=None)['zone_groups']
        return next(g for g in groups if g.get('air_loop') is not None)

    def test_a_loop_sized_on_the_ventilation_requirement_is_recorded(self):
        model = openstudio.model.Model()
        loop, zone = _loop_with_zone(model, 'Make-up Air Unit')
        always_on = model.alwaysOnDiscreteSchedule()
        _dx_coil(model).addToNode(loop.supplyOutletNode())
        term = openstudio.model.AirTerminalSingleDuctConstantVolumeNoReheat(
            model, always_on)
        loop.addBranchForZone(zone, term.to_HVACComponent().get())
        loop.sizingSystem().setTypeofLoadtoSizeOn('VentilationRequirement')

        group = self._group(model)
        self.assertTrue(group['ventilation_sized'])
        self.assertTrue(any('temper make-up air' in e for e in group['evidence']))

    def test_a_loop_sized_on_SENSIBLE_load_is_zone_cooling(self):
        model = openstudio.model.Model()
        loop, zone = _loop_with_zone(model, 'Zone Cooling AHU')
        always_on = model.alwaysOnDiscreteSchedule()
        _dx_coil(model).addToNode(loop.supplyOutletNode())
        term = openstudio.model.AirTerminalSingleDuctConstantVolumeNoReheat(
            model, always_on)
        loop.addBranchForZone(zone, term.to_HVACComponent().get())
        loop.sizingSystem().setTypeofLoadtoSizeOn('Sensible')

        group = self._group(model)
        self.assertFalse(group['ventilation_sized'])


class TestResidentialBranchReadsTheFacts(unittest.TestCase):
    """Table 8.4.4.7.-A's identity branch, at the predicate that decides it.

    Each case names which clause is the ONLY route to its answer, so a mutation
    of that clause has nowhere else to pass through.
    """

    def test_packaged_unitary_is_the_ONLY_route_when_the_terminal_is_VAV(self):
        """The divergent fixture for the positive clause.

        The bare-DX fallback requires a `none`/`cv` terminal. A VAV terminal
        fails it, so a True here can only come from the packaged fact — which
        is what makes this fixture, rather than a CV one, the witness.
        """
        group = {'air_loop': 'RTU', 'loop_dx_cooling': True,
                 'terminal_type': 'vav', 'packaged_unitary': True,
                 'ventilation_sized': False, 'zonal_units': [],
                 'family': 'unknown', 'family_guess': 'central_doas_or_cv'}
        self.assertTrue(_residential_compatible_cooling(group))

        bare = dict(group, packaged_unitary=False)
        self.assertFalse(
            _residential_compatible_cooling(bare),
            'without the packaged fact a VAV DX loop has no qualifying route')

    def test_a_VENTILATION_sized_loop_is_refused_even_with_bare_DX(self):
        """The exclusion. Its DX tempers make-up air, so Table -A's "cooled
        with" branch is not reached through it."""
        group = {'air_loop': 'MAU', 'loop_dx_cooling': True,
                 'terminal_type': 'cv', 'packaged_unitary': False,
                 'ventilation_sized': True, 'zonal_units': [],
                 'family': 'doas', 'family_guess': 'central_doas_or_cv'}
        self.assertFalse(_residential_compatible_cooling(group))

        zone_cooling = dict(group, ventilation_sized=False)
        self.assertTrue(
            _residential_compatible_cooling(zone_cooling),
            'the SAME loop sized on sensible load does qualify — the exclusion '
            'is the only difference between these two cases')

    def test_CODE_LISTED_zonal_equipment_outranks_the_exclusion(self):
        """A DOAS-plus-fan-coil composite is ventilation-sized AND qualifies.

        Table -A lists fan coils by name, so the zonal equipment satisfies the
        branch whatever the ventilation loop is doing. This pins the clause
        ORDER: hoisting the ventilation check above the zonal test turns every
        DOAS composite into through-the-wall.
        """
        for unit in ('fan_coil', 'wshp', 'vrf_terminal'):
            with self.subTest(unit=unit):
                group = {'air_loop': 'DOAS', 'loop_dx_cooling': True,
                         'terminal_type': 'cv', 'packaged_unitary': False,
                         'ventilation_sized': True, 'zonal_units': [unit],
                         'family': 'doas', 'family_guess': 'central_doas_or_cv'}
                self.assertTrue(_residential_compatible_cooling(group))


if __name__ == '__main__':
    unittest.main()


class TestTheOneZoneDefect(unittest.TestCase):
    """The defect Fable found in the first version, and the fixture that sees it.

    `_structural_family_guess` calls ANY single-zone no-reheat air loop
    `packaged_single_zone`. That guess was positive evidence ahead of the
    ventilation exclusion, so a one-zone ventilation-only block still qualified
    for Table -A's identity branch and was labelled `observed` with no warning.
    Every other fixture here and the whole selection matrix use FIVE zones, so
    nothing could distinguish zone count from equipment class — which is the
    thing D-108 says must not narrow the term.
    """

    def _group(self, n_zones):
        model = load_fixture()
        build_system(model, 'DOAS ventilation only',
                     sorted_zones(model)[:n_zones])
        groups = classify.characterize(model, audit=None)['zone_groups']
        return next(g for g in groups if g.get('air_loop') is not None)

    def test_a_ONE_zone_ventilation_loop_is_refused_like_any_other(self):
        """Zone count must not change the answer. The one-zone case is the
        witness; the five-zone case is the control that was already passing."""
        one = self._group(1)
        self.assertEqual('packaged_single_zone', one['family_guess'],
                         'precondition: the structural guess still says this, '
                         'so the fix cannot be an accident of the guess changing')
        self.assertTrue(one['ventilation_sized'])
        self.assertFalse(
            _residential_compatible_cooling(one),
            'a one-zone ventilation-only loop is still a ventilation system')

        for n in (2, 5):
            with self.subTest(zones=n):
                self.assertFalse(_residential_compatible_cooling(self._group(n)))

    def test_packaged_single_zone_is_not_positive_evidence_anywhere(self):
        """It is derived from zone count and terminal type, so it cannot
        establish an equipment class. Such a loop may still qualify through the
        bare-DX inference — the point is that it is labelled as inferred."""
        group = {'air_loop': 'RTU', 'loop_dx_cooling': True,
                 'terminal_type': 'cv', 'packaged_unitary': False,
                 'ventilation_sized': False, 'zonal_units': [],
                 'family': 'unknown', 'family_guess': 'packaged_single_zone'}
        self.assertTrue(_residential_compatible_cooling(group),
                        'it still qualifies, through the inference')

        no_dx = dict(group, loop_dx_cooling=False)
        self.assertFalse(
            _residential_compatible_cooling(no_dx),
            'but with the DX coil gone it has nothing left — which proves the '
            'guess itself was not what qualified it')


class TestVentilationSizedNeedsAllThreeFields(unittest.TestCase):
    """Sol's `329`: the sizing TYPE alone does not prove make-up-air tempering."""

    def _group(self, *, load_type, all_oa):
        model = openstudio.model.Model()
        loop, zone = _loop_with_zone(model, 'Sized Loop')
        always_on = model.alwaysOnDiscreteSchedule()
        _dx_coil(model).addToNode(loop.supplyOutletNode())
        term = openstudio.model.AirTerminalSingleDuctConstantVolumeNoReheat(
            model, always_on)
        loop.addBranchForZone(zone, term.to_HVACComponent().get())
        sizing = loop.sizingSystem()
        sizing.setTypeofLoadtoSizeOn(load_type)
        sizing.setAllOutdoorAirinCooling(all_oa)
        sizing.setAllOutdoorAirinHeating(all_oa)
        groups = classify.characterize(model, audit=None)['zone_groups']
        return next(g for g in groups if g.get('air_loop') is not None)

    def test_the_sizing_TYPE_alone_does_not_establish_it(self):
        """The divergent control. Same `VentilationRequirement`, outdoor-air
        flags false: a recirculating loop that happens to be sized on its
        ventilation requirement is not a make-up-air unit."""
        self.assertFalse(
            self._group(load_type='VentilationRequirement', all_oa=False)
            ['ventilation_sized'])

    def test_all_outdoor_air_alone_does_not_establish_it_either(self):
        self.assertFalse(
            self._group(load_type='Sensible', all_oa=True)['ventilation_sized'])

    def test_the_CONJUNCTION_establishes_it(self):
        group = self._group(load_type='VentilationRequirement', all_oa=True)
        self.assertTrue(group['ventilation_sized'])
        self.assertTrue(any('all outdoor air' in e for e in group['evidence']),
                        'the evidence states what was actually observed')


class TestTheAuditDistinguishesObservedFromInferred(unittest.TestCase):
    """The call site, not the predicate.

    `_residential_compatible_cooling` returns a bool and says nothing about
    WHY. The distinction an AHJ reader needs is made at the selector, and until
    this test existed nothing asserted it: the source set
    `equipment_class`, a warning and `ahj='AHJ-23'`, and no test searched for
    any of them (Sol, `329`; Fable, PR #153 review).
    """

    @staticmethod
    def _select(group_overrides):
        from btap.audit import AuditLog
        from btap.codes.necb import hvac

        group = {'zones': ['Z1'], 'air_loop': 'L1', 'family': None,
                 'catalog_name': None, 'family_guess': None,
                 'heated': True, 'cooled': True,
                 'heating_energy_types': ['NaturalGas'],
                 'cooling_energy_types': ['Electricity'],
                 'heat_pump': False, 'heat_pump_sources': [],
                 'terminal_type': 'cv', 'design_cooling_kw': 10.0,
                 'zonal_units': [], 'loop_dx_cooling': True,
                 'packaged_unitary': False, 'ventilation_sized': False,
                 'evidence': []}
        group.update(group_overrides)
        facts = {'built_by_gem': False, 'zone_groups': [group], 'plants': [],
                 'purchased_energy': {'heating': False, 'cooling': False}}
        audit = AuditLog()
        assignments = list(hvac.select_reference_systems(
            facts=facts, building={'storeys': 1, 'zone_types': {'Z1': 'Hotel/Motel'}},
            code='necb2020', audit=audit))
        return assignments, audit

    def test_a_BARE_DX_loop_is_labelled_inferred_warned_and_cited(self):
        assignments, audit = self._select({})
        self.assertEqual(['copy_proposed'], [str(a.action) for a in assignments],
                         'precondition: this is the route under test')

        decisions = [e for e in audit.entries
                     if e.get('inputs', {}).get('equipment_class')]
        self.assertTrue(decisions, 'the selector records the equipment class')
        self.assertEqual('inferred from bare DX',
                         decisions[0]['inputs']['equipment_class'])
        self.assertIn('D-108', str(decisions[0].get('ruling')))
        self.assertEqual('AHJ-23', decisions[0].get('ahj'))

        warnings = [w for w in audit.warnings if 'INFERENCE' in str(w.get('action'))]
        self.assertEqual(1, len(warnings),
                         'exactly one warning, naming the inference')
        self.assertEqual('AHJ-23', warnings[0].get('ahj'))

    def test_OBSERVED_equipment_carries_no_inference_warning_and_no_AHJ(self):
        """The divergent control. Same copy_proposed outcome, different basis:
        a warning on this route would cry wolf on an established fact."""
        for observed in ({'packaged_unitary': True},
                         {'zonal_units': ['fan_coil']},
                         {'declared_equipment_class': 'air_cooled_unitary'}):
            with self.subTest(observed=sorted(observed)):
                assignments, audit = self._select(observed)
                self.assertEqual(['copy_proposed'],
                                 [str(a.action) for a in assignments])

                decisions = [e for e in audit.entries
                             if e.get('inputs', {}).get('equipment_class')]
                self.assertEqual('observed',
                                 decisions[0]['inputs']['equipment_class'])
                self.assertIsNone(decisions[0].get('ahj'),
                                  'an observed fact needs no register entry')
                self.assertEqual(
                    [], [w for w in audit.warnings
                         if 'INFERENCE' in str(w.get('action'))])


class TestTheANSWERDoesNotDependOnWHOAUTHOREDTheModel(unittest.TestCase):
    """Sol's `331`: the determination must not turn on a catalogue name.

    `classify._recognize_gem_name` resolves an air loop's name against this
    repository's catalogue and writes `family`. While that family was positive
    equipment evidence, two OSMs with IDENTICAL topology got different answers
    — a loop still carrying a BTAP name was "observed" and got an ordinary
    verdict, the same loop with its name scrubbed was "inferred" and exited 6.

    The 108-row selection matrix cannot see this: it records the shared
    `copy_proposed` action, not the route or the determination. So the witness
    is here, and it is the SAME MODEL twice with one name changed.
    """

    def _route_and_family(self, scrub):
        model = load_fixture()
        build_system(model, 'Shared furnace with DX cooling and no outdoor air',
                     sorted_zones(model))
        if scrub:
            for i, loop in enumerate(model.getAirLoopHVACs()):
                loop.setName(f'Air System {i + 1}')
        groups = classify.characterize(model, audit=None)['zone_groups']
        group = next(g for g in groups if g.get('cooled'))
        return _residential_cooling_route(group), group.get('family')

    def test_scrubbing_the_loop_name_changes_NOTHING(self):
        named_route, named_family = self._route_and_family(scrub=False)
        scrubbed_route, scrubbed_family = self._route_and_family(scrub=True)

        self.assertEqual('furnace', named_family,
                         'precondition: the name DOES still resolve to a '
                         'family, so this fixture can tell the two apart')
        self.assertIsNone(scrubbed_family,
                          'precondition: scrubbing really does remove it')
        self.assertEqual(
            named_route, scrubbed_route,
            'the same topology must get the same answer whoever authored it')

    def test_a_DECLARED_class_survives_scrubbing_because_it_is_in_the_model(self):
        """The contrast that makes the point. A declaration is not a name: it
        is written into the OSM, so renaming the loop cannot remove it."""
        model = load_fixture()
        build_system(model, 'PSZ RTU Gas and DX Coils and Hot Water Baseboard',
                     sorted_zones(model))
        for i, loop in enumerate(model.getAirLoopHVACs()):
            loop.setName(f'Air System {i + 1}')
        groups = classify.characterize(model, audit=None)['zone_groups']
        group = next(g for g in groups if g.get('cooled'))

        self.assertIsNone(group.get('family'), 'the name is gone')
        self.assertEqual('air_cooled_unitary',
                         group.get('declared_equipment_class'),
                         'the FACT is not')
        self.assertEqual('declared', _residential_cooling_route(group))


class TestTheBRANCHNeedsHeatedANDCooled(unittest.TestCase):
    """Table -A's printed condition is "heated AS WELL AS being cooled with".

    BOTH. The implementation tested only `cooled` for a while, so a
    COOLING-ONLY block carrying listed equipment took the copy where the text
    sends it to `otherwise` (Sol, `331`). Dropping the conjunction again
    survived every other test in this file, because every other fixture here
    is heated — which is exactly why this one is not.
    """

    @staticmethod
    def _group(**overrides):
        group = {'zones': ['Z1'], 'air_loop': 'L1', 'family': None,
                 'catalog_name': None, 'family_guess': None,
                 'heated': True, 'cooled': True,
                 'heating_energy_types': ['NaturalGas'],
                 'cooling_energy_types': ['Electricity'],
                 'heat_pump': False, 'heat_pump_sources': [],
                 'terminal_type': 'cv', 'design_cooling_kw': 10.0,
                 'zonal_units': ['fan_coil'], 'loop_dx_cooling': False,
                 'packaged_unitary': False, 'ventilation_sized': False,
                 'declared_equipment_class': None, 'evidence': []}
        group.update(overrides)
        return group

    def _assign(self, group):
        from btap.audit import AuditLog
        from btap.codes.necb import hvac

        facts = {'built_by_gem': False, 'zone_groups': [group], 'plants': [],
                 'purchased_energy': {'heating': False, 'cooling': False}}
        return [str(a.action) for a in hvac.select_reference_systems(
            facts=facts, building={'storeys': 1,
                                   'zone_types': {'Z1': 'Hotel/Motel'}},
            code='necb2020', audit=AuditLog())]

    def test_COOLING_ONLY_with_listed_equipment_is_NOT_copied(self):
        """Fan coils are named in Table -A, and that is not enough on its own:
        an unheated block never satisfies "heated as well as"."""
        self.assertEqual(
            ['through_the_wall'],
            self._assign(self._group(heated=False)),
            'a cooling-only block reaches `otherwise` however its cooling is '
            'equipped')

    def test_the_SAME_block_heated_IS_copied(self):
        """The control. One field apart from the case above, so the only thing
        that can explain the difference is the thermal-mode prerequisite."""
        self.assertEqual(['copy_proposed'],
                         self._assign(self._group(heated=True)))

    def test_heated_only_still_takes_System_1(self):
        """The third branch, unchanged — included so a mutation that refuses
        everything cannot pass by making both cases above agree."""
        self.assertEqual(
            ['build'],
            self._assign(self._group(cooled=False, zonal_units=[],
                                     cooling_energy_types=[])))


class TestADeclarationIsPositiveInBOTHDirections(unittest.TestCase):
    """A declared class the Code does not list is EVIDENCE, not silence.

    `built_up` and `evaporative` are deliberately absent from
    `DECLARED_COMPATIBLE_CLASSES`, so declaring either sends the block to
    `otherwise` instead of to the bare-DX inference: the model answered the
    question and the answer was no. Treating any declaration as compatible
    survived every other test here, because no other fixture declares a
    non-listed class.
    """

    @staticmethod
    def _group(declared):
        return {'air_loop': 'L1', 'loop_dx_cooling': True,
                'terminal_type': 'cv', 'packaged_unitary': False,
                'ventilation_sized': False, 'zonal_units': [],
                'family': None, 'family_guess': None,
                'declared_equipment_class': declared}

    def test_a_NON_listed_declaration_refuses_the_branch(self):
        for declared in ('evaporative', 'built_up'):
            with self.subTest(declared=declared):
                self.assertIsNone(
                    _residential_cooling_route(self._group(declared)),
                    f'{declared} is not one of Table -A\'s identities, and the '
                    f'model SAID so — it must not fall through to the '
                    f'inference either')

    def test_a_LISTED_declaration_qualifies(self):
        for declared in ('air_cooled_unitary', 'packaged_terminal',
                         'room_air_conditioner', 'heat_pump', 'fan_coil'):
            with self.subTest(declared=declared):
                self.assertEqual(
                    'declared',
                    _residential_cooling_route(self._group(declared)))

    def test_an_UNDECLARED_loop_with_the_same_topology_is_INFERRED(self):
        """The divergence that matters: identical DX topology, no declaration.
        This is what makes the two cases above about the DECLARATION rather
        than about the coil."""
        self.assertEqual('inferred',
                         _residential_cooling_route(self._group(None)))


class TestADeclaredHeatPumpStillTakesTheArticle13Redirect(unittest.TestCase):
    """A declaration cannot be evidence for one branch and invisible to another.

    `heat_pump` is in the declaration vocabulary and on
    `DECLARED_COMPATIBLE_CLASSES`, so it qualifies for Table 8.4.4.7.-A's
    identity branch. But `_heat_pump_redirects` read only the characterized
    BOOLEAN, so a declared-only heat pump skipped D-34's classification and
    reached the identity branch — returning `copy_proposed` where D-37 requires
    the conservative ASHP reference for a heat pump with no source evidence
    (Sol, `333`, exercised at `460faf6a`).

    These run the FULL SELECTOR rather than the route helper, because the defect
    was precedence: the route predicate answered correctly in isolation and the
    assignment was still wrong.
    """

    @staticmethod
    def _select(zone_types_override='Hotel/Motel', **overrides):
        from btap.audit import AuditLog
        from btap.codes.necb import hvac

        group = {'zones': ['Z1'], 'air_loop': 'L1', 'family': None,
                 'catalog_name': None, 'family_guess': None,
                 'heated': True, 'cooled': True,
                 'heating_energy_types': ['Electricity'],
                 'cooling_energy_types': ['Electricity'],
                 'heat_pump': False, 'heat_pump_sources': [],
                 'terminal_type': 'cv', 'design_cooling_kw': 10.0,
                 'zonal_units': [], 'loop_dx_cooling': False,
                 'packaged_unitary': False, 'ventilation_sized': False,
                 'declared_equipment_class': None, 'evidence': []}
        group.update(overrides)
        facts = {'built_by_gem': False, 'zone_groups': [group], 'plants': [],
                 'purchased_energy': {'heating': False, 'cooling': False}}
        audit = AuditLog()
        return list(hvac.select_reference_systems(
            facts=facts,
            building={'storeys': 1, 'zone_types': {'Z1': zone_types_override}},
            code='necb2020', audit=audit)), audit

    def test_a_declared_heat_pump_with_no_source_BUILDS_the_hp_reference(self):
        assignments, audit = self._select(declared_equipment_class='heat_pump')
        self.assertEqual(['build'], [str(a.action) for a in assignments])
        self.assertEqual(['hp'], [a.reference_system for a in assignments])
        self.assertNotIn(
            'copy_proposed', [str(a.action) for a in assignments],
            'the identity branch must not be reached past Article 13')
        self.assertTrue(
            any('D-34' in str(e.get('ruling')) for e in audit.entries),
            'the redirect records its own ruling')

    def test_a_declared_UNITARY_class_still_copies(self):
        """The control. Same shape, a class that is NOT a heat pump, so the
        identity branch is the right destination and nothing redirects."""
        assignments, _ = self._select(
            declared_equipment_class='air_cooled_unitary')
        self.assertEqual(['copy_proposed'],
                         [str(a.action) for a in assignments])

    def test_a_DETECTED_water_loop_heat_pump_keeps_its_Table_A_selection(self):
        """D-37's retention branch, unchanged: positive water-loop source
        evidence keeps the copy. This is what the fix must NOT break."""
        assignments, _ = self._select(
            heat_pump=True, heat_pump_sources=['water_loop'],
            zonal_units=['wshp'])
        self.assertEqual(['copy_proposed'],
                         [str(a.action) for a in assignments])

    def test_the_RETENTION_audit_also_honours_the_declaration(self):
        """`_finalize`'s water-loop retention, the second site Sol named.

        A declared heat pump with POSITIVE water-loop source evidence does not
        redirect (D-37 sentence (1)), and the audit records that retention with
        its own ruling. Reverting this site to the raw boolean survived every
        other test here, because the residential branch returns `copy_proposed`
        and `_finalize` returns early on that — so the retention audit is only
        reachable from a group whose assignment is BUILT. Hence an office
        group: the same declaration, a destination that reaches `_finalize`.
        """
        assignments, audit = self._select(
            declared_equipment_class='heat_pump',
            heat_pump_sources=['water_loop'],
            zone_types_override='Office - enclosed')

        self.assertEqual(['build'], [str(a.action) for a in assignments])
        self.assertNotEqual(['hp'], [a.reference_system for a in assignments],
                            'water-loop evidence means NO ASHP redirect')
        retained = [e for e in audit.entries
                    if 'retained' in str(e.get('action'))
                    and e.get('ruling') == 'D-37']
        self.assertEqual(
            1, len(retained),
            'the retention is recorded, which is what an AHJ reads; with the '
            'raw boolean this decision is simply absent')
