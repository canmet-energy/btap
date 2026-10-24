#!/usr/bin/env python3
"""Generate the sample .osm set the Windows package ships — the Python twin of
btap-necb/scripts/generate_samples.rb (D-80 R2.2).

    python3 scripts/generate_samples.py OUTDIR

ONE building, MANY HVAC systems. That is the point: the demo is about the
compliance pipeline's response to different mechanical systems, and holding
the envelope and loads constant makes the comparison legible.

Why not openstudio-standards archetypes, which would be more realistic:
  * they need the pinned oracle checked out (a ~4.6 GB clone) to generate, so
    nobody could regenerate these from a fresh checkout; and
  * the legacy archetypes' Kiva OS:Foundation objects currently hit an
    EnergyPlus fatal in the reference sizing run (see CLAUDE.md / Open work).
    Shipping demo files that crash would be worse than shipping simple ones.

Why not wizard geometry, which would be prettier: wizard output carries NO
constructions, and the envelope domain cannot build an opaque construction
from nothing (the one real physics gap in Open work), so apply_prescriptive
would silently skip and the reference envelope would be wrong. The shared
fixture is a real DOE prototype and carries constructions.

THE ONE DELIBERATE DIVERGENCE FROM THE RUBY — the FAIL-FAST contract. The Ruby
rescues per sample and keeps going, so a broken builder writes a SMALLER corpus
and the script still exits 0; every downstream consumer then skips the missing
slugs and passes vacuously. Here:

  * any sample that fails to build ABORTS the run, naming the slug;
  * the produced slug set is compared against the committed manifest
    (scripts/sample_manifest.json) in BOTH directions — an extra sample is as
    much a defect as a missing one;
  * every written .osm is RE-LOADED through the SDK, because model.save()
    reports nothing about whether the file it wrote can be read back; and
  * a one-line-per-sample summary is printed at the end.

This generator never simulates — it is SDK-only.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PYTHON_ROOT = HERE.parent
sys.path.insert(0, str(PYTHON_ROOT))  # runnable from anywhere
REPO_ROOT = PYTHON_ROOT.parent

MANIFEST = HERE / "sample_manifest.json"

# One per family where the family is distinct enough to be worth a file, chosen
# to span fuel types and delivery types rather than to be exhaustive: 102 systems
# would be a test suite, not a sample set.
SAMPLES = (
    ("01-baseboard-gas",        "Baseboard gas boiler"),
    ("02-psz-gas-dx",           "PSZ RTU Gas and DX Coils and Hot Water Baseboard"),
    ("03-vav-reheat-chiller",   "MZ BU RTU Electric Heating Coil Scroll Chiller and Electric Baseboard"),
    ("04-fancoil-chiller",      "FPFC MAU DX Coils with Scroll Chiller"),
    ("05-ptac-electric",        "PTAC with baseboard electric"),
    ("06-unit-heaters-gas",     "Gas unit heaters"),
    ("07-furnace-forced-air",   "Forced air furnace"),
    ("08-vrf",                  "VRF"),
    ("09-water-source-hp",      "Water source heat pumps"),
    ("10-ashp-pthp",            "hs11_ashp_pthp"),
)

# The staged mixed-fuel plants, built by hand because no single catalog name
# produces a two-boiler set on two different fuels.
STAGED = (
    ("11-staged-boilers-gas-lead",      "NaturalGas", "Electricity"),
    ("12-staged-boilers-electric-lead", "Electricity", "NaturalGas"),
)

STAGED_NOTE = ("8.4.4.9.(5)/8.4.4.10.(4) multi-energy capacity ratios (a DECLARED gap: "
               "the reference keeps the mixed-fuel plant unchanged)")


def _two_storeys(model):
    model.getBuilding().setStandardsNumberOfAboveGroundStories(2)


def _three_storeys(model):
    model.getBuilding().setStandardsNumberOfAboveGroundStories(3)


def _corner_block_above_four_storeys(model):
    """Five storeys AND a zone with exposure on two orientations.

    BOTH are needed, and only the pair reaches Table 8.4.x.7.-B Note (3)'s
    ambiguity (AHJ-10). `VAVReheat._zone_groups` records its grouping evidence
    only above four storeys — at or below, every above-grade zone goes into one
    group and there is no facade election to question. And the shared
    `5ZoneNoHVAC` fixture has four perimeter zones each facing exactly ONE
    way, so raising the storey count alone yields evidence with no corner in
    it: measured S 152, W 76, N 152, E 76, core none.

    Merging the W zone into the S zone makes ONE block exposed on two
    facades, which is exactly the case Note (3) does not decide: it says
    blocks are "grouped together based on facade orientation" and supplies
    neither the metric nor the tie-break. D-18 elects the largest exterior
    wall area, so this block takes S (152 > 76) and the choice is audited.
    """
    model.getBuilding().setStandardsNumberOfAboveGroundStories(5)
    zones = {zone.nameString(): zone for zone in model.getThermalZones()}
    keep, merge = zones.get("Thermal Zone 1"), zones.get("Thermal Zone 2")
    if keep is None or merge is None:
        raise SystemExit("corner sample: the fixture's zone names have moved")
    for space in list(merge.spaces()):
        space.setThermalZone(keep)
    merge.remove()


def _humidified(model):
    """Proposed humidification WITH a determinable control.

    Table 8.4.x.7.-B Note (1) governs the energy SOURCE once humidification is
    present in the reference; it does not say whether reference humidification
    is added at all (AHJ-12). No other sample carries a humidifier, and
    `btap.modeling` builds none, so this is the only shape that reaches the
    question.

    The humidistat matters as much as the humidifier. Without one the capture
    finds no determinable control and refuses to rebuild, which exercises only
    the REFUSAL branch — a witness to the wrong half. With a humidistat on one
    served zone, this model reaches BOTH: the rebuild decision for that zone's
    loop and the refusal for the zonally-served remainder.
    """
    import openstudio  # local, as everywhere else in this script

    loops = sorted(model.getAirLoopHVACs(), key=lambda loop: loop.nameString())
    if not loops:
        raise SystemExit("humidified sample: the catalog system built no air loop")
    loop = loops[0]
    humidifier = openstudio.model.HumidifierSteamElectric(model)
    humidifier.setName("Proposed Steam Humidifier")
    if not humidifier.addToNode(loop.supplyOutletNode()):
        raise SystemExit("humidified sample: the humidifier would not attach")
    schedule = openstudio.model.ScheduleRuleset(model)
    schedule.setName("Min Relative Humidity 30")
    schedule.defaultDaySchedule().addValue(openstudio.Time(0, 24, 0, 0), 30.0)
    humidistat = openstudio.model.ZoneControlHumidistat(model)
    humidistat.setHumidifyingRelativeHumiditySetpointSchedule(schedule)
    served = sorted(loop.thermalZones(), key=lambda zone: zone.nameString())
    if not served:
        raise SystemExit("humidified sample: the air loop serves no thermal block")
    served[0].setZoneControlHumidistat(humidistat)

    # AND the outlet setpoint manager, without which this sample CANNOT BE
    # SIMULATED. A humidistat alone satisfies the reference-side capture — the
    # SDK-only path builds and audits fine — but EnergyPlus fatals in the
    # PROPOSED sizing run:
    #
    #   Severe  Humidifiers: Missing humidity setpoint for
    #           Humidifier:Steam:Electric = PROPOSED STEAM HUMIDIFIER
    #           use a Setpoint Manager with Control Variable =
    #           "MinimumHumidityRatio"
    #   Fatal   Previous severe set point errors cause program termination
    #
    # So the first version of this sample was unsimulable and nothing caught
    # it, because the reference path never runs the engine (Sol, `181`).
    # `test_hvac_necb_humidification.py` already held the valid construction.
    outlet = humidifier.outletModelObject()
    if not outlet.is_initialized():
        raise SystemExit("humidified sample: the humidifier has no outlet node")
    manager = openstudio.model.SetpointManagerSingleZoneHumidityMinimum(model)
    manager.setControlZone(served[0])
    if not manager.addToNode(outlet.get().to_Node().get()):
        raise SystemExit("humidified sample: the setpoint manager would not attach")


#: Runs AFTER the catalog system is built: there is no air loop to humidify
#: before that.
_humidified.after_build = True


# Cases chosen to make the REFERENCE-BUILDING logic visibly do something, rather
# than to cover another system. Each names the article it exercises, and the
# optional callable is model-level setup the plain SAMPLES tuple cannot express.
#
#   (slug, catalog system, article + what to look for, setup(model) | None)
def _ground_f_factor(model):
    """A ground floor submitted on the F-factor method.

    NO other sample carries a whole-foundation method other than simple
    `Ground`, and the frozen corpus therefore never selected the branch where
    BTAP has no validated NECB reference applier at all.

    What this sample covers, exactly: the branch SELECTION and the
    `no_determination` emission. Its factor floor is `ordinary` and the seed's
    four other ground floors keep the ordinary list non-empty, so it does NOT
    exercise the embedded or all-embedded routes that the two silent-verdict
    defects of 9454b902 lived on — Fable witnessed both reverts leaving this
    scenario green (`303`). Sample 22 is the one shaped for those.

    `Construction:FfactorGroundFloor` carries no layers: EnergyPlus derives an
    effective U from F, area and exposed perimeter, soil and both films
    included. That is why it cannot be reconciled with NECB's assembly U by
    unit inspection alone, and why the reference applier is still open work.
    F = 1.26 W/m-K is an uninsulated unheated slab, and the area and exposed
    perimeter are the floor's own measured values, so the sample simulates
    coherently rather than merely parsing.

    The run emits NO determination (`compliant = null`, exit 6) by design.
    That is the disclosure under 8.4.1.1.(1), not a failure of the sample.
    """
    import openstudio  # local, as everywhere else in this script

    from btap._compat import sorted_by_name
    from btap.modeling.envelope import foundations

    grounds = [s for s in sorted_by_name(model.getSurfaces())
               if s.surfaceType() == "Floor"
               and s.outsideBoundaryCondition() == "Ground"]
    if not grounds:
        raise SystemExit("f-factor sample: the seed has no simple-Ground floor")

    floor = grounds[0]
    # MEASURED, not assumed. `4*sqrt(area)` treats every floor as a square:
    # Surface 1 is a perimeter-zone trapezoid whose total perimeter is 43.8 m
    # and whose EXPOSED edge is 20.0 m, so the square assumption declared
    # 33.6 m and overstated slab edge loss by 68% against the sample's own
    # geometry. EnergyPlus derives the slab U from F*P/A, so that is a physics
    # error, not a cosmetic one. Measured here while the floor is still simple
    # `Ground`, because that is what `exposed_perimeters` reads. Fable's `303`.
    perimeter = foundations.exposed_perimeters(
        model, [floor])["perimeters"][floor.nameString()]
    construction = openstudio.model.FFactorGroundFloorConstruction(model)
    construction.setName("Slab-on-grade F-factor construction")
    construction.setFFactor(1.26)
    construction.setArea(floor.grossArea())
    construction.setPerimeterExposed(perimeter)
    floor.setConstruction(construction)
    floor.setOutsideBoundaryCondition("GroundFCfactorMethod")


def _ground_f_factor_all_non_ordinary(model):
    """Every ground floor non-ordinary, the F-factor floor among them.

    Sample 21 covers the branch selection; this covers the two routes the
    silent-verdict defects of `9454b902` actually lived on, both of which
    needed the ORDINARY list to be empty or the limitation to be built from it:

    - `method_limits` built from the ordinary floors only, which dropped a
      non-ordinary factor floor entirely;
    - `if not floors: return` running before the only remaining record site,
      which dropped the limitation for a model with no ordinary ground floor.

    Fable witnessed both reverts leaving sample 21 GREEN and this shape
    catching both (`303`).

    A factor floor can NEVER be `embedded`: `Construction:FfactorGroundFloor`
    carries no layers, so it cannot be a `ConstructionWithInternalSource` and
    no radiant unit resolves it. It reaches `unresolved` instead, through a
    floor-radiant unit on its zone that names no surfaces. The other four
    ground floors take a genuine internal-source construction and are
    `embedded`. So this is a PIPELINE-level shape — the statuses are what the
    inventory derives, not a slab anyone pours — and it is here to hold the
    inventory's branches, not to teach a construction detail.

    The radiant unit must hold the LAST equipment priority, which takes the
    priority calls below AND `after_build = True`. An earlier version of this
    docstring claimed the sample could not simulate and that this was inherent
    and unfixable. It is neither: it sizes and runs a full year with zero
    Severes and `unresolved` intact. The claim came from testing the wrong
    knob — detaching the unit, which changes the status — and from a priority
    call that was a silent no-op because the mutator ran before the catalog
    system existed (Fable, `304`).

    No IDF carries the radiant unit either way — the translator always drops a
    surface-less one — so `unresolved` is a status the OSM asserts and the
    simulation never sees. That is what makes this a pipeline-level shape, and
    it is why the simulated result is a valid NECB run rather than a model of
    a radiant floor.
    """
    import openstudio  # local, as everywhere else in this script

    from btap._compat import sorted_by_name
    from btap.modeling.envelope import foundations

    grounds = [s for s in sorted_by_name(model.getSurfaces())
               if s.surfaceType() == "Floor"
               and s.outsideBoundaryCondition() == "Ground"]
    if len(grounds) < 2:
        raise SystemExit(
            "all-non-ordinary f-factor sample: the seed needs several "
            "simple-Ground floors, so that the ORDINARY list ends up empty")

    factor_floor, rest = grounds[0], grounds[1:]

    # The others: genuinely embedded. The insulation layer is required — the
    # reference applier raises "no insulation layer identifiable" on a
    # single-layer slab, so a bare internal-source construction would make the
    # sample ungenerable rather than embedded.
    embedded = openstudio.model.ConstructionWithInternalSource(model)
    embedded.setName("Embedded slab with internal source")
    slab = openstudio.model.StandardOpaqueMaterial(
        model, "MediumRough", 0.1, 1.8, 2300, 900)
    insulation = openstudio.model.StandardOpaqueMaterial(
        model, "Smooth", 0.05, 0.035, 30, 1200)
    insulation.setName("Embedded slab insulation")
    embedded.setLayers([slab, insulation])
    embedded.setSourcePresentAfterLayerNumber(1)
    embedded.setTemperatureCalculationRequestedAfterLayerNumber(1)
    for surface in rest:
        surface.setConstruction(embedded)

    # The factor floor: measured first, as in `_ground_f_factor`.
    perimeter = foundations.exposed_perimeters(
        model, [factor_floor])["perimeters"][factor_floor.nameString()]
    construction = openstudio.model.FFactorGroundFloorConstruction(model)
    construction.setName("Slab-on-grade F-factor construction")
    construction.setFFactor(1.26)
    construction.setArea(factor_floor.grossArea())
    construction.setPerimeterExposed(perimeter)
    factor_floor.setConstruction(construction)
    factor_floor.setOutsideBoundaryCondition("GroundFCfactorMethod")

    # ...and `unresolved`, via a radiant unit that resolves no surfaces.
    radiant = openstudio.model.ZoneHVACLowTemperatureRadiantElectric(
        model, model.alwaysOnDiscreteSchedule(),
        model.alwaysOnDiscreteSchedule())
    radiant.setName("Floor radiant naming no surfaces")
    radiant.setRadiantSurfaceType("Floors")
    zone_opt = factor_floor.space().get().thermalZone()
    if not zone_opt.is_initialized():
        raise SystemExit("all-non-ordinary f-factor sample: factor floor has "
                         "no thermal zone to carry the radiant unit")
    zone = zone_opt.get()
    radiant.addToThermalZone(zone)
    # GIVE THE RADIANT UNIT THE LAST PRIORITY, or the sample does not
    # simulate. The ForwardTranslator always drops a surface-less radiant
    # unit; if it held priority 1 the surviving baseboard keeps
    # `Zone Equipment Cooling/Heating Sequence 1 = 2`, which points past the
    # end of a now one-item list, and E+ raises
    # `invalid zone_equipment_cooling_sequence=[2]` twice and then
    # `Fatal: GetZoneEquipmentData: Errors found`.
    #
    # `after_build = True` below is what makes this work, and is the whole
    # fix: run BEFORE the catalog system and the zone holds only the radiant,
    # so "last" is 1, the baseboard arrives at 2, and the ordering is exactly
    # the broken one. The priority call is not optional decoration — it is
    # also not sufficient on its own.
    #
    # It is the ORDER, not the attachment. Detaching also clears the Fatal,
    # but `_embedded_floor_inventory` skips equipment whose `thermalZone()` is
    # empty, so an unattached unit leaves the floor `ordinary` and destroys
    # the only status this sample exists to carry (Fable, `304`).
    last = len(zone.equipment())
    if not zone.setCoolingPriority(radiant, last):
        raise SystemExit("all-non-ordinary f-factor sample: could not give the "
                         "radiant unit the last cooling priority")
    if not zone.setHeatingPriority(radiant, last):
        raise SystemExit("all-non-ordinary f-factor sample: could not give the "
                         "radiant unit the last heating priority")
    # Assert the ORDER, not just that the setters returned true: the sample is
    # worthless if the surviving equipment is not first, and a silent no-op
    # here produced an exit-4 sample once already.
    order = [e.handle() for e in zone.equipmentInHeatingOrder()]
    if order and order[-1] != radiant.handle():
        raise SystemExit("all-non-ordinary f-factor sample: the radiant unit "
                         "is not last in the heating order, so dropping it "
                         "will leave a sequence gap and E+ will refuse")


# Like `_humidified`, this one needs the catalog system to EXIST first: the
# radiant unit must take the LAST equipment priority, and until the baseboard
# is built the zone holds only the radiant, so "last" is 1 and the radiant
# ends up FIRST — the translator then drops it and leaves the baseboard
# pointing at sequence 2 of a one-item list, which is the exit-4 sample.
_ground_f_factor_all_non_ordinary.after_build = True

STRESS_CASES = (
    ("13-district-heating",
     "DOAS with fan coil air-cooled chiller with district hot water",
     "8.4.4.6.(1)(a) — purchased heating: the reference grows a gas-fired boiler "
     "where the proposed has none. MUST be a single-group system: with several "
     "single-zone groups the district loop survives the per-group teardown and is "
     "adopted by name, so the article is only half-applied.",
     None),
    ("14-general-2storey",
     "Baseboard gas boiler",
     "Table 8.4.4.7.-A — General Area at 2 storeys selects reference System 3. "
     "Pairs with 15; one sample cannot show a flip.",
     _two_storeys),
    ("15-general-3storey",
     "Baseboard gas boiler",
     "Table 8.4.4.7.-A — the same building at 3 storeys crosses the threshold and "
     "selects System 6 instead.",
     _three_storeys),
    ("16-ashp-electric-supp-hw-baseboard",
     "PSZ RTU ASHP with Electric and ASHP with Electric Supp. Heat Coils and Hot Water Baseboard",
     "8.4.4.13.(2)(g) / D-52 — the auxiliary-fuel election. Needs --simulate annual: "
     "under :none it cannot run and the structural 8.4.4.9.(4) proxy answers instead. "
     "Proof that it RAN is the (g)(i) suffix on the article and the ELECTED wording, "
     "not the answer itself — this building delivers more gas (baseboard) than "
     "electric (supp coil), so the election and the proxy happen to agree on gas. "
     "A mixed-fuel heat pump is required for the election to be reachable at all; "
     "on an all-electric one there is nothing to elect between.",
     None),
    ("17-vav-hw-reheat",
     "MZ BU RTU Hot Water Heating Coil Scroll Chiller and Electric Baseboard",
     "8.4.4.14/8.4.5.14 + DF-17 — the CATALOG-authored hydronic VAV, a common "
     "NECB System 6: five CoilHeatingWater in VAV reheat terminals, held inside "
     "the terminals and so reached through containingHVACComponent (the "
     "served-zone traversal's third accessor), plus one bare on the air loop. "
     "(18-vav-hw-subset-reheat also carries held hot-water coils — three — so "
     "neither sample is 'the only' one that does.) Its distinction is the "
     "OUTCOME: it is the only frozen scenario where correspondence SUCCEEDS "
     "through a loop resolved by air-loop coil UNION held coils, transferring "
     "proposed_pumps=1 at 255.49 W/(L/s). 18's transfer deliberately declines; "
     "01 and 02 succeed but resolve through baseboards. So this is the positive "
     "correspondence witness on that topology. (The W/(L/s) figure itself is not "
     "unique — 13 transfers the same — the topology and the outcome are.) "
     "READ THIS BEFORE TRUSTING IT: the air loop's own heating coil is hot water "
     "too, and it contributes every zone on the loop through the SECOND accessor, "
     "so this sample's served-zone SET is the same whether the held path works or "
     "not. It witnesses the accessor's contribution; it cannot DETECT its "
     "absence. 18-vav-hw-subset-reheat is the sample that does.",
     None),
    ("19-corner-block-5storey",
     "MZ BU RTU Hot Water Heating Coil Scroll Chiller and Hot Water Baseboard",
     "Table 8.4.4.7.-B Note (3) / D-18 / AHJ-10 — the ONLY sample with a block "
     "exposed on two facades, and the only one above four storeys. Both are "
     "required: grouping evidence is recorded only above four storeys, and the "
     "shared fixture's four perimeter zones each face exactly ONE way, so "
     "raising the storey count alone produces evidence with no corner in it. "
     "The merged block takes S over W by largest exterior wall area (152 vs "
     "76 m2) — a tie-break Note (3) does not supply, which is the question.",
     _corner_block_above_four_storeys),
    ("20-humidified-psz",
     "PSZ RTU Gas and DX Coils and Hot Water Baseboard",
     "Table 8.4.4.7.-B Note (1) / D-55 / AHJ-12 — the ONLY sample carrying "
     "humidification; `btap.modeling` builds none, so no other shape reaches "
     "the question of whether reference humidification is added at all. The "
     "humidistat is as load-bearing as the humidifier: without one the capture "
     "finds no determinable control and only the REFUSAL branch runs. With one "
     "on a single served zone this model reaches BOTH branches — the rebuild "
     "for that loop and the refusal for the zonally-served remainder.",
     _humidified),
    ("21-ground-f-factor",
     "Baseboard gas boiler",
     "8.4.1.1.(1)/D-32 — a ground floor on `GroundFCfactorMethod`, the one "
     "whole-foundation method with no validated NECB reference applier. The "
     "run emits NO determination rather than a verdict, and this is the only "
     "sample reaching that branch with an ORDINARY factor floor: it covers "
     "the selection and the refusal, not the embedded routes sample 22 "
     "carries.",
     _ground_f_factor),
    ("22-ground-f-factor-all-non-ordinary",
     "Baseboard gas boiler",
     "8.4.1.1.(1)/D-32 — every ground floor non-ordinary with the F-factor "
     "floor among them, so the ORDINARY list is EMPTY. The two routes "
     "9454b902's silent-verdict defects lived on; sample 21 stays green under "
     "both reverts and this one does not. The floor-radiant unit takes the "
     "last equipment priority, so the model still sizes and runs a full year "
     "cleanly once the translator drops it.",
     _ground_f_factor_all_non_ordinary),
)

#: DF-17's discriminating sample, and the reason it is hand-built rather than
#: named from the catalog: no catalog row produces a hydronic loop reached ONLY
#: through held coils. All 97 were swept — 64 carry a hydronic loop, 138 loops,
#: none sensitive to either PR #53 defect — because every hydronic VAV takes one
#: `heating_coil_type` for the air-loop coil AND the reheat coils, and that
#: air-loop coil contributes every zone through the second accessor.
#:
#: Post-build surgery escapes that, exactly as 11/12 do for staged boilers:
#: take the ELECTRIC VAV (so nothing hydronic sits on the air loop), add a
#: hot-water loop, and put hot-water reheat on a STRICT SUBSET of the terminals.
#: The loop then reaches its zones only through containingHVACComponent, and
#: only for the zones it actually serves.
SUBSET_REHEAT = (
    "18-vav-hw-subset-reheat",
    "MZ BU RTU Electric Heating Coil Scroll Chiller and Electric Baseboard",
    3,
)

SUBSET_REHEAT_NOTE = (
    "8.4.4.14/8.4.5.14 + DF-17 — the sample that DISCRIMINATES a served-zone "
    "mis-attribution instead of merely exercising the traversal. Hot-water "
    "reheat on 3 of 5 VAV terminals of an otherwise all-electric system, so the "
    "hot-water loop reaches its blocks ONLY through containingHVACComponent and "
    "ONLY for the three zones it truly serves. Measured against the System 3 "
    "reference this model selects, whose hot-water BASEBOARDS resolve through "
    "the first accessor and so are untouched by either defect — it is the "
    "PROPOSED set that moves:\n"
    "      real     [Zone 1-3] -> 'shares 3 of this reference loop's 5 thermal "
    "blocks ... a partial overlap is not a correspondence'\n"
    "      round 1  []         -> 'no proposed hot_water loop serves these "
    "thermal blocks' (held accessor removed)\n"
    "      round 2  [Zone 1-5] -> 'one-to-one' (holder over-attributed to its "
    "whole air loop) — a FALSE match\n"
    "    Three different correspondence outcomes, so either defect moves this "
    "baseline. Keep the reheat a STRICT SUBSET: give every terminal a coil and "
    "the set becomes insensitive again."
)


def fixture() -> str:
    """The seed .osm, resolved from INSIDE the installed package (the Ruby
    reads the gem's copy of the same, byte-identical, file). Walking out to the
    repository would work in a checkout and silently degrade from a wheel —
    exactly the failure scripts/wheel_smoke.py exists to catch."""
    from importlib import resources

    return str(resources.files("btap.modeling.hvac") / "data" / "5ZoneNoHVAC.osm")


SUPPORTED_SYSTEM_STATUS_SCHEMA = 1


def simulatable() -> set[str]:
    """Names with a clean recorded design-day sizing run.

    `scripts/simulate_all_systems.py` records which systems completed sizing
    on the recorded DDY with zero Severe or Fatal errors. Honour that narrow
    result here so the sample set self-corrects when a system is fixed. All
    97 pass as of the defrost-curve fix; the gate stays because the next
    sizing regression should stop a sample, not ship one.

    The sweep certifies each system on the BARE fixture, not the seeded sample
    this generator ships. The humidified-PSZ incident is the live distinction:
    a sizing-clean catalogue system still produced an unsimulable sample after
    humidification was added here, so sample-specific tests remain necessary.

    The Python-owned fixture is authoritative after R6. Missing data is loud:
    silently generating every catalog system would make this gate vacuous.
    An unknown schema is equally loud: this reader may not guess what a
    future verdict shape means."""
    path = PYTHON_ROOT / "tests" / "fixtures" / "system_simulation_status.json"
    if not path.is_file():
        raise FileNotFoundError(f"missing Python system status fixture: {path}")
    verdict = json.loads(path.read_text(encoding="utf-8"))
    # The verdict gained a `produced_by` block when the sweep that writes it
    # was finally written, so the rows moved under a `systems` key. THIS
    # FUNCTION IS THE SECOND READER, and I updated only the first: CI caught
    # it as `TypeError: string indices must be integers` on a dict I was
    # iterating as a list.
    produced_by = verdict.get("produced_by")
    schema = (produced_by.get("schema_version")
              if isinstance(produced_by, dict) else None)
    if schema != SUPPORTED_SYSTEM_STATUS_SCHEMA:
        raise ValueError(
            "unsupported system simulation status schema_version "
            f"{schema!r}; expected {SUPPORTED_SYSTEM_STATUS_SCHEMA}")
    return {row["name"] for row in verdict["systems"]
            if row["status"] == "ok"}


def seed(code="necb2020"):
    """The shared proposed building: the DOE prototype fixture, NECB-tagged,
    with loads/lighting/SHW applied. Identical recipe to the Ruby's seed()."""
    from btap._sdk import load_model
    from btap.audit import AuditLog
    from btap.codes.necb import lighting, loads, shw

    model = load_model(fixture())
    # The fixture is ASHRAE-tagged; the NECB pre-flight (correctly) rejects that.
    # Tag it so the samples run with no --space-type on the command line — a demo
    # whose first step is a refusal is a bad demo.
    for st in model.getSpaceTypes():
        if st.spaces():
            st.setStandardsBuildingType("Space Function")
            st.setStandardsSpaceType("Office enclosed > 25 m2")
    audit = AuditLog()
    loads.apply_loads(model, code=code, audit=audit)
    lighting.apply_lights(model, code=code, audit=audit)
    shw.apply_shw(model, code=code, fuel="NaturalGas", audit=audit)
    return model


def save(model, out: Path, slug: str) -> int:
    import openstudio

    path = out / f"{slug}.osm"
    model.save(openstudio.path(str(path)), True)
    return path.stat().st_size


def abort(slug: str, error: BaseException) -> None:
    """The fail-fast half of the contract: name the slug, then stop. A partial
    corpus that exits 0 is the outcome this script exists to prevent."""
    print(f"  FAILED {slug}: {type(error).__name__}: {str(error)[:200]}", file=sys.stderr)
    raise SystemExit(1)


def generate(out: Path) -> list[tuple[str, str, int]]:
    import openstudio

    import btap.modeling as modeling
    from btap._compat import sorted_by_name
    from btap.modeling.hvac.systems import plant_loops

    ok = simulatable()
    out.mkdir(parents=True, exist_ok=True)
    built: list[tuple[str, str, int]] = []
    notes: dict[str, str] = {}

    def gate(slug, system):
        # The Ruby SKIPS a system outside the sizing-clean set; under the
        # fail-fast contract a skip would silently shrink the corpus.
        if system not in ok:
            print(f"  REFUSED {slug}: '{system}' is not in the sizing-clean "
                  "design-day set", file=sys.stderr)
            raise SystemExit(1)

    required = list(SAMPLES)
    required.append(SUBSET_REHEAT[:2])
    required.extend((slug, system)
                    for slug, system, _note, _setup in STRESS_CASES)
    for slug, system in required:
        gate(slug, system)

    for slug, system in SAMPLES:
        try:
            model = seed("necb2020")
            modeling.build_system(model, system, sorted_by_name(model.getThermalZones()))
            size = save(model, out, slug)
        except Exception as e:  # noqa: BLE001 - re-raised as a fatal, named
            abort(slug, e)
        built.append((slug, system, size))
        print(f"  {slug:<24} {system:<64} {size / 1_048_576.0:6.1f} MB")

    # A staged, mixed-fuel hot-water plant: lead boiler on one fuel, second stage
    # on the other, SequentialLoad so the staging is real rather than nominal.
    # Exercises 8.4.4.9.(5)/8.4.4.10.(4) multi-energy capacity ratios — a
    # DECLARED gap: the reference keeps the mixed plant unchanged. These exist as
    # evidence of that.
    for slug, lead, backup in STAGED:
        try:
            model = seed("necb2020")
            loop = plant_loops.hot_water(model, fuel=lead, backup_fuel=backup, reuse=False)
            loop.setLoadDistributionScheme("SequentialLoad")
            modeling.build_system(model, "Baseboard gas boiler",
                                  sorted_by_name(model.getThermalZones()))
            size = save(model, out, slug)
        except Exception as e:  # noqa: BLE001 - re-raised as a fatal, named
            abort(slug, e)
        built.append((slug, f"staged boilers: {lead} lead, {backup} second stage", size))
        notes[slug] = STAGED_NOTE
        print(f"  {slug:<36} {lead + ' lead / ' + backup + ' backup':<52} "
              f"{size / 1_048_576.0:6.1f} MB")

    # DF-17's discriminating sample: hot-water reheat on a STRICT SUBSET of an
    # all-electric VAV's terminals, so the loop reaches its blocks only through
    # the held-coil accessor and only for the zones it truly serves.
    slug, system, reheated = SUBSET_REHEAT
    try:
        model = seed("necb2020")
        modeling.build_system(model, system,
                              sorted_by_name(model.getThermalZones()))
        loop = plant_loops.hot_water(model, fuel="NaturalGas", reuse=False)
        terminals = sorted_by_name(model.getAirTerminalSingleDuctVAVReheats())
        if len(terminals) <= reheated:
            abort(slug, ValueError(
                f"needs more than {reheated} VAV terminals to leave a subset "
                f"unserved; found {len(terminals)}"))
        for terminal in terminals[:reheated]:
            coil = openstudio.model.CoilHeatingWater(
                model, model.alwaysOnDiscreteSchedule())
            # Both return a bool the SDK will happily let you ignore. If either
            # silently fails the sample still SAVES, and what ships is a model
            # that no longer discriminates — the exact failure this sample
            # exists to prevent (Sol, PR #54).
            if not loop.addDemandBranchForComponent(coil):
                abort(slug, ValueError(
                    f"addDemandBranchForComponent refused the reheat coil for "
                    f"{terminal.nameString()}"))
            if not terminal.setReheatCoil(coil):
                abort(slug, ValueError(
                    f"setReheatCoil refused the hot-water coil on "
                    f"{terminal.nameString()}"))
        size = save(model, out, slug)
    except Exception as e:  # noqa: BLE001 - re-raised as a fatal, named
        abort(slug, e)
    built.append((slug, f"{system} + hot-water reheat on {reheated} terminals",
                  size))
    notes[slug] = SUBSET_REHEAT_NOTE
    print(f"  {slug:<36} {'hot-water reheat on a subset':<52} "
          f"{size / 1_048_576.0:6.1f} MB")

    for slug, system, note, setup in STRESS_CASES:
        try:
            model = seed("necb2020")
            # Most setup shapes the model the system is then built ONTO —
            # storey counts, zone merges. One needs the opposite: a humidifier
            # attaches to an air loop, which does not exist until the catalog
            # system is built. `after_build` says which, explicitly, rather
            # than reordering the common case or guessing from the slug.
            after = bool(getattr(setup, "after_build", False))
            if setup is not None and not after:
                setup(model)
            modeling.build_system(model, system, sorted_by_name(model.getThermalZones()))
            if setup is not None and after:
                setup(model)
            size = save(model, out, slug)
        except Exception as e:  # noqa: BLE001 - re-raised as a fatal, named
            abort(slug, e)
        built.append((slug, system, size))
        notes[slug] = note
        print(f"  {slug:<36} {system[:52]:<52} {size / 1_048_576.0:6.1f} MB")

    write_readme(out, built, notes)
    return built


def write_readme(out: Path, built, notes) -> None:
    """The shipped README.txt, structurally identical to the Ruby heredoc
    (systems block first, then the reference-logic cases with their notes)."""
    systems = "\n".join(f"  {slug.ljust(36)} {sys}"
                        for slug, sys, _ in built if slug not in notes)
    cases = "\n".join(f"  {slug}\n    system: {sys}\n    tests:  {notes[slug]}\n"
                      for slug, sys, _ in built if slug in notes)
    text = f"""Sample models — {len(built)} files, one building
{'=' * 62}

The same 5-zone office (a DOE prototype, so it carries real constructions) in
every file. Only the mechanical system changes, so the compliance verdict moves
with the HVAC rather than with the building.

All are tagged with NECB space types already, so no --space-type is needed:

  btap-compliance samples\\01-baseboard-gas.osm --city toronto --quick

Drop --quick for a real 8.4.1.2 determination (40-90 min, four simulations).
--quick shortens the run to a week and the tool refuses to call that a verdict.

SYSTEMS — one per catalog family, spanning fuels and delivery types
{'-' * 62}
{systems}

REFERENCE-LOGIC CASES — these make the NECB rules visibly do something
{'-' * 62}
Run each with --simulate none first and read audit.txt; the interesting part is
the decision, not the energy number.

{cases}
"""
    (out / "README.txt").write_text(text, encoding="utf-8")


def expected_slugs() -> list[str]:
    return list(json.loads(MANIFEST.read_text(encoding="utf-8"))["samples"])


def verify(out: Path, built) -> list[tuple[str, str, int, int]]:
    """Both halves of the post-condition: the slug set matches the committed
    manifest in BOTH directions, and every written file loads back through the
    SDK (model.save() says nothing about whether the bytes are readable)."""
    from btap._sdk import load_model

    expected = set(expected_slugs())
    produced = {slug for slug, _, _ in built}
    on_disk = {p.stem for p in out.glob("*.osm")}
    missing = sorted(expected - produced)
    extra = sorted(produced - expected)
    stray = sorted(on_disk - produced)
    if missing or extra or stray:
        for slug in missing:
            print(f"  MISSING  {slug} — in the manifest, not produced", file=sys.stderr)
        for slug in extra:
            print(f"  EXTRA    {slug} — produced, not in the manifest", file=sys.stderr)
        for slug in stray:
            print(f"  STRAY    {slug}.osm — on disk, not produced by this run",
                  file=sys.stderr)
        raise SystemExit(1)

    rows = []
    for slug, system, size in built:
        path = out / f"{slug}.osm"
        try:
            model = load_model(path)
            zones = len(model.getThermalZones())
        except Exception as e:  # noqa: BLE001 - re-raised as a fatal, named
            print(f"  UNREADABLE {slug}.osm: {type(e).__name__}: {e}", file=sys.stderr)
            raise SystemExit(1) from None
        if zones == 0:
            print(f"  UNREADABLE {slug}.osm: reloads with no thermal zones",
                  file=sys.stderr)
            raise SystemExit(1)
        rows.append((slug, system, size, zones))
    return rows


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("outdir", help="directory the .osm samples are written to")
    args = parser.parse_args(argv)

    out = Path(args.outdir).resolve()
    built = generate(out)
    rows = verify(out, built)

    print(f"\nSUMMARY — {len(rows)} samples, all re-loaded from disk")
    for slug, system, size, zones in rows:
        print(f"  {slug:<36} {system[:60]:<60} {size / 1_048_576.0:6.1f} MB  "
              f"{zones} zones")
    print(f"\n{len(rows)} of {len(expected_slugs())} written to {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
