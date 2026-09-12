"""D-89 — the reference boiler and furnace part-load curves.

Two halves, deliberately separated:

* the DATA half is SDK-free and re-derives every published number from the
  edition's own ``part_load_fheatplc`` block. Nothing here trusts a figure the
  snapshot states about itself: ``max_error_vs_exact`` is recomputed from the
  published points and the published coefficients and compared to what the file
  claims, so a hand-edited error figure fails HERE.
* the MODEL half exercises the applier and the loader: the electric boiler's
  reset (quantified, because no frozen scenario has an electric reference
  boiler), the propagated-class read, an unrepresentable class, and the DF-4
  probe that a foreign model object sharing a curve's name is not adopted.
"""

from __future__ import annotations

import json
import pathlib
import unittest

DATA_DIR = (pathlib.Path(__file__).resolve().parents[2]
            / 'btap' / 'codes' / 'necb' / 'data')
EDITIONS = ('necb2020', 'necb2025')
DATA = {edition: json.loads((DATA_DIR / edition / 'efficiencies.json')
                            .read_text(encoding='utf-8'))
        for edition in EDITIONS}

#: The enum a row or a propagated feature may name (D-89).
CLASSES = ('non_condensing', 'atmospheric', 'condensing',
           'modulating', 'not_applicable')

#: EnergyPlus floors a fuel heating coil's part-load fraction at 0.7 —
#: ``EnergyPlus::HeatingCoils::CalcFuelHeatingCoil`` (25.2.0, shipped with
#: OpenStudio 3.11.0): "PLF curve values must be >= 0.7. PLF has been reset to
#: 0.7 and the simulation continues...". The furnace grid starts at PLR 0.10
#: for that reason, and no furnace node may sit under the floor.
ENGINE_PLF_FLOOR = 0.7


def fheatplc(coefficients, plr):
    a, b, c = coefficients
    return a + b * plr + c * plr * plr


def exact_plf(coefficients, plr):
    """PLF = PLR / FHeatPLC(PLR) — the transform 8.4.5.2.(1)/8.4.6.2.(1) fixes:
    FHeatPLC scales the FUEL input, the EnergyPlus field is a degradation
    divisor, so the two are reciprocal about the part-load ratio (D-53)."""
    return plr / fheatplc(coefficients, plr)


def interpolate(points, x):
    """What a `Table:Lookup` with Linear interpolation and Constant
    extrapolation returns — the representation the curve declares."""
    if x <= points[0][0]:
        return points[0][1]
    if x >= points[-1][0]:
        return points[-1][1]
    for (x0, y0), (x1, y1) in zip(points, points[1:]):
        if x0 <= x <= x1:
            return y0 + (x - x0) * (y1 - y0) / (x1 - x0)
    raise AssertionError(f'{x} is inside the grid but between no two nodes')


def derive_max_error(points, coefficients):
    """Max RELATIVE error of the table's Linear interpolation against the exact
    rational, on a 0.0001 grid over the table's own span — finer than the
    finest node spacing (0.001), so no interval is sampled only at its nodes."""
    lo, hi = points[0][0], points[-1][0]
    worst = 0.0
    for i in range(round((hi - lo) / 0.0001) + 1):
        x = round(lo + i * 0.0001, 4)
        exact = exact_plf(coefficients, x)
        worst = max(worst, abs(interpolate(points, x) - exact) / abs(exact))
    return worst


def curves(edition):
    return {c['name']: c for c in DATA[edition]['curves']}


def fheatplc_entry(edition, equipment, klass):
    return next((e for e in DATA[edition]['part_load_fheatplc']
                 if e['equipment'] == equipment and e['class'] == klass), None)


