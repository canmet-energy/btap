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
# to span fuel types and delivery types rather than to be exhaustive: 97 systems
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


# Cases chosen to make the REFERENCE-BUILDING logic visibly do something, rather
# than to cover another system. Each names the article it exercises, and the
# optional callable is model-level setup the plain SAMPLES tuple cannot express.
#
#   (slug, catalog system, article + what to look for, setup(model) | None)
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
)


def fixture() -> str:
    """The seed .osm, resolved from INSIDE the installed package (the Ruby
    reads the gem's copy of the same, byte-identical, file). Walking out to the
    repository would work in a checkout and silently degrade from a wheel —
    exactly the failure scripts/wheel_smoke.py exists to catch."""
    from importlib import resources

    return str(resources.files("btap.modeling.hvac") / "data" / "5ZoneNoHVAC.osm")


def simulatable() -> set[str] | None:
    """Never ship a model that cannot simulate. The catalog sweep
    (scripts/simulate_all_systems.py / rake hvac:simulate_systems) records which
    systems produce a simulate-able model; honour it here so this list
    self-corrects when a system is fixed rather than needing a human to
    remember. All 97 pass as of the defrost-curve fix; the gate stays because
    the next regression should stop a sample, not ship one.

    The Python-owned fixture is authoritative after R6. Missing data is loud:
    returning ``None`` would silently generate every catalog system and make
    this safety gate vacuous."""
    path = PYTHON_ROOT / "tests" / "fixtures" / "system_simulation_status.json"
    if not path.is_file():
        raise FileNotFoundError(f"missing Python system status fixture: {path}")
    rows = json.loads(path.read_text(encoding="utf-8"))
    return {r["name"] for r in rows if r["status"] == "ok"}


def seed(vintage="2020"):
    """The shared proposed building: the DOE prototype fixture, NECB-tagged,
    with loads/lighting/SHW applied. Identical recipe to the Ruby's seed()."""
    from btap._sdk import load_model
    from btap.audit import AuditLog
    from btap.necb import lighting, loads, shw

    model = load_model(fixture())
    # The fixture is ASHRAE-tagged; the NECB pre-flight (correctly) rejects that.
    # Tag it so the samples run with no --space-type on the command line — a demo
    # whose first step is a refusal is a bad demo.
    for st in model.getSpaceTypes():
        if st.spaces():
            st.setStandardsBuildingType("Space Function")
            st.setStandardsSpaceType("Office enclosed > 25 m2")
    audit = AuditLog()
    loads.apply_loads(model, vintage=vintage, audit=audit)
    lighting.apply_lights(model, vintage=vintage, audit=audit)
    shw.apply_shw(model, vintage=vintage, fuel="NaturalGas", audit=audit)
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
    import btap.modeling as modeling
    from btap._compat import sorted_by_name
    from btap.modeling.hvac.systems import plant_loops

    ok = simulatable()
    out.mkdir(parents=True, exist_ok=True)
    built: list[tuple[str, str, int]] = []
    notes: dict[str, str] = {}

    def gate(slug, system):
        # The Ruby SKIPS an un-simulate-able system; under the fail-fast
        # contract a skip would silently shrink the corpus, so it is a refusal.
        if ok is not None and system not in ok:
            print(f"  REFUSED {slug}: '{system}' is not in the simulate-able set",
                  file=sys.stderr)
            raise SystemExit(1)

    for slug, system in SAMPLES:
        gate(slug, system)
        try:
            model = seed("2020")
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
            model = seed("2020")
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

    for slug, system, note, setup in STRESS_CASES:
        gate(slug, system)
        try:
            model = seed("2020")
            if setup is not None:
                setup(model)
            modeling.build_system(model, system, sorted_by_name(model.getThermalZones()))
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
