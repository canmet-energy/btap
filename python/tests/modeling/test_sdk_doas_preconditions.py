"""Three preconditions of `AirLoopHVACDedicatedOutdoorAirSystem`.

Nothing in this package builds that object. The `doas` family builds a DOAS
*pattern* — a 100% outdoor-air loop serving zones through uncontrolled
diffusers — while the SDK object is the other arrangement: one unit
preconditions outdoor air and feeds the OA inlet of several air loops, which
is what a model authored in the OpenStudio App contains.

`btap.codes.necb.path` reads models it did not build, so these preconditions
matter whether or not this package ever ships such a system. All three were
MEASURED, and all three are invisible in process: the SDK accepts the wrong
arrangement and either EnergyPlus refuses it or the translator kills the
process.

Every claim here was independently re-measured by a reviewer (Fable, `238`),
and three of my original statements were WRONG in ways recorded beside them.
These tests carry the corrected facts, not the ones I first wrote.

No catalogue row. An earlier version of this work added two, and they were
withdrawn: the per-zone loops were sized for ventilation while being the
zones' only conditioning (18-77% of design cooling capacity, 1724 unmet
occupied cooling hours against 756 for a PSZ control), teardown left the
dedicated unit orphaned so a replacement build died in EnergyPlus, and a new
catalogue row needs its D-58 reference-selection entry adjudicated against
Table 8.4.x.7.-A, which is not a thing a test author gets to decide.
"""
import pathlib
import unittest

from tests.support import needs_sdk

WEATHER = (pathlib.Path(__file__).resolve().parents[1] / "fixtures"
           / "weather")
EPW = WEATHER / "CAN_ON_Toronto.Intl.AP.716240_CWEC2020.epw"
DDY = WEATHER / "CAN_ON_Toronto.Intl.AP.716240_CWEC2020.ddy"


def _two_zone_doas(openstudio, *, per_loop_oa_system=True,
                   missing_loop_oa=None, fan="system",
                   setpoints="both-coils"):
    """A central DOAS over per-zone air loops on the SHARED FIXTURE.

    `per_loop_oa_system`, `missing_loop_oa`, `fan` and `setpoints` are the
    three precondition axes below. A tuple of fan types builds one dedicated
    system per type over disjoint served-loop groups.

    The fixture is `5ZoneNoHVAC.osm`, not a synthetic `Model()`. I built a
    synthetic two-zone model first and spent three rounds making it valid —
    a single-zone reheat manager missing a required property, then zone
    sizing not requested — and each defect fired on EVERY case, so all four
    fan variants and all four setpoint variants reported the SAME error and
    the distinctions under test were invisible. A fixture whose own fault
    masks the property is worse than no test. This one already carries
    zones, loads, thermostats and sizing, and the rest of this directory
    uses it.
    """
    from tests.support import load_fixture

    model = load_fixture()
    always = model.alwaysOnDiscreteSchedule()
    zones = sorted(model.getThermalZones(), key=lambda z: z.nameString())
    loops = []
    for index, zone in enumerate(zones):
        loop = openstudio.model.AirLoopHVAC(model)
        loop.setName(f"AL{index}")
        openstudio.model.FanConstantVolume(model, always).addToNode(
            loop.supplyInletNode())
        openstudio.model.CoilHeatingElectric(model, always).addToNode(
            loop.supplyInletNode())
        terminal = (openstudio.model
                    .AirTerminalSingleDuctConstantVolumeNoReheat(
                        model, always))
        loop.addBranchForZone(zone, terminal.to_StraightComponent().get())
        # `SetpointManagerScheduled`, not `SingleZoneReheat`. These
        # synthetic zones carry no loads or geometry, so a single-zone
        # reheat manager is Severe for a missing required property — and
        # that defect fired on EVERY case, making all four fan variants and
        # all four setpoint variants report the same error. A fixture whose
        # own fault masks the property under test proves nothing.
        manager = openstudio.model.SetpointManagerScheduled(
            model, openstudio.model.ScheduleRuleset(model, 13.0))
        manager.addToNode(loop.supplyOutletNode())
        if per_loop_oa_system:
            own = openstudio.model.AirLoopHVACOutdoorAirSystem(
                model, openstudio.model.ControllerOutdoorAir(model))
            own.addToNode(loop.supplyInletNode())
        loops.append(loop)

    neutral = openstudio.model.ScheduleRuleset(model, 20.0)
    neutral.setName("DOAS Neutral Supply Air Temp")
    fan_types = (fan,) if isinstance(fan, str) else tuple(fan)
    for doas_index, fan_type in enumerate(fan_types):
        oa_system = openstudio.model.AirLoopHVACOutdoorAirSystem(
            model, openstudio.model.ControllerOutdoorAir(model))
        dedicated = (openstudio.model
                     .AirLoopHVACDedicatedOutdoorAirSystem(oa_system))
        dedicated.setName(f"Central DOAS {doas_index + 1}")
        for loop in loops[doas_index::len(fan_types)]:
            dedicated.addAirLoop(loop)

        # Outdoors inward: preheat, precool, fan.
        if fan_type == "system":
            made = openstudio.model.FanSystemModel(model)
        elif fan_type == "constant":
            made = openstudio.model.FanConstantVolume(model, always)
        elif fan_type == "variable":
            made = openstudio.model.FanVariableVolume(model, always)
        elif fan_type == "onoff":
            made = openstudio.model.FanOnOff(model, always)
        else:
            made = None
        if made is not None:
            made.setName(f"DOAS {doas_index + 1} Supply Fan")
            made.addToNode(oa_system.outboardOANode().get())
        precool = openstudio.model.CoilCoolingDXSingleSpeed(model)
        precool.setName(f"DOAS {doas_index + 1} Precool Coil")
        precool.addToNode(oa_system.outboardOANode().get())
        preheat = openstudio.model.CoilHeatingElectric(model, always)
        preheat.setName(f"DOAS {doas_index + 1} Preheat Coil")
        preheat.addToNode(oa_system.outboardOANode().get())

        nodes = [c.to_Node().get() for c in oa_system.oaComponents()
                 if c.to_Node().is_initialized()]
        # `nodes` runs outboard to inboard: OA inlet, preheat out, precool
        # out, fan out. Raw outdoor air has nothing to control.
        wanted = {
            "both-coils": nodes[1:3],
            "all-nodes": nodes[1:],
            "preheat-only": nodes[1:2],
            "precool-only": nodes[2:3],
            "inboard-only": nodes[-1:],
            "none": [],
        }[setpoints]
        for node in wanted:
            openstudio.model.SetpointManagerScheduled(
                model, neutral).addToNode(node)
    if missing_loop_oa is not None:
        own = loops[missing_loop_oa].airLoopHVACOutdoorAirSystem()
        if own.is_initialized():
            own.get().remove()
    return model