class TestPartLoadData(unittest.TestCase):
    """SDK-free: the edition's own published requirement, and what ships."""

    def test_every_boiler_and_furnace_row_declares_a_class_in_the_enum(self):
        for edition in EDITIONS:
            for family in ('boilers', 'furnaces'):
                for row in DATA[edition][family]:
                    where = f'{edition}/{family}/{row.get("fuel_type")}'
                    self.assertIn(row.get('part_load_curve_class'), CLASSES, where)
                    for gone in ('efffplr', 'condensing', 'condensing_control'):
                        self.assertNotIn(gone, row,
                                         f'{where}: {gone!r} was never populated and '
                                         'no longer names the part-load curve (D-89)')

    def test_the_electric_boiler_row_is_not_applicable(self):
        """8.4.5.2./8.4.6.2. derive the part-load FUEL consumption of a
        fuel-fired boiler. An electric boiler has no fuel input to adjust."""
        for edition in EDITIONS:
            electric = [r for r in DATA[edition]['boilers']
                        if r['fuel_type'] == 'Electric']
            self.assertTrue(electric, edition)
            for row in electric:
                self.assertEqual('not_applicable', row['part_load_curve_class'], edition)
            for row in DATA[edition]['boilers']:
                if row['fuel_type'] != 'Electric':
                    self.assertEqual('non_condensing', row['part_load_curve_class'],
                                     edition)

    def test_every_reachable_class_maps_to_a_curve_row_that_ships(self):
        for edition in EDITIONS:
            catalogue = curves(edition)
            mapped = DATA[edition]['part_load_curves']
            for entry in DATA[edition]['part_load_fheatplc']:
                where = f'{edition}/{entry["equipment"]}/{entry["class"]}'
                classes = (mapped.get(entry['equipment']) or {}).get('classes') or {}
                if entry['reachable']:
                    self.assertIn(entry['class'], classes,
                                  f'{where}: a reachable class must be in the map')
                    name = classes[entry['class']]
                    self.assertIn(name, catalogue, f'{where}: {name!r} is not shipped')
                    self.assertEqual('TableLookup', catalogue[name]['form'], where)
                else:
                    self.assertNotIn(entry['class'], classes,
                                     f'{where}: an unreachable class must not be '
                                     'mapped to a curve')
                    self.assertTrue(entry.get('deferred_reason'),
                                    f'{where}: an unreachable class must say why')

    def test_every_class_a_row_declares_is_in_the_map(self):
        for edition in EDITIONS:
            mapped = DATA[edition]['part_load_curves']
            for family, equipment in (('boilers', 'boiler'), ('furnaces', 'furnace')):
                classes = (mapped.get(equipment) or {}).get('classes') or {}
                for row in DATA[edition][family]:
                    self.assertIn(row['part_load_curve_class'], classes,
                                  f'{edition}/{family}: a class a row can SELECT must '
                                  'have an entry in the map, or the applier would only '
                                  'ever warn')

    def test_each_lookup_reproduces_plf_from_the_edition_s_own_coefficients(self):
        for edition in EDITIONS:
            for curve in DATA[edition]['curves']:
                if curve['form'] != 'TableLookup':
                    continue
                implements = curve['implements']
                entry = fheatplc_entry(edition, implements['equipment'],
                                       implements['class'])
                self.assertIsNotNone(entry, f'{edition}/{curve["name"]}')
                where = f'{edition}/{curve["name"]}'
                self.assertEqual(entry['table'], implements['table'], where)
                if entry['form'] == 'points':
                    wanted = {plr: plr / value for plr, value in entry['points']}
                else:
                    wanted = {plr: exact_plf(entry['coefficients'], plr)
                              for plr, _plf in curve['points']}
                self.assertEqual(len(wanted), len(curve['points']), where)
                for plr, plf in curve['points']:
                    self.assertAlmostEqual(wanted[plr], plf, places=6,
                                           msg=f'{where} at PLR {plr}')

    def test_the_published_interpolation_error_is_re_derived_not_trusted(self):
        for edition in EDITIONS:
            for curve in DATA[edition]['curves']:
                if curve['form'] != 'TableLookup':
                    continue
                implements = curve['implements']
                entry = fheatplc_entry(edition, implements['equipment'],
                                       implements['class'])
                where = f'{edition}/{curve["name"]}'
                published = implements['max_error_vs_exact']
                if entry['form'] == 'points':
                    # The Code publishes only the ten points and no rule between
                    # them, so there is no exact function to measure against.
                    self.assertEqual(0.0, published, where)
                    continue
                derived = derive_max_error([tuple(p) for p in curve['points']],
                                           entry['coefficients'])
                self.assertAlmostEqual(derived, published, places=9,
                                       msg=f'{where}: published '
                                           f'{published}, re-derived {derived}')

    def test_the_published_errors_are_the_expected_magnitudes(self):
        """Pinned so a regenerated grid cannot quietly get coarser."""
        expected = {
            ('necb2020', 'BOILER-PLF-NONCONDENSING'): 0.001991326,
            ('necb2025', 'BOILER-PLF-NONCONDENSING'): 0.001991326,
            ('necb2020', 'FURNACE-PLF-ATMOSPHERIC'): 0.000268619,
            ('necb2025', 'FURNACE-PLF-ATMOSPHERIC'): 0.000268619,
            ('necb2020', 'BOILER-PLF-MODULATING-necb2020'): 0.0,
            ('necb2025', 'BOILER-PLF-MODULATING-necb2025'): 0.007898575,
        }
        for (edition, name), value in expected.items():
            self.assertAlmostEqual(
                value, curves(edition)[name]['implements']['max_error_vs_exact'],
                places=9, msg=f'{edition}/{name}')

    def test_the_grids_and_the_representation_are_what_d_89_declares(self):
        for edition in EDITIONS:
            for name, curve in curves(edition).items():
                if curve['form'] != 'TableLookup':
                    continue
                where = f'{edition}/{name}'
                self.assertEqual('Linear', curve['interpolation'], where)
                self.assertEqual('Constant', curve['extrapolation'], where)
                self.assertEqual('PLR', curve['independent_variable_1'], where)
                points = curve['points']
                self.assertEqual(sorted(points), points, f'{where}: nodes ascend')
                self.assertEqual(points[0][0], curve['minimum_independent_variable_1'],
                                 where)
                self.assertEqual(points[-1][0], curve['maximum_independent_variable_1'],
                                 where)
                self.assertEqual(1.0, points[-1][0], f'{where}: the grid reaches PLR 1')
                if name.startswith('BOILER-PLF-MODULATING-necb2020'):
                    self.assertEqual(10, len(points), where)
                elif name.startswith('FURNACE-'):
                    self.assertEqual(0.10, points[0][0],
                                     f'{where}: the furnace grid starts at 0.10')
                    self.assertEqual(91, len(points), where)
                else:
                    # Boiler quadratic classes: the grid starts at the engine's
                    # aligned minimum part-load ratio (0.001) and is finest
                    # where the rational is most convex (Sol's R-O review P2).
                    self.assertEqual(0.001, points[0][0], where)
                    self.assertEqual(150, len(points), where)
                    xs = [x for x, _ in points]
                    self.assertEqual([round(0.001 * i, 3) for i in range(1, 50)],
                                     xs[:49], f'{where}: 0.001 steps below 0.05')
                    for node in (0.05, 0.055, 0.1):
                        self.assertIn(node, xs, f'{where}: node {node}')

    def test_no_furnace_node_sits_under_the_engine_s_plf_floor(self):
        """The 0.10 grid start is not a preference: EnergyPlus resets a fuel
        heating coil's PLF to 0.7 below that, so nodes under the floor would
        only feed the engine values it rejects."""
        for edition in EDITIONS:
            curve = curves(edition)['FURNACE-PLF-ATMOSPHERIC']
            for plr, plf in curve['points']:
                self.assertGreaterEqual(plf, ENGINE_PLF_FLOOR,
                                        f'{edition} at PLR {plr}')
            entry = fheatplc_entry(edition, 'furnace', 'atmospheric')
            # and the rational really does cross the floor just below the grid
            self.assertLess(exact_plf(entry['coefficients'], 0.05), ENGINE_PLF_FLOOR)
            self.assertGreater(exact_plf(entry['coefficients'], 0.10), ENGINE_PLF_FLOOR)

    def test_the_two_editions_modulating_curves_differ_and_the_rest_agree(self):
        """D-88 as amended: a source-neutral name is only honest while the two
        editions state the same numbers under it."""
        for shared in ('BOILER-PLF-NONCONDENSING', 'FURNACE-PLF-ATMOSPHERIC'):
            self.assertEqual(curves('necb2020')[shared]['points'],
                             curves('necb2025')[shared]['points'],
                             f'{shared} keeps a neutral name, so its points must be '
                             'identical in both snapshots')
        modulating_2020 = curves('necb2020')['BOILER-PLF-MODULATING-necb2020']
        modulating_2025 = curves('necb2025')['BOILER-PLF-MODULATING-necb2025']
        self.assertNotEqual(modulating_2020['points'], modulating_2025['points'],
                            'the modulating content differs, which is exactly why '
                            'these two names are code-qualified')
        self.assertNotIn('BOILER-PLF-MODULATING-necb2025', curves('necb2020'))
        self.assertNotIn('BOILER-PLF-MODULATING-necb2020', curves('necb2025'))

    def test_the_2011_cubics_and_the_heat_rejection_block_are_gone(self):
        for edition in EDITIONS:
            names = set(curves(edition))
            for retired in ('BOILER-EFFFPLR', 'BOILER-EFFFPLR-COND',
                            'FURNACE-EFFPLR', 'FURNACE-EFFPLR-COND'):
                self.assertNotIn(retired, names, edition)
            self.assertNotIn('heat_rejection', DATA[edition], edition)

    def test_every_published_class_names_its_archived_payload(self):
        for edition in EDITIONS:
            for entry in DATA[edition]['part_load_fheatplc']:
                where = f'{edition}/{entry["equipment"]}/{entry["class"]}'
                payload = DATA_DIR / edition / entry['archived_payload']
                self.assertTrue(payload.is_file(), f'{where}: {payload}')
                archived = json.loads(payload.read_text(encoding='utf-8'))
                table = next(iter(archived.values()))
                self.assertEqual(entry['table'], table['table_number'], where)


