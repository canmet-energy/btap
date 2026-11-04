"""The recipe writer's envelope section (#196).

The three U-reading routes are the substance here: the first version of the
reader used only the third and dropped EVERY window on
`Office_pre-1960` — 30 of them, the whole fenestration section.
"""

from __future__ import annotations

import unittest

from btap._compat import opt
from btap.audit import AuditLog
from btap.stock import envelope_section
from btap.stock.envelope import ENVELOPE_BOUNDARIES
from tests.support import needs_sdk


def _square(z=0.0, size=4.0):
    import openstudio

    pts = openstudio.Point3dVector()
    for x, y in ((0, 0), (size, 0), (size, size), (0, size)):
        pts.append(openstudio.Point3d(x, y, z))
    return pts


def _wall(model, space, construction, width=4.0, height=3.0):
    import openstudio

    pts = openstudio.Point3dVector()
    for x, z in ((0, 0), (width, 0), (width, height), (0, height)):
        pts.append(openstudio.Point3d(x, 0.0, z))
    surface = openstudio.model.Surface(pts, model)
    surface.setSpace(space)
    surface.setSurfaceType('Wall')
    surface.setOutsideBoundaryCondition('Outdoors')
    surface.setConstruction(construction)
    return surface


def _opaque_construction(model, name, conductivity=0.05, thickness=0.1):
    import openstudio

    material = openstudio.model.StandardOpaqueMaterial(model)
    material.setName(f'{name} Material')
    material.setConductivity(conductivity)
    material.setThickness(thickness)
    construction = openstudio.model.Construction(model)
    construction.setName(name)
    construction.setLayers([material])
    return construction


@needs_sdk
class TestTheThreeUReadingRoutes(unittest.TestCase):
    """Each is a different SDK shape, and only measurement found them."""

    def test_an_opaque_construction_reads_through_the_CONSTRUCTION(self):
        import openstudio

        model = openstudio.model.Model()
        space = openstudio.model.Space(model)
        construction = _opaque_construction(model, 'Test Wall',
                                            conductivity=0.05, thickness=0.1)
        _wall(model, space, construction)

        section = envelope_section(model)
        entry = section['opaque']['Wall:Outdoors']
        # conductance 0.05/0.1 = 0.5; wall films add R, so U < 0.5.
        self.assertLess(entry['u_si'], 0.5)
        self.assertAlmostEqual(1.0 / entry['u_si'], entry['r_si'], places=2)
        self.assertEqual([], section['unreadable'])

    def test_SimpleGlazing_reads_its_uFactor_and_films_are_NOT_added(self):
        """A SimpleGlazing U-factor is already the OVERALL U — that is the
        definition of WindowMaterial:SimpleGlazingSystem's U-Factor field — so
        adding films would report a window better than it is."""
        import openstudio

        model = openstudio.model.Model()
        space = openstudio.model.Space(model)
        wall = _wall(model, space, _opaque_construction(model, 'Host Wall'))

        glazing = openstudio.model.SimpleGlazing(model)
        glazing.setUFactor(3.55)
        glazing.setSolarHeatGainCoefficient(0.6)
        glazing.setVisibleTransmittance(0.7)
        window_con = openstudio.model.Construction(model)
        window_con.setName('Simple Window')
        window_con.setLayers([glazing])

        pts = openstudio.Point3dVector()
        for x, z in ((1, 1), (3, 1), (3, 2), (1, 2)):
            pts.append(openstudio.Point3d(x, 0.0, z))
        sub = openstudio.model.SubSurface(pts, model)
        sub.setSurface(wall)
        sub.setSubSurfaceType('FixedWindow')
        sub.setConstruction(window_con)

        section = envelope_section(model)
        entry = section['fenestration']['FixedWindow:Outdoors']
        self.assertAlmostEqual(
            3.55, entry['u_si'], places=3,
            msg='the uFactor VERBATIM — no film resistance added to it')
        self.assertAlmostEqual(0.6, entry['shgc'])
        self.assertAlmostEqual(0.7, entry['visible_transmittance'])
        self.assertEqual([], section['unreadable'])

    def test_a_single_StandardGlazing_reads_the_MATERIAL_conductance(self):
        """The layered construction's `thermalConductance()` returns None for
        glazing, while a StandardGlazing MATERIAL has its own. Reading only
        the construction dropped 19 windows carrying
        `Customized Fenestration: cond=…` on the campus archetypes."""
        import openstudio

        model = openstudio.model.Model()
        space = openstudio.model.Space(model)
        wall = _wall(model, space, _opaque_construction(model, 'Host Wall 2'))

        glazing = openstudio.model.StandardGlazing(model)
        glazing.setThickness(0.003)
        glazing.setThermalConductivity(0.9)
        glazing.setSolarTransmittanceatNormalIncidence(0.5)
        glazing.setVisibleTransmittanceatNormalIncidence(0.21)
        window_con = openstudio.model.Construction(model)
        window_con.setName('Standard Window')
        window_con.setLayers([glazing])

        # Assert the premise rather than gesture at it: my first version of
        # this line was `assertIsNone(None if … else None)`, which is None
        # either way and asserted nothing.
        self.assertFalse(
            opt(window_con.to_LayeredConstruction()).thermalConductance()
            .is_initialized(),
            'the CONSTRUCTION-level conductance is the read that fails for '
            'glazing — which is why the material-level one is needed')

        pts = openstudio.Point3dVector()
        for x, z in ((1, 1), (3, 1), (3, 2), (1, 2)):
            pts.append(openstudio.Point3d(x, 0.0, z))
        sub = openstudio.model.SubSurface(pts, model)
        sub.setSurface(wall)
        sub.setSubSurfaceType('FixedWindow')
        sub.setConstruction(window_con)

        section = envelope_section(model)
        self.assertIn('FixedWindow:Outdoors', section['fenestration'],
                      'this is the window the first reader lost')
        entry = section['fenestration']['FixedWindow:Outdoors']
        # Material conductance 0.9/0.003 = 300 W/m2K, so U is film-dominated.
        self.assertGreater(entry['u_si'], 3.0)
        self.assertEqual([], section['unreadable'])