def _translates(openstudio, model):
    """Does the forward translator survive this model?

    IN A CHILD PROCESS, because the failure under test is not an exception:
    the translator hits `BOOST_ASSERT` and the process dies on SIGSEGV. The
    same reason `modeling/CLAUDE.md` gives for running every glTF export out
    of process.
    """
    import subprocess
    import sys
    import tempfile

    with tempfile.TemporaryDirectory(prefix="doas-ft-") as work:
        osm = pathlib.Path(work) / "m.osm"
        model.save(openstudio.toPath(str(osm)), True)
        script = (
            "import sys, openstudio as o\n"
            "m = o.osversion.VersionTranslator().loadModel("
            "o.toPath(sys.argv[1])).get()\n"
            "w = o.energyplus.ForwardTranslator().translateModel(m)\n"
            # The SDK writes its own log lines to stdout, so the count goes
            # on a marked line the caller can find.
            "print('OBJECTS=%d' % len(w.objects()))\n")
        done = subprocess.run([sys.executable, "-c", script, str(osm)],
                              capture_output=True, text=True, timeout=600)
    count = ""
    for line in done.stdout.splitlines():
        if line.startswith("OBJECTS="):
            count = line.split("=", 1)[1]
    return done.returncode, count, done.stdout + done.stderr