# ---------------------------------------------------------------- model half

try:  # the SDK half is skipped wholesale where OpenStudio is unavailable
    import openstudio
except ImportError:  # pragma: no cover
    openstudio = None

if openstudio is not None:
    from btap.audit import AuditLog
    from btap.codes.necb.hvac import efficiency


def boiler_model(fuel='NaturalGas', capacity_w=100_000.0):
    model = openstudio.model.Model()
    boiler = openstudio.model.BoilerHotWater(model)
    boiler.setName('Primary Boiler')
    boiler.setFuelType(fuel)
    boiler.setNominalCapacity(capacity_w)
    return model, boiler


def apply_boiler(boiler, edition='necb2020', audit=None):
    audit = audit if audit is not None else AuditLog()
    tables = efficiency.data(edition.removeprefix('necb'))
    plant = {'two_boiler_max_kw': 352.0, 'single_boiler_max_kw': 176.0,
             'modulating_min_fraction': 0.25}
    efficiency._apply_boiler(boiler, tables, plant, audit)
    return audit


@unittest.skipIf(openstudio is None, 'OpenStudio SDK unavailable')
class TestElectricBoilerHasNoPartLoadCurve(unittest.TestCase):
    """Contract item 4. No frozen scenario has an electric reference boiler, so
    the effect is quantified HERE or nowhere."""

    #: The retired NECB 2011 cubic BOILER-EFFFPLR, which every boiler row —
    #: the electric one included — used to be given.
    LEGACY_CUBIC = (0.3831, 2.0567, -2.6469, 1.2148)

    def test_a_sized_electric_boiler_ends_with_no_curve_even_if_one_was_attached(self):
        model, boiler = boiler_model(fuel='Electricity')
        pre_attached = openstudio.model.CurveCubic(model)
        pre_attached.setName('carried in from the proposed')
        boiler.setNormalizedBoilerEfficiencyCurve(pre_attached)
        self.assertTrue(boiler.normalizedBoilerEfficiencyCurve().is_initialized())

        audit = apply_boiler(boiler)

        self.assertFalse(boiler.normalizedBoilerEfficiencyCurve().is_initialized(),
                         'an electric boiler has no fuel input for FHeatPLC to '
                         'adjust, and the reset must also clear a curve the '
                         'proposed model contributed to this clone')
        entry = next(e for e in audit.entries if e['action'] == 'boiler efficiency applied')
        self.assertEqual('not_applicable', entry['inputs']['part_load_curve_class'])
        self.assertEqual('row', entry['inputs']['class_source'])
        self.assertEqual('D-89', entry['ruling'])
        self.assertEqual([], audit.warnings)

    def test_the_corrected_multiplier_is_quantified_against_the_legacy_cubic(self):
        model, boiler = boiler_model(fuel='Electricity')
        apply_boiler(boiler)
        self.assertFalse(boiler.normalizedBoilerEfficiencyCurve().is_initialized())

        a, b, c, d = self.LEGACY_CUBIC
        expected = {0.10: 0.5635, 0.25: 0.7508, 0.50: 0.9016, 1.00: 1.0077}
        print('\nelectric reference boiler, normalized efficiency multiplier:')
        for plr, legacy in sorted(expected.items()):
            was = a + b * plr + c * plr ** 2 + d * plr ** 3
            self.assertAlmostEqual(legacy, was, places=4,
                                   msg=f'the legacy cubic at PLR {plr}')
            print(f'  PLR {plr:.2f}: legacy BOILER-EFFFPLR {was:.4f} -> corrected 1.0000 '
                  f'({(1.0 / was - 1) * 100:+.1f} % efficiency)')
        # the whole point: at 10 % load the legacy curve derated an ELECTRIC
        # boiler's efficiency by 43.6 %, which no article asks for
        self.assertAlmostEqual(0.4365, 1.0 - expected[0.10], places=4)


