"""An exterior Door is a SUB-surface with an OPAQUE assembly.

The recipe writer bucketed every sub-surface as fenestration, so the reader
handed an opaque door a glazing construction and the EnergyPlus
ForwardTranslator reclassified it. All 29 exterior doors in
`Office_pre-1960` came out of a round trip as `GlassDoor` in the IDF, gaining
solar heat the real doors do not admit.

**The OSM did not show it.** `subSurfaceType()` still reported `'Door'` after
the round trip; only the translated IDF differed. A check at the OSM layer
passes against the unfixed code, which is why these tests assert on the
CONSTRUCTION being opaque rather than on the sub-surface type.

Found by an Astra agent reading the saved artefacts. The ForwardTranslator had
said so during the original run — `uses fenestration construction, changing
SubSurface type from Door to GlassDoor` — and my own output filter
(`grep -v "^\["`) stripped exactly those lines.
"""

from __future__ import annotations

import unittest

from tests.support import needs_sdk


@needs_sdk
class DoorBase(unittest.TestCase):

    def setUp(self):
        import openstudio

        self.os = openstudio
        self.model = openstudio.model.Model()

    def _wall_with(self, sub_type, glazed):
        """A 10x3 exterior wall carrying one sub-surface of `sub_type`."""
        os = self.os
        space = os.model.Space(self.model)
        pts = [os.Point3d(0, 0, 3), os.Point3d(0, 0, 0),
               os.Point3d(10, 0, 0), os.Point3d(10, 0, 3)]
        wall = os.model.Surface(os.Point3dVector(pts), self.model)
        wall.setSpace(space)
        wall.setSurfaceType('Wall')
        wall.setOutsideBoundaryCondition('Outdoors')

        opaque = os.model.StandardOpaqueMaterial(self.model)
        opaque.setThickness(0.05)
        opaque.setConductivity(0.1)
        wall.setConstruction(
            os.model.Construction(os.model.OpaqueMaterialVector([opaque])))

        spts = [os.Point3d(2, 0, 2), os.Point3d(2, 0, 0),
                os.Point3d(4, 0, 0), os.Point3d(4, 0, 2)]
        sub = os.model.SubSurface(os.Point3dVector(spts), self.model)
        sub.setSurface(wall)
        sub.setSubSurfaceType(sub_type)

        if glazed:
            glazing = os.model.SimpleGlazing(self.model)
            glazing.setUFactor(3.0)
            glazing.setSolarHeatGainCoefficient(0.6)
            layers = os.model.FenestrationMaterialVector([glazing])
        else:
            core = os.model.StandardOpaqueMaterial(self.model)
            core.setThickness(0.04)
            core.setConductivity(0.16)
            layers = os.model.OpaqueMaterialVector([core])
        sub.setConstruction(os.model.Construction(layers))
        return sub

    def section(self):
        from btap.stock.envelope import envelope_section

        return envelope_section(self.model)

    def construction_is_opaque(self, sub):
        from btap._compat import opt

        layered = opt(sub.construction()).to_LayeredConstruction()
        self.assertTrue(layered.is_initialized())
        return layered.get().isOpaque()


class TestTheWriterBucketsByIsOpaque(DoorBase):

    def test_an_opaque_Door_is_filed_as_OPAQUE(self):
        self._wall_with('Door', glazed=False)
        section = self.section()

        self.assertIn('Door:Outdoors', section['opaque'])
        self.assertNotIn(
            'Door:Outdoors', section['fenestration'],
            'an opaque door filed as fenestration gets a GLAZING construction '
            'from the reader, and the ForwardTranslator then reclassifies it')

    def test_a_GlassDoor_is_still_filed_as_FENESTRATION(self):
        """The control: the fix must not sweep real glazing into opaque."""
        self._wall_with('GlassDoor', glazed=True)
        section = self.section()

        self.assertIn('GlassDoor:Outdoors', section['fenestration'])
        self.assertNotIn('GlassDoor:Outdoors', section['opaque'])
        self.assertIsNotNone(
            section['fenestration']['GlassDoor:Outdoors']['shgc'],
            'real glazing carries an SHGC; that is what distinguishes it')

    def test_the_writer_ALREADY_had_the_signal_it_was_not_using(self):
        """An opaque sub-surface has no SHGC to read, and the writer recorded
        `shgc=None` for doors even while filing them as fenestration."""
        self._wall_with('Door', glazed=False)
        self.assertEqual(
            {}, {k: v for k, v in self.section()['fenestration'].items()
                 if 'Door' in k})


class TestTheReaderKeepsThemOpaque(DoorBase):

    def round_trip(self, sub_type, glazed):
        from btap.audit import AuditLog
        from btap.stock.reader import _apply_envelope

        sub = self._wall_with(sub_type, glazed)
        before = self.construction_is_opaque(sub)
        _apply_envelope(self.model, self.section(), [], [], AuditLog())
        return before, self.construction_is_opaque(sub)

    def test_an_opaque_door_is_STILL_opaque_after_a_round_trip(self):
        before, after = self.round_trip('Door', glazed=False)
        self.assertTrue(before, 'precondition: it started opaque')
        self.assertTrue(
            after,
            'the door was given a glazing construction — this is the defect, '
            'and it is INVISIBLE at the subSurfaceType layer')

    def test_CONTROL_a_glass_door_stays_glazed(self):
        before, after = self.round_trip('GlassDoor', glazed=True)
        self.assertFalse(before)
        self.assertFalse(
            after, 'real glazing must not be turned opaque by the fix')

    def test_the_subSurfaceType_alone_CANNOT_see_the_defect(self):
        """Pins why the tests above assert on the construction.

        A check on `subSurfaceType()` passes either way, because OpenStudio
        keeps the declared type and only the ForwardTranslator reclassifies.
        """
        from btap.audit import AuditLog
        from btap.stock.reader import _apply_envelope

        sub = self._wall_with('Door', glazed=False)
        _apply_envelope(self.model, self.section(), [], [], AuditLog())
        self.assertEqual(
            'Door', sub.subSurfaceType(),
            'if this ever changes, the OSM layer became able to show the '
            'defect and these tests could be simplified')
