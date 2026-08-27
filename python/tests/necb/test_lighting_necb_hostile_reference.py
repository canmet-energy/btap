"""Hostile-outcome gate for the reference LIGHTING transform (NECB 8.4.4.5.(1)).

Method: give the PROPOSED a deliberately non-compliant lighting power, build
the reference, then assert the reference carries the Part 4 ALLOWANCE rather
than the hostile proposed value.

Why outcomes and not audit strings: the reference is a CLONE of the proposed,
so a transform that silently no-ops leaves reference LPD == proposed LPD —
i.e. the allowance is waived and the proposed is compared against itself. The
audit meanwhile records a confident "interior lighting applied" decision. Any
test that asserts on the audit passes while the model is wrong, which is
exactly how this class of defect survived. Assert model values only.

Expected values are recomputed from the catalog in-test rather than
hardcoded, so the assertions follow the data if it is revised.

Port of btap-necb/test/test_lighting_necb_hostile_reference.rb.
"""

import unittest

from tests.necb.support import needs_sdk

HOSTILE_W_PER_M2 = 99.0
KNOWN_SPACE_TYPE = "Office enclosed > 25 m2"
# Deliberately absent from the 308-row catalog. Note the real rows are
# 'Office enclosed <= 25 m2' and 'Office enclosed > 25 m2' — this hyphenated
# form is the shape of name a foreign or older model actually carries.
UNKNOWN_SPACE_TYPE = "Office - enclosed"


def tagged_space_type(model, building_type, space_type):
    import openstudio

    st = openstudio.model.SpaceType(model)
    st.setName(f"{building_type} {space_type}")
    st.setStandardsBuildingType(building_type)
    st.setStandardsSpaceType(space_type)
    return st