@unittest.skipIf(openstudio is None, 'OpenStudio SDK unavailable')
class TestPartLoadClassResolution(unittest.TestCase):

    def test_the_row_s_class_selects_the_non_condensing_curve(self):
        model, boiler = boiler_model()
        audit = apply_boiler(boiler)
        applied = boiler.normalizedBoilerEfficiencyCurve()
        self.assertTrue(applied.is_initialized())
        self.assertEqual('BOILER-PLF-NONCONDENSING', applied.get().nameString())
        self.assertTrue(applied.get().to_TableLookup().is_initialized(),
                        'the representation D-89 chose is a Table:Lookup')
        entry = next(e for e in audit.entries if e['action'] == 'boiler efficiency applied')
        self.assertEqual('non_condensing', entry['inputs']['part_load_curve_class'])
        self.assertEqual('row', entry['inputs']['class_source'])
        self.assertEqual('TableLookup', entry['inputs']['form'])
        self.assertIn('8.4.5.2.', entry['article'])
        self.assertIn('5.2.12.1', entry['article'])
        self.assertIn('PLF = PLR / FHeatPLC(PLR)', entry['evidence'])
        self.assertIn('EnteringBoiler', entry['evidence'])
        self.assertEqual('EnteringBoiler',
                         boiler.efficiencyCurveTemperatureEvaluationVariable().get())

    def test_a_propagated_class_wins_over_the_row_s_default(self):
        """The interface with the reference-selection side: a class stamped on
        the object survives the SECOND efficiency pass, which the row cannot."""
        for edition, expected in (('necb2020', 'BOILER-PLF-MODULATING-necb2020'),
                                  ('necb2025', 'BOILER-PLF-MODULATING-necb2025')):
            model, boiler = boiler_model()
            boiler.additionalProperties().setFeature(
                efficiency.PART_LOAD_CLASS_FEATURE, 'modulating')
            audit = apply_boiler(boiler, edition=edition)
            applied = boiler.normalizedBoilerEfficiencyCurve()
            self.assertTrue(applied.is_initialized(), edition)
            self.assertEqual(expected, applied.get().nameString(), edition)
            entry = next(e for e in audit.entries
                         if e['action'] == 'boiler efficiency applied')
            self.assertEqual('modulating', entry['inputs']['part_load_curve_class'])
            self.assertEqual('reference selection', entry['inputs']['class_source'])
            self.assertEqual([], audit.warnings, edition)

    def test_an_unrepresentable_class_warns_and_leaves_the_factor_constant(self):
        """Never a silent fall back to the non-condensing curve."""
        model, boiler = boiler_model()
        pre_attached = openstudio.model.CurveCubic(model)
        boiler.setNormalizedBoilerEfficiencyCurve(pre_attached)
        boiler.additionalProperties().setFeature(
            efficiency.PART_LOAD_CLASS_FEATURE, 'condensing')

        audit = apply_boiler(boiler)

        self.assertFalse(boiler.normalizedBoilerEfficiencyCurve().is_initialized())
        warning = next(w for w in audit.warnings
                       if 'has no representation' in w['action'])
        self.assertIn("'condensing'", warning['action'])
        self.assertIn('NECB 2020', warning['action'])
        self.assertEqual('D-89', warning['ruling'])
        entry = next(e for e in audit.entries if e['action'] == 'boiler efficiency applied')
        self.assertEqual('condensing', entry['inputs']['part_load_curve_class'])
        self.assertIn('unrepresentable', entry['inputs']['curve'])