@needs_sdk
class TestTheDedicatedOutdoorAirSystemPreconditions(unittest.TestCase):
    def test_each_served_loop_needs_its_OWN_outdoor_air_system(self):
        """Precondition (a). The first missing loop makes this a CRASH.

        Without an OA system on a served loop the forward translator emits
        `BOOST_ASSERT: Assertion oas failed` at line 115. When the first
        served loop is missing it, the process dies at exit -11 (SIGSEGV).
        A later missing loop can log that same assertion and still return 0,
        so return code alone is not the complete diagnostic.
        """
        import openstudio

        with_own = _two_zone_doas(openstudio, per_loop_oa_system=True)
        code, objects, _err = _translates(openstudio, with_own)
        self.assertEqual(0, code,
                         "a DOAS whose served loops each carry their own OA "
                         "system must translate")
        self.assertGreater(int(objects), 0)

        without = _two_zone_doas(openstudio, per_loop_oa_system=False)
        code, _objects, err = _translates(openstudio, without)
        self.assertNotEqual(
            0, code,
            "a DOAS over loops with NO outdoor-air system of their own must "
            "not translate quietly — the translator aborts the process, and "
            "a test that ran it in-process would take the suite down")
        self.assertIn("Assertion oas failed", err,
                      "and the abort must still be the one documented here")

    def test_EACH_single_missing_loop_is_diagnosed(self):
        """Four correct loops cannot mask any one loop's missing OA system."""
        import openstudio

        for missing in range(5):
            with self.subTest(missing_loop=missing):
                model = _two_zone_doas(
                    openstudio, missing_loop_oa=missing)
                loops = model.getAirLoopHVACs()
                own_oa = sum(
                    loop.airLoopHVACOutdoorAirSystem().is_initialized()
                    for loop in loops)
                self.assertEqual(
                    len(loops) - 1, own_oa,
                    "the fixture must omit exactly one served loop's own "
                    "OA system")

                code, _objects, err = _translates(openstudio, model)
                self.assertIn(
                    "Assertion oas failed", err,
                    "a missing later loop can return 0, but it must not be "
                    "accepted without the SDK's precondition diagnostic")
                if missing == 0:
                    self.assertNotEqual(
                        0, code,
                        "the measured first-loop case aborts the child; "
                        "running this translator in-process would kill pytest")

    def test_the_fan_must_be_a_SYSTEM_model_or_OnOff_not_CV_or_VV(self):
        """Precondition (b), with my over-broad claim corrected.

        I wrote that EnergyPlus "refuses the alternatives" and that the fan
        "must be the system or component model". Measured: `Fan:ConstantVolume`
        and `Fan:VariableVolume` are each refused with "can not be used as a
        component" plus node-connection severes and a Fatal — but
        **`Fan:OnOff` ran clean** (Fable, `238`). So the refusal is of those
        two, not of everything but the system model.

        Whether an OnOff fan is SIMULATED correctly in that position is not
        established by this test, and this test does not claim it: it pins
        which fans EnergyPlus refuses, which is the fact a builder needs.
        """
        import openstudio

        import btap.simulation as simulation

        for fan, expect_clean in (("system", True), ("onoff", True),
                                  ("constant", False), ("variable", False)):
            with self.subTest(fan=fan):
                model = _two_zone_doas(openstudio, fan=fan)
                clean, severe, _fatal, detail, err = _run(simulation,
                                                           model)
                self.assertEqual(
                    expect_clean, clean,
                    f"{fan}: expected clean={expect_clean}, got severe="
                    f"{severe} — {detail}")
                if not expect_clean:
                    self.assertIn("can not be used as a component", err,
                                  f"{fan}: refused for a different reason "
                                  f"than the documented one — {detail}")

    def test_mixed_DOAS_fans_are_decided_PER_dedicated_system(self):
        """One permitted fan cannot mask a refused fan in a sibling DOAS."""
        import openstudio

        import btap.simulation as simulation

        for fans, expect_clean in ((("system", "onoff"), True),
                                   (("system", "constant"), False)):
            with self.subTest(fans=fans):
                model = _two_zone_doas(openstudio, fan=fans)
                self.assertEqual(
                    2, len(model.getAirLoopHVACDedicatedOutdoorAirSystems()),
                    "the fixture must contain both fan arrangements")
                clean, severe, _fatal, detail, err = _run(
                    simulation, model)
                self.assertEqual(
                    expect_clean, clean,
                    f"{fans}: expected clean={expect_clean}, got severe="
                    f"{severe} — {detail}")
                if not expect_clean:
                    self.assertIn(
                        "can not be used as a component", err,
                        "the mixed model must fail because of its refused "
                        "constant-volume DOAS fan, not an unrelated defect")

    def test_each_COIL_needs_a_setpoint_at_its_own_outlet(self):
        """Precondition (c), and my anecdote about it was not reproducible.

        The rule holds: a setpoint at one coil's outlet does not satisfy the
        other. The reviewer's table on the shipped topology:

            setpoints kept                  result
            none                            preheat Severe + DX Severe, Fatal
            fan outlet only (inboard end)   preheat Severe + DX Severe, Fatal
            preheat + precool outlets       CLEAN

        I had written that "a setpoint at the stream's end satisfied the DX
        coil and left the heating coil fatal". On this topology the inboard
        end satisfies NEITHER coil — that sentence described an intermediate
        build in which the DX coil was inboard-most (Fable, `238`).

        The fan outlet needs no setpoint, which is the other half of the
        correction: my builder installed one there and my test asserted it,
        with a message claiming "the coil at its inlet is uncontrolled"
        while the component at that node's inlet is the fan.
        """
        import openstudio

        import btap.simulation as simulation

        for setpoints, expect_clean in (("both-coils", True),
                                        ("all-nodes", True),
                                        ("inboard-only", False),
                                        ("none", False)):
            with self.subTest(setpoints=setpoints):
                model = _two_zone_doas(openstudio, setpoints=setpoints)
                clean, severe, _fatal, detail, _err = _run(simulation,
                                                            model)
                self.assertEqual(
                    expect_clean, clean,
                    f"{setpoints}: expected clean={expect_clean}, got "
                    f"severe={severe} — {detail}")

    def test_each_SINGLE_missing_coil_setpoint_names_that_coil(self):
        """The sibling coil's setpoint cannot satisfy the missing outlet."""
        import openstudio

        import btap.simulation as simulation

        cases = (
            ("preheat-only",
             "CoilSystem:Cooling:DX: Missing temperature setpoint"),
            ("precool-only",
             "Missing temperature setpoint for heating coil"),
        )
        for setpoints, reason in cases:
            with self.subTest(setpoints=setpoints):
                model = _two_zone_doas(openstudio, setpoints=setpoints)
                clean, severe, fatal, detail, err = _run(simulation, model)
                self.assertFalse(
                    clean,
                    f"{setpoints}: one missing coil setpoint must be refused")
                self.assertEqual(
                    (1, 1), (severe, fatal),
                    f"{setpoints}: expected the one causal Severe and its "
                    f"terminal Fatal — {detail}")
                self.assertIn(
                    reason, err,
                    f"{setpoints}: the error must identify the coil whose "
                    "own outlet lacks a setpoint")

    def test_a_setpoint_on_the_FAN_outlet_is_not_required(self):
        """The narrower half of (c), asserted so the claim stays honest.

        `both-coils` and `all-nodes` differ only by a setpoint on the fan's
        outlet. Both are clean, so that node is not a controlled one and no
        test should say it is.
        """
        import openstudio

        import btap.simulation as simulation

        without_fan_node = _two_zone_doas(openstudio, setpoints="both-coils")
        clean, severe, _fatal, detail, _err = _run(simulation,
                                                    without_fan_node)
        self.assertTrue(
            clean,
            "a DOAS with setpoints on both coil outlets and NONE on the fan "
            f"outlet must run: severe={severe} — {detail}")


