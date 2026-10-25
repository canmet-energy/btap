"""`modeling.seed_constructions` — the authoring chain's first precondition.

`btap/modeling/README.md` documents a chain whose first step is a seed
construction set, because wizard and bar output carries NO constructions and
every envelope pass retargets an EXISTING one. Until issue #143 the only
implementation was a method on a test class, so the documented chain could be
started from a repository checkout and not from the installed wheel.

The Kiva test below is the one that matters. The first version of the seed used
a `MasslessOpaqueMaterial` — the obvious placeholder — and EnergyPlus REFUSES a
massless layer on a `Foundation` surface, so the default `ground_model="kiva"`
path was unreachable from every seeded model. Reverting to massless takes the
Kiva count from 4 of 4 to 0 of 4, and the whole suite stayed green at 2338
while that was true, because nothing drove a seeded model through foundations.
"""

import pathlib
import unittest

from tests.support import needs_engine

try:
    import openstudio  # noqa: F401

    import btap.modeling as modeling
    from btap.modeling.envelope import constructions
    HAVE_SDK = True
except ImportError:  # pragma: no cover - the engine-free lane
    modeling = constructions = None
    HAVE_SDK = False

needs_sdk = unittest.skipUnless(HAVE_SDK, "the OpenStudio SDK is required")

WEATHER = (pathlib.Path(__file__).resolve().parents[1] / "fixtures"
           / "weather")
EPW = WEATHER / "CAN_ON_Toronto.Intl.AP.716240_CWEC2020.epw"
DDY = WEATHER / "CAN_ON_Toronto.Intl.AP.716240_CWEC2020.ddy"


def _standard_layers(construction):
    """The construction's layers, each asserted to be a standard material.

    Every downcast asserts before it dereferences because `.get()` on an empty
    Optional exits 139 (SIGSEGV) with no Python exception and the output
    buffered and lost — issue #141's mechanism, confirmed under the massless
    mutation, where these tests dumped core instead of failing.
    """
    out = []
    for layer in construction.layers():
        standard = layer.to_StandardOpaqueMaterial()
        assert standard.is_initialized(), (
            f"{layer.nameString()} is not a StandardOpaqueMaterial "
            f"(guarded: issue #141)")
        out.append(standard.get())
    return out


def _board_of(construction):
    """The fixed board layer, found by its EXPORTED name.

    Not by position: the order is batt-then-board and a check reading
    `layers()[1]` would keep passing if the order changed for the wrong
    reason, which is exactly the regression `318` A2 was. Not by density or
    thickness either — those match whatever else shares them. The name is a
    constant the product code exports, so a rename moves both sides together.
    """
    # PREFIX, not equality: `deep_copy` renames a copied layer by appending a
    # counter, so a retargeted construction carries "Seed Interior Board 1"
    # and an exact match finds nothing on exactly the constructions these
    # tests care most about. Anchored to the exported constant, and
    # `_standard_layers` asserts a single match, so a future layer sharing the
    # prefix fails loudly instead of being picked up silently.
    boards = [m for m in _standard_layers(construction)
              if m.nameString().startswith(constructions.BOARD_LAYER_NAME)]
    assert len(boards) == 1, (
        f"expected exactly one board layer, found "
        f"{[m.nameString() for m in _standard_layers(construction)]}")
    return boards[0]


def areal_mass(construction):
    return sum(m.thickness() * m.density()
               for m in _standard_layers(construction))


def heat_capacity(construction):
    return sum(m.thickness() * m.density() * m.specificHeat()
               for m in _standard_layers(construction))