@unittest.skipIf(openstudio is None, 'OpenStudio SDK unavailable')
class TestCurveLoaderValidatesBeforeReuse(unittest.TestCase):
    """DF-4. Before D-89 `curve()` adopted any model object matching by name."""

    def _shipped(self, edition='necb2020', name='BOILER-PLF-NONCONDENSING'):
        tables = efficiency.data(edition.removeprefix('necb'))
        return tables, next(c for c in tables['curves'] if c['name'] == name)

    def _build(self, model, row, name, mutate=None):
        points = [list(p) for p in row['points']]
        if mutate is not None:
            mutate(points)
        independent = openstudio.model.TableIndependentVariable(model)
        independent.setInterpolationMethod(row['interpolation'])
        independent.setExtrapolationMethod(row['extrapolation'])
        independent.setUnitType('Dimensionless')
        independent.setValues([x for x, _y in points])
        independent.setMinimumValue(row['minimum_independent_variable_1'])
        independent.setMaximumValue(row['maximum_independent_variable_1'])
        table = openstudio.model.TableLookup(model)
        table.addIndependentVariable(independent)
        table.setNormalizationMethod('None')
        table.setOutputUnitType('Dimensionless')
        table.setOutputValues([y for _x, y in points])
        table.setMinimumOutput(row['minimum_dependent_variable_output'])
        table.setMaximumOutput(row['maximum_dependent_variable_output'])
        table.setName(name)
        return table

    def test_a_foreign_object_with_a_wrong_point_is_not_reused(self):
        model = openstudio.model.Model()
        tables, row = self._shipped()
        foreign = self._build(model, row, 'BOILER-PLF-NONCONDENSING',
                              mutate=lambda pts: pts[50].__setitem__(1, 0.5))
        audit = AuditLog()

        built = efficiency.curve(model, tables, 'BOILER-PLF-NONCONDENSING',
                                 audit=audit, target='probe')

        self.assertIsNot(built, foreign)
        self.assertEqual('BOILER-PLF-NONCONDENSING (D-89)', built.nameString())
        self.assertEqual([y for _x, y in row['points']],
                         [round(v, 6) for v in built.outputValues()])
        warning = next(w for w in audit.warnings if 'NOT adopted' in w['action'])
        self.assertIn('BOILER-PLF-NONCONDENSING', warning['action'])
        self.assertEqual('BOILER-PLF-NONCONDENSING (D-89)',
                         warning['inputs']['applied'])

    def test_a_matching_object_is_reused(self):
        model = openstudio.model.Model()
        tables, row = self._shipped()
        existing = self._build(model, row, 'BOILER-PLF-NONCONDENSING')
        audit = AuditLog()

        built = efficiency.curve(model, tables, 'BOILER-PLF-NONCONDENSING',
                                 audit=audit, target='probe')

        self.assertEqual(existing.handle(), built.handle())
        self.assertEqual([], audit.warnings)

    def test_a_second_pass_reuses_the_ruleset_s_own_object(self):
        """The disambiguated object must not multiply: the efficiency pass runs
        twice on the reference, and each pass must land on the same curve."""
        model = openstudio.model.Model()
        tables, row = self._shipped()
        self._build(model, row, 'BOILER-PLF-NONCONDENSING',
                    mutate=lambda pts: pts[50].__setitem__(1, 0.5))

        audit = AuditLog()
        first = efficiency.curve(model, tables, 'BOILER-PLF-NONCONDENSING',
                                 audit=audit, target='probe')
        second = efficiency.curve(model, tables, 'BOILER-PLF-NONCONDENSING',
                                  audit=audit, target='probe 2')

        self.assertEqual(first.handle(), second.handle())
        self.assertEqual(1, len([c for c in model.getCurves()
                                 if c.nameString().endswith('(D-89)')]))
        # The foreign object is reported ONCE per model, when the ruleset's
        # own curve is built — not again for every component that reuses it
        # (a reference with five DX coils would otherwise carry 40 copies).
        self.assertEqual(1, len([w for w in audit.warnings
                                 if 'NOT adopted' in w['action']]))

    def test_an_object_of_another_curve_type_never_matches(self):
        """A Quadratic spec must not be smuggled through as a cubic with a zero
        term — the SHW loader's rule, applied here."""
        model = openstudio.model.Model()
        tables, row = self._shipped()
        impostor = openstudio.model.CurveCubic(model)
        impostor.setName('BOILER-PLF-NONCONDENSING')
        audit = AuditLog()

        built = efficiency.curve(model, tables, 'BOILER-PLF-NONCONDENSING',
                                 audit=audit, target='probe')

        self.assertTrue(built.to_TableLookup().is_initialized())
        self.assertEqual('BOILER-PLF-NONCONDENSING (D-89)', built.nameString())
        self.assertTrue(audit.warnings)

    def test_an_unknown_form_warns_rather_than_returning_a_silent_none(self):
        model = openstudio.model.Model()
        tables, _row = self._shipped()
        tables = dict(tables)
        tables['curves'] = list(tables['curves']) + [
            {'name': 'INVENTED-FORM', 'form': 'Sinusoidal'}]
        audit = AuditLog()

        self.assertIsNone(efficiency.curve(model, tables, 'INVENTED-FORM',
                                           audit=audit, target='probe'))
        warning = next(w for w in audit.warnings if 'INVENTED-FORM' in w['action'])
        self.assertIn('Sinusoidal', warning['action'])

    def test_a_name_outside_the_catalogue_warns(self):
        model = openstudio.model.Model()
        tables, _row = self._shipped()
        audit = AuditLog()

        self.assertIsNone(efficiency.curve(model, tables, 'NOT-IN-THE-CATALOGUE',
                                           audit=audit, target='probe'))
        self.assertTrue(any('NOT-IN-THE-CATALOGUE' in w['action']
                            for w in audit.warnings))