@needs_sdk
class TestAggregation(unittest.TestCase):

    def test_it_weights_U_by_AREA_not_R(self):
        """Heat flow is the sum of U*A*dT, so the effective U is
        sum(U*A)/sum(A). Averaging R overweights the well-insulated surfaces
        and reports an envelope better than the one that exists."""
        import openstudio

        model = openstudio.model.Model()
        space = openstudio.model.Space(model)
        # Two walls, equal area, conductance 0.5 and 2.0 -> films included.
        _wall(model, space, _opaque_construction(model, 'A', 0.05, 0.1))
        _wall(model, space, _opaque_construction(model, 'B', 0.2, 0.1))

        entry = envelope_section(model)['opaque']['Wall:Outdoors']
        us = (entry['from']['u_min'], entry['from']['u_max'])
        u_mean = sum(us) / 2.0
        r_mean_derived = 1.0 / (sum(1.0 / u for u in us) / 2.0)
        self.assertAlmostEqual(
            u_mean, entry['u_si'], places=3,
            msg='equal areas, so the U mean — not the R mean')
        self.assertNotAlmostEqual(
            r_mean_derived, entry['u_si'], places=3,
            msg='and the two are genuinely different numbers here')

    def test_r_is_DERIVED_so_the_pair_cannot_disagree(self):
        import openstudio

        model = openstudio.model.Model()
        space = openstudio.model.Space(model)
        _wall(model, space, _opaque_construction(model, 'C', 0.05, 0.1))
        entry = envelope_section(model)['opaque']['Wall:Outdoors']
        self.assertAlmostEqual(1.0 / entry['u_si'], entry['r_si'], places=3)

    def test_a_WIDE_spread_is_flagged_and_a_tight_one_is_not(self):
        import openstudio

        for label, (cond_a, cond_b), expect_warning in (
                ('tight', (0.05, 0.051), False),
                ('wide', (0.05, 0.4), True)):
            with self.subTest(label):
                model = openstudio.model.Model()
                space = openstudio.model.Space(model)
                _wall(model, space,
                      _opaque_construction(model, f'{label} A', cond_a, 0.1))
                _wall(model, space,
                      _opaque_construction(model, f'{label} B', cond_b, 0.1))
                entry = envelope_section(model)['opaque']['Wall:Outdoors']
                has = 'spread_warning' in entry['from']
                self.assertEqual(
                    expect_warning, has,
                    f"{label}: spread {entry['from']['u_spread_ratio']}x")

    def test_the_provenance_is_recorded(self):
        import openstudio

        model = openstudio.model.Model()
        space = openstudio.model.Space(model)
        for n in range(3):
            _wall(model, space, _opaque_construction(model, f'P{n}'))
        entry = envelope_section(model)['opaque']['Wall:Outdoors']
        self.assertEqual(3, entry['from']['surfaces'])
        self.assertAlmostEqual(36.0, entry['from']['area_m2'], places=1)