@needs_sdk
class TestSeedConstructions(unittest.TestCase):
    def _seeded(self, **kwargs):
        model = modeling.create(
            shape="rectangle", length=30.0, width=20.0, storeys=1)
        modeling.apply_wwr(model, wwr=0.4)
        modeling.seed_constructions(model, **kwargs)
        return model

    def test_every_surface_and_sub_surface_gets_one(self):
        model = self._seeded()
        surfaces = model.getSurfaces()
        sub_surfaces = model.getSubSurfaces()
        self.assertTrue(surfaces)
        self.assertTrue(sub_surfaces, "apply_wwr must have made windows to seed")
        self.assertEqual(
            [], [s.nameString() for s in surfaces
                 if not s.construction().is_initialized()],
            "a surface with no construction is what the envelope pass cannot "
            "retarget")
        self.assertEqual(
            [], [s.nameString() for s in sub_surfaces
                 if not s.construction().is_initialized()])

    def test_the_opaque_layer_carries_REAL_THERMAL_MASS(self):
        """A massless layer makes the default Kiva ground model unreachable.

        Pinned as a property of the material, not only through the Kiva
        behaviour below, so a reader sees WHY the material type is load-bearing.
        """
        model = self._seeded()
        floor = next(s for s in model.getSurfaces()
                     if s.surfaceType() == "Floor"
                     and s.outsideBoundaryCondition() == "Ground")
        construction = floor.construction().get().to_Construction().get()
        for layer in construction.layers():
            self.assertFalse(
                layer.to_MasslessOpaqueMaterial().is_initialized(),
                "a MasslessOpaqueMaterial is refused by EnergyPlus on a "
                "Foundation surface — see the Kiva test")
        # The DECLARED material, asserted from its own four properties.
        # An earlier version asserted equality to NECB Note A-8.4.4.4.(1)'s
        # wood-frame example; Sol refused that (`320`) because those numbers
        # were selected for a reference approximation and imply a code
        # identity a synthetic seed does not have.
        board = _board_of(construction)
        self.assertAlmostEqual(constructions.BOARD_THICKNESS_M,
                               board.thickness(), places=9)
        self.assertAlmostEqual(constructions.BOARD_DENSITY_KG_M3,
                               board.density(), places=6)
        self.assertAlmostEqual(constructions.BOARD_SPECIFIC_HEAT_J_KGK,
                               board.specificHeat(), places=6)
        # DERIVED, not a chosen round number: the construction must store at
        # least what the board alone stores. A chosen 10 kJ/(m2.K) passed a
        # 12.7 mm board and failed a 10 mm one, so it was really a thickness
        # assertion in disguise (Fable, `318` addendum 3). This form still
        # kills the massless mutation, which stores nothing.
        self.assertGreaterEqual(
            heat_capacity(construction),
            constructions.BOARD_THICKNESS_M
            * constructions.BOARD_DENSITY_KG_M3
            * constructions.BOARD_SPECIFIC_HEAT_J_KGK,
            "the construction must store at least the board's own heat; a "
            "massless layer stores none, and is refused on a Foundation "
            "surface besides")

    def test_a_seeded_ground_floor_CAN_become_a_Kiva_foundation(self):
        """The behavioural witness: 4 of 4 with mass, 0 of 4 without."""
        from btap.modeling.envelope import foundations

        model = self._seeded()
        grounds = [s for s in model.getSurfaces()
                   if s.surfaceType() == "Floor"
                   and s.outsideBoundaryCondition() == "Ground"]
        measured = foundations.exposed_perimeters(model, grounds)["perimeters"]
        exposed = [s for s in grounds
                   if measured.get(s.nameString(), 0.0) > 0.01]
        self.assertTrue(
            exposed, "the fixture must have a ground floor with exposed edge "
                     "or this proves nothing")

        refusals = []
        created = 0
        for surface in exposed:
            result = foundations.create_kiva_foundation(model, surface)
            if result["created"]:
                created += 1
            else:
                refusals.extend(result["refusals"])
        self.assertEqual(
            len(exposed), created,
            "every exposed seeded ground floor must be Kiva-legal; "
            f"refusals: {refusals}")

    def test_the_r_value_dial_is_honoured(self):
        model = self._seeded(opaque_r_si=3.5)
        wall = next(s for s in model.getSurfaces()
                    if s.surfaceType() == "Wall"
                    and s.outsideBoundaryCondition() == "Outdoors")
        construction = wall.construction().get().to_Construction().get()
        # The construction's resistance, NOT layer 0's: the seed has two
        # layers and `opaque_r_si` is the resistance of the pair.
        self.assertAlmostEqual(
            3.5, 1.0 / construction.thermalConductance().get(), places=3,
            msg="the batt layer is sized to make up the requested total")

    def test_retargeting_copies_rather_than_mutating_the_seed(self):
        """Why ONE opaque construction can serve every surface type.

        `opaque_at_conductance` deep-copies and reuses by name, so improving a
        wall cannot alter a roof that shares the seed. If that stopped being
        true, one seed construction for all surfaces would be wrong.
        """
        model = self._seeded()
        seed = (model.getSurfaces()[0].construction().get()
                .to_Construction().get())
        before = seed.thermalConductance().get()

        retargeted = constructions.opaque_at_conductance(model, seed, 0.21)
        self.assertNotEqual(seed.nameString(), retargeted.nameString())
        after = seed.thermalConductance().get()
        self.assertAlmostEqual(before, after, places=6,
                               msg="the seed itself must be untouched")


    def test_the_mass_SURVIVES_retargeting_across_the_range(self):
        """F1: a one-layer seed quadrupled its mass on the way to code.

        `opaque_at_conductance` solves with `setConductance`, which on a lone
        `StandardOpaqueMaterial` grows its THICKNESS. A seeded roof retargeted
        to U-0.156 became a 0.48 m slab at four times the mass it started
        with. Asking for more RESISTANCE and silently getting four times the
        MASS is incoherent on its own terms: the caller named one property and
        a different one moved.

        The two-layer seed exists for this: `find_and_set_insulation_layer`
        picks the batt because its resistance is the larger, so only the batt
        grows and the board's mass stays put.
        """
        model = self._seeded()
        seed = (model.getSurfaces()[0].construction().get()
                .to_Construction().get())
        board_before = _board_of(seed).thickness()

        # A spread of plausible improvement targets, from a mild wall to a
        # well-insulated roof. The point is the MECHANISM across a range, not
        # any particular target.
        for conductance in (0.278, 0.21, 0.183, 0.156, 0.121):
            with self.subTest(conductance=conductance):
                retargeted = constructions.opaque_at_conductance(
                    model, seed, conductance)
                self.assertAlmostEqual(
                    conductance, retargeted.thermalConductance().get(),
                    places=3, msg="the retarget must still hit its target")

                # THE EXACT MECHANISM, not a tolerance. All the added
                # resistance goes into the batt, so the added mass is exactly
                # that resistance times the batt's own conductivity and
                # density. An earlier version asserted "within 10%", a bound
                # picked to fit a spread already measured — which would have
                # passed throughout the band `318` A1 found.
                predicted = (
                    constructions.BOARD_THICKNESS_M
                    * constructions.BOARD_DENSITY_KG_M3
                    + (1.0 / conductance - constructions.BOARD_R_SI)
                    * constructions.BATT_CONDUCTIVITY_W_MK
                    * constructions.BATT_DENSITY_KG_M3)
                self.assertAlmostEqual(
                    predicted, areal_mass(retargeted), places=6,
                    msg=f"at U-{conductance} the added mass must be the "
                        f"batt's alone")
                self.assertAlmostEqual(
                    board_before, _board_of(retargeted).thickness(),
                    places=9,
                    msg="the board layer must not grow — that IS the fix")

    def test_an_r_value_the_BATT_cannot_dominate_is_REFUSED(self):
        """`318` A1: the picker grows whichever layer resists more.

        The batt only carries `opaque_r_si - BOARD_R_SI`, so below twice the
        board's own resistance the BOARD is the insulation layer and
        retargeting grows IT instead — measured at 1.4 m for a U-0.156
        target. The first version of this guard sat at ONE times the fixed
        layer's resistance and left that whole band open.
        """
        floor = 2 * constructions.BOARD_R_SI
        for r_si in (constructions.BOARD_R_SI, floor * 0.75, floor):
            with self.subTest(opaque_r_si=r_si):
                with self.assertRaises(ValueError):
                    self._seeded(opaque_r_si=r_si)

    def test_just_ABOVE_the_floor_the_batt_is_still_what_grows(self):
        """The boundary the guard is drawn at, from the other side."""
        model = self._seeded(opaque_r_si=2 * constructions.BOARD_R_SI + 0.0001)
        seed = (model.getSurfaces()[0].construction().get()
                .to_Construction().get())
        board_before = _board_of(seed).thickness()

        retargeted = constructions.opaque_at_conductance(model, seed, 0.156)
        self.assertAlmostEqual(
            board_before, _board_of(retargeted).thickness(), places=9,
            msg="the board must not grow at the very edge of the legal range")
        self.assertLess(
            areal_mass(retargeted),
            3 * constructions.BOARD_THICKNESS_M
            * constructions.BOARD_DENSITY_KG_M3,
            msg="a board-grown construction is an order of magnitude heavier")

    def test_the_MASS_is_on_the_inside_of_the_insulation(self):
        """`318` A2, and the only witness of the layer ORDER.

        EnergyPlus reads a Construction's first layer as the OUTSIDE one, so
        board-then-batt puts the thermal mass on the weather and soil side of
        the insulation, decoupled from the zone it exists to damp. That is the
        opposite of why the mass is there, and it is invisible to every other
        check here: reverting the order left all nine of them green.

        For a two-layer construction "last layer" IS "interior side", so this
        asserts the mechanism directly rather than a proxy for it.
        """
        model = self._seeded()
        construction = (model.getSurfaces()[0].construction().get()
                        .to_Construction().get())
        layers = [m.nameString() for m in _standard_layers(construction)]
        self.assertEqual(
            2, len(layers), "the seed is two layers; see the module docstring")
        self.assertTrue(
            layers[-1].startswith(constructions.BOARD_LAYER_NAME),
            f"the board carries the mass and must be the INTERIOR layer, "
            f"not the exterior one; got {layers}")
        self.assertFalse(
            layers[0].startswith(constructions.BOARD_LAYER_NAME),
            f"and must not also be the exterior layer; got {layers}")

    def test_the_boards_resistance_is_DERIVED_not_declared(self):
        """The package-boundary guard Sol asked for (`320`).

        A declared resistance is exactly where a borrowed code value
        reappears: the refused version's fixed layer carried NECB Note
        A-8.4.4.4.(1)'s framing-path `R = 0.611` as a constant of its own.
        Deriving `BOARD_R_SI` from thickness and conductivity means the
        resistance cannot be chosen independently of the material, so there is
        nowhere for such a value to sit.

        `btap.modeling` is generic authoring with no NECB anywhere (D-77).
        `lint-imports` enforces the import half; a RESTATED value decides
        simulation physics just the same and no linter sees it.
        """
        self.assertAlmostEqual(
            constructions.BOARD_THICKNESS_M
            / constructions.BOARD_CONDUCTIVITY_W_MK,
            constructions.BOARD_R_SI, places=12,
            msg="BOARD_R_SI must be thickness / conductivity, not a number "
                "chosen on its own")

        model = self._seeded()
        board = _board_of(model.getSurfaces()[0].construction().get()
                          .to_Construction().get())
        self.assertAlmostEqual(
            constructions.BOARD_R_SI, board.thermalResistance(), places=9,
            msg="and the material built from it must agree")

    def test_the_board_SURVIVES_the_largest_target_any_caller_passes(self):
        """The trim edge, pinned by its MARGIN rather than by a claim.

        Above `1 / BOARD_R_SI` the solver trims the fixed layer away and the
        construction loses its mass entirely. The previous fixed layer put
        that edge at 1.637 W/(m2.K), BELOW almost every NECB door target, so
        retargeting a seeded door through the prescriptive path returned a
        construction with no mass layer and nothing said so. A thinner board
        moved the edge to 10 and fixed it by accident (Fable, `318`
        addendum 3).

        3.2 is just above the largest target any caller in this repository
        passes — the zone-4 door at 3.11 construction-only. If a future
        change to the board pulls the edge back down toward the callers, this
        fails instead of silently dropping the layer.
        """
        model = self._seeded()
        seed = (model.getSurfaces()[0].construction().get()
                .to_Construction().get())

        retargeted = constructions.opaque_at_conductance(model, seed, 3.2)
        names = [m.nameString() for m in _standard_layers(retargeted)]
        self.assertEqual(
            2, len(names),
            f"both layers must survive the largest real target; got {names}")
        self.assertAlmostEqual(
            constructions.BOARD_THICKNESS_M,
            _board_of(retargeted).thickness(), places=9,
            msg="and the board must not have been trimmed")

    def test_a_DOOR_does_not_silently_become_glass(self):
        """F2: the forward translator rewrites the sub-surface type.

        Seeding every sub-surface with glazing made EnergyPlus log "uses
        fenestration construction, changing SubSurfaceType to GlassDoor" and
        turned a submitter's opaque door into a glass one, with nothing in the
        audit. Doors take the opaque construction.
        """
        model = modeling.create(
            shape="rectangle", length=30.0, width=20.0, storeys=1)
        modeling.apply_wwr(model, wwr=0.4)
        door = model.getSubSurfaces()[0]
        door.setName("PROBE DOOR")
        self.assertTrue(door.setSubSurfaceType("Door"))

        modeling.seed_constructions(model)

        self.assertEqual("Door", door.subSurfaceType(),
                         "seeding must not change the sub-surface type")
        layers = (door.construction().get().to_Construction().get().layers())
        self.assertEqual(
            [], [x.nameString() for x in layers
                 if x.to_SimpleGlazing().is_initialized()],
            "a door must not carry a glazing layer")
        window = next(s for s in model.getSubSurfaces()
                      if s.subSurfaceType() == "FixedWindow")
        self.assertTrue(
            window.construction().get().to_Construction().get()
            .layers()[0].to_SimpleGlazing().is_initialized(),
            "while a window still does")


