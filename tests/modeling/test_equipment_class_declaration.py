"""The serialized equipment-class declaration (`equipment_class`).

Some code requirements turn on what equipment IS, and a model's topology often
cannot say: a bare `Coil:Cooling:DX*` on a constant-volume loop describes a
certified packaged unit and a field-erected built-up system equally well.

Two wrong answers were tried first, and the tests here are shaped by both. The
air loop's NAME made the answer depend on who authored the file; the zone count
(`packaged_single_zone`) was arithmetic rather than evidence. A declaration is
neither: it is written into the OSM by whoever knows, and read identically by
anyone — including a tool that never saw this catalogue.
"""

import tempfile
import unittest
from pathlib import Path

import openstudio

from btap.modeling import build_system
from btap.modeling.hvac import classify, equipment_class
from tests.necb.hvac_helpers import load_fixture, sorted_zones


class TestTheDeclarationItself(unittest.TestCase):
    def setUp(self):
        self.model = openstudio.model.Model()
        self.loop = openstudio.model.AirLoopHVAC(self.model)
        self.loop.setName('Probe Loop')

    def test_declare_then_read_round_trips(self):
        equipment_class.declare(self.loop, 'air_cooled_unitary')
        self.assertEqual('air_cooled_unitary', equipment_class.read(self.loop))

    def test_an_undeclared_loop_reads_as_None(self):
        self.assertIsNone(equipment_class.read(self.loop))

    def test_a_value_outside_the_convention_is_REFUSED(self):
        """A typo must not read as "no declaration" and fall back to inference
        silently — that is the failure this guard exists for."""
        with self.assertRaises(ValueError) as caught:
            equipment_class.declare(self.loop, 'air-cooled-unitary')
        self.assertIn('falls back to inference', str(caught.exception))

    def test_an_UNKNOWN_value_already_in_a_model_reads_as_None(self):
        """Not symmetric with the writer, deliberately. A model from another
        tool may use a vocabulary we do not know, and the honest response is to
        treat the class as undeclared rather than refuse the model."""
        self.loop.additionalProperties().setFeature(
            equipment_class.FEATURE, 'something_we_do_not_know')
        self.assertIsNone(equipment_class.read(self.loop))

    def test_it_SURVIVES_an_OSM_round_trip(self):
        """The declaration has to reach whoever reads the file next, which is
        the entire point of putting it in the model rather than in a lookup."""
        equipment_class.declare(self.loop, 'fan_coil')
        with tempfile.TemporaryDirectory(prefix='equip-class-') as tmp:
            path = Path(tmp, 'probe.osm')
            self.model.save(openstudio.path(str(path)), True)
            reloaded = openstudio.model.Model.load(
                openstudio.path(str(path))).get()
        loop = reloaded.getAirLoopHVACByName('Probe Loop').get()
        self.assertEqual('fan_coil', equipment_class.read(loop))

    def test_it_FORWARD_TRANSLATES_to_nothing(self):
        """Declaring must not change a single simulation result. This is what
        makes the declaration cheap enough to add to shipped builders at all —
        the alternative considered was restructuring PSZ into a unitary
        container, which would have moved every PSZ model's control and sizing.
        """
        equipment_class.declare(self.loop, 'air_cooled_unitary')
        workspace = openstudio.energyplus.ForwardTranslator().translateModel(
            self.model)
        names = {obj.iddObject().name() for obj in workspace.objects()}
        self.assertFalse(
            any('AdditionalProperties' in name for name in names),
            'an AdditionalProperties feature must not reach the IDF')


class TestTheClassifierReadsIt(unittest.TestCase):
    def _group(self, model):
        groups = classify.characterize(model, audit=None)['zone_groups']
        return next(g for g in groups if g.get('air_loop') is not None)

    def test_a_declaring_builder_puts_the_fact_in_the_facts(self):
        """`psz` means packaged single zone, so the row names real equipment."""
        model = load_fixture()
        build_system(model, 'PSZ RTU Gas and DX Coils and Hot Water Baseboard',
                     sorted_zones(model))
        group = self._group(model)
        self.assertEqual('air_cooled_unitary',
                         group['declared_equipment_class'])
        self.assertTrue(
            any('declares equipment_class' in e for e in group['evidence']),
            'the evidence trail names the declaration as its basis')

    def test_a_builder_with_nothing_to_declare_leaves_it_None(self):
        """The divergent control, and the honest case: our `furnace` family
        builds a generic air handler, and whether a given Campus unit is
        packaged is a fact about those buildings that nobody established."""
        model = load_fixture()
        build_system(model, 'Shared furnace with DX cooling and no outdoor air',
                     sorted_zones(model))
        self.assertIsNone(self._group(model)['declared_equipment_class'])

    def test_a_ROW_may_declare_where_its_builder_cannot(self):
        """`furnace` serves both cases above, so the declaration is per ROW.
        `Residential AC with baseboard electric` is a residential central split
        AC — Table 5.2.12.1.-A's split-system air-cooled unitary."""
        model = load_fixture()
        build_system(model, 'Residential AC with baseboard electric',
                     sorted_zones(model))
        groups = classify.characterize(model, audit=None)['zone_groups']
        declared = {g.get('declared_equipment_class') for g in groups
                    if g.get('air_loop') is not None}
        self.assertEqual({'air_cooled_unitary'}, declared)