if __name__ == '__main__':
    unittest.main()


@unittest.skipIf(openstudio is None, 'OpenStudio SDK unavailable')
class TestTheTableCoversEveryPermittedInput(unittest.TestCase):
    """Sol's R-O review, P2: the published error only bounds the engine's
    behaviour if every part-load ratio the engine can evaluate is covered.
    Most boilers keep the SDK's minimum part-load ratio of 0, so the engine
    may evaluate any PLR in (0, 1]. The table covers [0.001, 1] by nodes and
    (0, 0.001) by its declared Constant extrapolation; the under-count there is
    bounded by the Code's own standby term, and that bound is published.

    The engine minimum is deliberately NOT raised to close the domain:
    EnergyPlus forces the delivered heat up to MinPLR x capacity under locked
    flow (Boilers.cc, CalcBoilerModel), which changes the load, not the curve."""

    def test_the_applier_leaves_the_engine_minimum_alone(self):
        model, boiler = boiler_model()
        apply_boiler(boiler)
        self.assertEqual(0.0, boiler.minimumPartLoadRatio())
        model, boiler = boiler_model(capacity_w=400_000.0)
        apply_boiler(boiler)
        self.assertEqual(0.25, boiler.minimumPartLoadRatio(),
                         "8.4.4.9.(6)(d)'s staged-primary floor is the only "
                         "minimum the pass sets")

    def test_the_under_count_below_the_first_node_is_bounded_by_the_standby_term(self):
        """fuel_exact(p) - fuel_table(p), as a fraction of the design fuel
        Fuel_design = Q_design / eta, for every p below the first node: the
        exact rational charges Fuel_design x FHeatPLC(p) while the table, held
        at PLF(p0), charges Fuel_design x p / PLF(p0). The gap is at most
        FHeatPLC(0) = a, and the test derives it rather than trusting the text."""
        for edition in EDITIONS:
            for curve in curves(edition).values():
                implements = curve.get('implements') or {}
                if curve['form'] != 'TableLookup' or implements.get('equipment') != 'boiler':
                    continue
                entry = fheatplc_entry(edition, 'boiler', implements['class'])
                if entry['form'] != 'quadratic':
                    continue
                a = entry['coefficients'][0]
                p0, plf0 = curve['points'][0]
                self.assertEqual('Constant', curve['extrapolation'])
                worst = 0.0
                for i in range(1, 1000):
                    p = p0 * i / 1000
                    # FHeatPLC(p) = p / PLF_exact(p): the Code's fuel as a
                    # fraction of Fuel_design; the table's is p / PLF(p0).
                    fuel_exact = p / exact_plf(entry['coefficients'], p)
                    fuel_table = p / plf0
                    worst = max(worst, fuel_exact - fuel_table)
                self.assertLessEqual(worst, a + 1e-12, f'{edition}/{curve["name"]}')
                self.assertGreater(worst, 0.9 * a, 'the bound is tight as p -> 0')
                self.assertIn(f'{a} x Fuel_design', implements['error_grid'],
                              f'{edition}/{curve["name"]}: the bound is published')