@needs_sdk
class TestNECBHostileReferenceLighting(unittest.TestCase):
    def catalog_lpd_w_per_m2(self, space_type):
        import openstudio

        from btap.necb.loads import space_types as SpaceTypes

        record = SpaceTypes.find(building_type="Space Function", space_type=space_type,
                                 vintage="2020")
        self.assertIsNotNone(record,
                             f"fixture precondition: '{space_type}' must exist in the catalog")
        return openstudio.convert(float(record["lighting_per_area"]), "W/ft^2", "W/m^2").get()

    def hostile_lights(self, space_type):
        """Stand in for an over-lit proposed design."""
        import openstudio

        definition = openstudio.model.LightsDefinition(space_type.model())
        definition.setName(f"{space_type.nameString()} HOSTILE Lights Definition")
        definition.setWattsperSpaceFloorArea(HOSTILE_W_PER_M2)
        lights = openstudio.model.Lights(definition)
        lights.setName(f"{space_type.nameString()} HOSTILE Lights")
        lights.setSpaceType(space_type)
        return space_type

    def lpd_of(self, space_type):
        instances = space_type.lights()
        if not instances:
            return None

        watts = instances[0].lightsDefinition().wattsperSpaceFloorArea()
        return watts.get() if watts.is_initialized() else None

    # Positive control: for a catalog-resolvable space type the transform must
    # overwrite the hostile value with the allowance. If this fails, the harness
    # itself is broken and the negative case below proves nothing.
    def test_reference_lighting_overwrites_hostile_lpd_for_known_space_type(self):
        import openstudio

        from btap.audit import AuditLog
        from btap.necb import lighting

        model = openstudio.model.Model()
        space_type = self.hostile_lights(
            tagged_space_type(model, "Space Function", KNOWN_SPACE_TYPE))

        lighting.reference_lighting(model, vintage="2020", audit=AuditLog())

        self.assertAlmostEqual(self.catalog_lpd_w_per_m2(KNOWN_SPACE_TYPE),
                               self.lpd_of(space_type), delta=1e-6,
                               msg="8.4.4.5.(1): reference LPD must be the Part 4 allowance, "
                                   "not the proposed value")
        self.assertNotAlmostEqual(HOSTILE_W_PER_M2, self.lpd_of(space_type), delta=1e-6,
                                  msg="reference retained the hostile proposed LPD")

    def with_space(self, space_type):
        """A space type only matters if a floor-area space uses it — attach one so
        the gate treats the type as consequential."""
        import openstudio

        space = openstudio.model.Space(space_type.model())
        space.setSpaceType(space_type)
        return space_type

    # DEFECT #1 — fixed: the reference transform now REFUSES, loudly.
    #
    # apply_lights silently skips space types with no catalog record, and the
    # reference is a clone — so before the fix, an unmatched type kept the
    # proposed's LPD verbatim: the 8.4.4.5.(1) allowance was waived and an
    # over-lit space incurred zero penalty. The allowance for an unlisted space
    # function is a human judgement (4.2.1.6.(1)(b)), so no fallback value is
    # invented: reference_lighting raises before a wrong reference can exist,
    # naming the type. (The umbrella pre-flight fails even earlier, with
    # suggestions — this guards direct gem callers.)
    def test_reference_lighting_refuses_unknown_space_type_instead_of_keeping_hostile_lpd(self):
        import openstudio

        from btap.audit import AuditLog
        from btap.necb import lighting

        model = openstudio.model.Model()
        space_type = self.with_space(self.hostile_lights(
            tagged_space_type(model, "Space Function", UNKNOWN_SPACE_TYPE)))

        audit = AuditLog()
        with self.assertRaises(ValueError) as ctx:
            lighting.reference_lighting(model, vintage="2020", audit=audit)

        self.assertIn(UNKNOWN_SPACE_TYPE, str(ctx.exception),
                      "the refusal must name the unresolvable space type")
        self.assertIn("8.4.4.5.(1)", str(ctx.exception),
                      "the refusal must cite the waived allowance article")
        self.assertAlmostEqual(HOSTILE_W_PER_M2, self.lpd_of(space_type), delta=1e-6,
                               msg="the model must be left untouched on refusal — "
                                   "no partial transform")
        self.assertTrue(any(UNKNOWN_SPACE_TYPE in str(w["action"])
                            and "UNRESOLVABLE" in str(w["action"]) for w in audit.warnings),
                        "the refusal must also land in the audit trail "
                        "(warnings are never silent)")

    # An unmatched space type NO floor-area space uses is inconsequential — the
    # gate must not refuse over the fixture's orphan space types.
    def test_unused_unknown_space_type_does_not_block_reference_lighting(self):
        import openstudio

        from btap.audit import AuditLog
        from btap.necb import lighting

        model = openstudio.model.Model()
        self.with_space(tagged_space_type(model, "Space Function", KNOWN_SPACE_TYPE))
        tagged_space_type(model, "Space Function", UNKNOWN_SPACE_TYPE)  # orphan: no spaces

        audit = AuditLog()
        lighting.reference_lighting(model, vintage="2020", audit=audit)  # must not raise

        self.assertFalse(any("UNRESOLVABLE" in str(w["action"]) for w in audit.warnings),
                         "orphan space types must not generate unresolvable warnings")

    # Plenums are skipped BY DESIGN (apply_lights.py _is_plenum). Pinned so that
    # whatever fix lands for the miss above does not turn a deliberate exemption
    # into a false failure.
    def test_plenum_exemption_is_preserved(self):
        import openstudio

        from btap.audit import AuditLog
        from btap.necb import lighting

        model = openstudio.model.Model()
        plenum = self.hostile_lights(
            tagged_space_type(model, "Space Function", "Office enclosed <= 25 m2"))
        plenum.setName("Zone 1 Plenum")

        lighting.reference_lighting(model, vintage="2020", audit=AuditLog())

        self.assertAlmostEqual(HOSTILE_W_PER_M2, self.lpd_of(plenum), delta=1e-6,
                               msg="plenums are exempt by design and must be left untouched")


if __name__ == "__main__":
    unittest.main()