@needs_sdk
class TestWhatItExcludesAndRefuses(unittest.TestCase):

    def test_INTERIOR_surfaces_are_excluded(self):
        """The pre-1960 Hangar has 310 interior walls against 76 exterior
        ones, so including them would dominate the average and describe
        nothing."""
        import openstudio

        model = openstudio.model.Model()
        space = openstudio.model.Space(model)
        exterior = _wall(model, space, _opaque_construction(model, 'Ext'))
        interior = _wall(model, space, _opaque_construction(model, 'Int',
                                                            0.5, 0.1))
        interior.setOutsideBoundaryCondition('Adiabatic')

        section = envelope_section(model)
        self.assertEqual(['Wall:Outdoors'], list(section['opaque']))
        self.assertEqual(1, section['opaque']['Wall:Outdoors']
                         ['from']['surfaces'])
        self.assertNotIn('Adiabatic', ENVELOPE_BOUNDARIES)
        del exterior

    def test_an_unreadable_surface_is_LISTED_not_defaulted(self):
        """A recipe that quietly fills in a plausible number is worse than one
        that says it does not know, because a reader cannot tell them apart."""
        import openstudio

        model = openstudio.model.Model()
        space = openstudio.model.Space(model)
        bare = _wall(model, space, _opaque_construction(model, 'Readable'))
        bare.resetConstruction()
        bare.setName('No Construction Wall')
        audit = AuditLog()

        section = envelope_section(model, audit=audit)
        self.assertEqual({}, section['opaque'],
                         'nothing invented for the only surface')
        self.assertEqual(1, len(section['unreadable']))
        self.assertEqual('No Construction Wall',
                         section['unreadable'][0]['surface'])
        self.assertTrue(any('OMITTED' in str(e.get('value')
                                             or e.get('action') or '')
                            for e in audit.entries),
                        'and the omission is in the trail')

    def test_SHGC_is_absent_rather_than_the_0_60_fallback(self):
        """`constructions.fenestration_solar_transmittance` returns 0.60 when
        it finds no glazing layer — right when APPLYING a construction, a
        fabrication when reading one."""
        import openstudio

        from btap.modeling.envelope.constructions import fenestration_solar_transmittance

        model = openstudio.model.Model()
        space = openstudio.model.Space(model)
        wall = _wall(model, space, _opaque_construction(model, 'Host Wall 3'))
        opaque_door = _opaque_construction(model, 'Solid Door', 0.1, 0.05)

        pts = openstudio.Point3dVector()
        for x, z in ((1, 0), (2, 0), (2, 2), (1, 2)):
            pts.append(openstudio.Point3d(x, 0.0, z))
        sub = openstudio.model.SubSurface(pts, model)
        sub.setSurface(wall)
        sub.setSubSurfaceType('Door')
        sub.setConstruction(opaque_door)

        self.assertAlmostEqual(
            0.60, fenestration_solar_transmittance(opaque_door),
            msg='the existing helper fabricates this')
        entry = envelope_section(model)['fenestration']['Door:Outdoors']
        self.assertNotIn('shgc', entry,
                         'and the writer omits it instead')


if __name__ == '__main__':
    unittest.main()