class TestThePszDeclarationFollowsItsHeatSource(unittest.TestCase):
    """#154: the eight reference-ASHP rows build a heat pump, so they say so.

    No NECB result differs today — topology establishes the heat pump and
    Article 8.4.4.13's redirect precedes any identity use — which is why this
    needs its own test: reverting the conditional changed nothing any other
    test could see.
    """

    @staticmethod
    def _declared(name):
        model = load_fixture()
        build_system(model, name, sorted_zones(model))
        return {equipment_class.read(loop)
                for loop in model.getAirLoopHVACs()}

    def test_every_reference_ASHP_row_declares_heat_pump(self):
        from btap.modeling.hvac import catalog

        rows = [r['name'] for r in catalog.rows()
                if r.get('family') == 'psz' and r.get('heat_source') == 'ashp']
        self.assertEqual(8, len(rows), 'precondition: the eight ASHP rows')
        for name in rows:
            with self.subTest(row=name):
                self.assertEqual({'heat_pump'}, self._declared(name))

    def test_an_ordinary_psz_row_still_declares_air_cooled_unitary(self):
        """The control: the conditional must not have flipped every row."""
        from btap.modeling.hvac import catalog

        rows = [r['name'] for r in catalog.rows()
                if r.get('family') == 'psz' and not r.get('heat_source')]
        self.assertTrue(rows)
        for name in rows[:3]:
            with self.subTest(row=name):
                self.assertEqual({'air_cooled_unitary'}, self._declared(name))


if __name__ == '__main__':
    unittest.main()


class TestAnUnrecognizedDeclarationIsNotSilent(unittest.TestCase):
    """"No declaration" and "a declaration we cannot read" are different.

    `read` cannot raise on an unknown value — the convention is open, and a
    vocabulary from another tool is not grounds to refuse a model. But treating
    the two cases identically sends whoever wrote the feature back to retype
    the value they already typed: the run refuses for the same reason, with the
    same message, and nothing says a declaration was even seen.

    Fable found this while checking whether README's instructions could be
    followed verbatim (PR #161). The README had promised that a typo "cannot
    read as nothing declared", which was true of `declare()` and false of the
    raw `setFeature` call the README itself showed.
    """

    @staticmethod
    def _characterize(value):
        from btap.audit import AuditLog

        model = load_fixture()
        build_system(model, 'Shared furnace with DX cooling and no outdoor air',
                     sorted_zones(model))
        if value is not None:
            for loop in model.getAirLoopHVACs():
                loop.additionalProperties().setFeature(
                    equipment_class.FEATURE, value)
        audit = AuditLog()
        facts = classify.characterize(model, audit=audit)
        warnings = [w for w in audit.warnings
                    if 'equipment_class' in str(w.get('action'))]
        group = next(g for g in facts['zone_groups']
                     if g.get('air_loop') is not None)
        return group, warnings

    def test_an_unrecognized_value_WARNS_and_names_what_is_accepted(self):
        group, warnings = self._characterize('air_cooled_unitry')

        self.assertIsNone(group['declared_equipment_class'],
                          'it still reads as no declaration — the model is not '
                          'refused over a vocabulary we do not know')
        self.assertEqual(1, len(warnings))
        self.assertIn('air_cooled_unitry', str(warnings[0]['action']),
                      'the warning quotes the value, so the author sees their '
                      'own typo rather than guessing')
        self.assertIn('air_cooled_unitary',
                      warnings[0]['inputs']['accepted'],
                      'and lists what it would have accepted')

    def test_a_RECOGNIZED_value_warns_about_nothing(self):
        group, warnings = self._characterize('air_cooled_unitary')
        self.assertEqual('air_cooled_unitary',
                         group['declared_equipment_class'])
        self.assertEqual([], warnings)

    def test_NO_declaration_warns_about_nothing_either(self):
        """The divergent control. Without this, a warning on every undeclared
        loop would look identical to a warning on a typo — and most loops
        carry no declaration at all, so that would be noise on nearly
        every run."""
        group, warnings = self._characterize(None)
        self.assertIsNone(group['declared_equipment_class'])
        self.assertEqual([], warnings)

    def test_read_raw_tells_the_two_cases_apart(self):
        import openstudio

        model = openstudio.model.Model()
        loop = openstudio.model.AirLoopHVAC(model)
        self.assertIsNone(equipment_class.read_raw(loop))

        loop.additionalProperties().setFeature(
            equipment_class.FEATURE, 'something_else')
        self.assertEqual('something_else', equipment_class.read_raw(loop))
        self.assertIsNone(equipment_class.read(loop),
                          'read() still refuses to guess')