@needs_engine
class TestSeedConstructionsSimulate(unittest.TestCase):
    """EnergyPlus must ACCEPT the seed's layer stack.

    Everything above is a property of the model in memory. None of it would
    notice a layer stack EnergyPlus dislikes — a 0.3 m batt, a two-layer
    construction on a Kiva foundation, or the opaque door the F2 fix
    introduced. Fable ran it by hand at `318` and reported 0 Severe; a
    hand-run is not a witness, so it runs here, in the engine lane.

    TWO THINGS THIS TEST LEARNED THE HARD WAY, both recorded because the
    first version of it passed while proving neither:

    `modeling.create` makes spaces and NO thermal zones, and the forward
    translator drops every surface of a zoneless model. The first version ran
    in 1.2 s and reported a clean error file for an IDF holding four
    constructions, no surfaces, no Kiva and no door — a pass that attested
    nothing. Hence the zones below, and hence the IDF assertions: a clean
    error file from a run that never saw the objects is not evidence about
    them.

    And retargeting must not touch an INTERZONE surface. Doing so gave one
    side of a pair the code target and left the other at the seed, which is
    FATAL: "Construction SEED OPAQUE of interzone surface ... does not have
    the same materials in the reverse order". Exterior-only matches what the
    NECB envelope pass does, and is why `outsideBoundaryCondition` is checked
    before the construction is assigned.
    """

    def test_energyplus_ACCEPTS_the_two_layer_stack_with_kiva_and_a_door(self):
        import re
        import tempfile

        import openstudio

        from btap import simulation
        from btap.modeling.envelope import foundations

        model = modeling.create(
            shape="rectangle", length=30.0, width=20.0, storeys=1)
        modeling.apply_wwr(model, wwr=0.4)
        # One opaque door, so the F2 branch is in the simulated model.
        door = model.getSubSurfaces()[0]
        door.setName("SEEDED DOOR")
        self.assertTrue(door.setSubSurfaceType("Door"))
        modeling.seed_constructions(model)

        # Without zones the translator emits no surfaces at all; see the
        # class docstring.
        for space in model.getSpaces():
            space.setThermalZone(openstudio.model.ThermalZone(model))

        # Retarget to a plausible improvement target so the batt is at its
        # grown
        # thickness, EXTERIOR surfaces only — see the class docstring.
        seed = (model.getSurfaces()[0].construction().get()
                .to_Construction().get())
        retargeted = constructions.opaque_at_conductance(model, seed, 0.121)
        roofs = [s for s in model.getSurfaces()
                 if s.surfaceType() == "RoofCeiling"
                 and s.outsideBoundaryCondition() == "Outdoors"]
        self.assertTrue(roofs, "the fixture must have exterior roofs")
        for surface in roofs:
            surface.setConstruction(retargeted)

        grounds = [s for s in model.getSurfaces()
                   if s.surfaceType() == "Floor"
                   and s.outsideBoundaryCondition() == "Ground"]
        measured = foundations.exposed_perimeters(model, grounds)["perimeters"]
        kivas = sum(
            1 for s in grounds
            if measured.get(s.nameString(), 0.0) > 0.01
            and foundations.create_kiva_foundation(model, s)["created"])
        self.assertTrue(kivas, "the Kiva path must be in this model")

        severe = re.compile(r"\*\*\s*Severe\s*\*\*")
        fatal = re.compile(r"\*\*\s*Fatal\s*\*\*")
        with tempfile.TemporaryDirectory(prefix="seed-sim-") as work:
            run_dir = pathlib.Path(work) / "run"
            try:
                simulation.run(
                    model, run_dir=str(run_dir),
                    weather={"epw": str(EPW), "ddy": str(DDY)},
                    sizing_only=True)
            except Exception:                                 # noqa: BLE001
                # The backend RAISES on a failed run, so the evidence has to
                # be read on this path too — the same defect this
                # repository's own sweep had.
                pass

            err = ""
            for found in sorted(run_dir.rglob("eplusout.err")):
                err = found.read_text(encoding="utf-8", errors="replace")
                break
            self.assertTrue(err, "no eplusout.err — the run did not happen, "
                                 "and an absent error file is not a pass")

            idf = ""
            for found in sorted(run_dir.rglob("in.idf")):
                idf = found.read_text(encoding="utf-8", errors="replace")
                break
            self.assertTrue(idf, "no in.idf — nothing attests the input")
            for required in (constructions.BOARD_LAYER_NAME, "Seed Batt",
                             "Foundation:Kiva", "SEEDED DOOR",
                             "BuildingSurface:Detailed"):
                self.assertIn(
                    required, idf,
                    f"{required!r} never reached the IDF, so this run says "
                    f"nothing about it")

            first = ""
            for line in err.splitlines():
                if severe.search(line) or fatal.search(line):
                    first = line.strip()[:220]
                    break
            self.assertEqual(
                (0, 0), (len(severe.findall(err)), len(fatal.findall(err))),
                f"EnergyPlus must accept a stack we author; first: {first}")


if __name__ == "__main__":
    unittest.main()