def _run(simulation, model):
    """Sizing-only: `(clean, severe, fatal, first_severity_line, whole_err)`.

    The whole text as well as the first line, because EnergyPlus puts the
    EXPLANATION on a `**   ~~~   **` continuation: the first Severe line
    says which object is at fault and the next one says why. Asserting the
    reason against the first line alone fails on text that is present.

    Sizing because these are input and translation defects, refused during
    GetInput or on the design days. The verdict is deliberately narrow: no
    Severe or Fatal on the design days, which is not the same as annual
    operability.
    """
    import re
    import tempfile

    severe_re = re.compile(r"\*\*\s*Severe\s*\*\*")
    fatal_re = re.compile(r"\*\*\s*Fatal\s*\*\*")
    with tempfile.TemporaryDirectory(prefix="doas-run-") as work:
        try:
            result = simulation.run(
                model, run_dir=str(pathlib.Path(work) / "run"),
                weather={"epw": str(EPW), "ddy": str(DDY)},
                sizing_only=True)
            clean, where = result.is_clean(), pathlib.Path(result.run_dir)
        except Exception:                                     # noqa: BLE001
            # The backend RAISES on a failed run, so the evidence has to be
            # read on this path too — the same defect this repository's
            # sweep had (Sol, `234`).
            clean, where = False, pathlib.Path(work) / "run"
        err = ""
        for found in sorted(where.rglob("eplusout.err")):
            err = found.read_text(encoding="utf-8", errors="replace")
            break
        detail = ""
        for line in err.splitlines():
            if severe_re.search(line) or fatal_re.search(line):
                detail = line.strip()[:220]
                break
        return (clean, len(severe_re.findall(err)),
                len(fatal_re.findall(err)), detail, err)


if __name__ == "__main__":
    unittest.main()
