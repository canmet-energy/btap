"""The sample-corpus generator gate (D-80 R2.2): scripts/generate_samples.py
must produce EXACTLY the committed corpus, and every file in it must be a
readable model carrying the properties the samples exist to demonstrate.

SDK-ONLY — no EnergyPlus. The generator builds and saves models; nothing here
simulates, so the whole class runs under ``needs_sdk`` alone. It is slow for an
SDK test (18 models, built once in setUpClass and shared) because the thing
under test is the corpus, not one model.

Why the both-directions manifest assertion matters: the Ruby original rescues
per sample and keeps going, so a broken builder writes a SMALLER corpus and
still exits 0 — after which every consumer skips the missing slugs and passes
vacuously. That is the failure this file exists to make impossible.
"""

from __future__ import annotations

import importlib.util
import re
import sys
import tempfile
import unittest
from pathlib import Path

from tests.support import needs_sdk

PYTHON_ROOT = Path(__file__).resolve().parents[2]
GENERATOR = PYTHON_ROOT / "scripts" / "generate_samples.py"


def _load_generator():
    """scripts/ is not a package — load the generator by path (the same
    treatment scripts get from the CLI)."""
    sys.path.insert(0, str(PYTHON_ROOT))
    spec = importlib.util.spec_from_file_location("generate_samples", GENERATOR)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def district_count(model):
    # Same probe as test_reference_rules.py: the SDK renamed the district
    # objects across versions (DistrictHeating -> DistrictHeatingWater), so
    # match the type NAME rather than calling a version-specific getter.
    return sum(1 for o in model.modelObjects()
               if re.search("DistrictHeating", o.iddObjectType().valueName()))


@needs_sdk
class TestGenerateSamples(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.generator = _load_generator()
        cls.tmp = tempfile.TemporaryDirectory()
        cls.out = Path(cls.tmp.name) / "samples"
        cls.built = cls.generator.generate(cls.out)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def load(self, slug):
        from btap._sdk import load_model

        return load_model(self.out / f"{slug}.osm")

    def test_slug_set_equals_the_manifest_in_both_directions(self):
        expected = set(self.generator.expected_slugs())
        produced = {slug for slug, _, _ in self.built}
        on_disk = {p.stem for p in self.out.glob("*.osm")}

        self.assertEqual(expected, produced,
                         "the produced slug set must equal the committed manifest "
                         "exactly — a missing sample and an extra one are both defects")
        self.assertEqual(expected, on_disk,
                         "every manifest slug must exist on disk as a .osm, and nothing else")
        self.assertEqual(18, len(expected), "the corpus is 18 samples")

    def test_every_sample_reloads_through_the_sdk_with_zones(self):
        # model.save() reports nothing about whether the bytes it wrote can be
        # read back, so the only honest check is a re-load.
        for slug, _, size in self.built:
            with self.subTest(slug=slug):
                self.assertGreater(size, 0, "an empty .osm was written")
                model = self.load(slug)
                self.assertGreater(len(model.getThermalZones()), 0,
                                   f"{slug} reloaded with no thermal zones")

    def _reheat_and_coil_census(self, slug):
        """Terminal reheat fuels, and how each hot-water coil is reached."""
        import openstudio  # noqa: F401  (SDK types come back from the model)

        model = self.load(slug)
        terminals = model.getAirTerminalSingleDuctVAVReheats()
        census = {
            "terminals": len(terminals),
            "water_reheat": sum(
                1 for t in terminals
                if t.reheatCoil().to_CoilHeatingWater().is_initialized()),
            "electric_reheat": sum(
                1 for t in terminals
                if t.reheatCoil().to_CoilHeatingElectric().is_initialized()),
            "held": 0,
            "bare_on_air_loop": 0,
        }
        for coil in model.getCoilHeatingWaters():
            if coil.containingHVACComponent().is_initialized():
                census["held"] += 1
            elif coil.airLoopHVAC().is_initialized():
                census["bare_on_air_loop"] += 1
        return model, census

    def test_the_df17_pair_carries_the_topology_that_makes_18_discriminating(self):
        """DF-17's whole point is structural, so pin the structure here rather
        than only in a frozen baseline (Sol, PR #54).

        The frozen baselines are the BEHAVIOURAL gate, but they cannot protect
        the premise: if an SDK or catalog change quietly gave sample 18 a coil
        on every terminal, or put a hot-water coil back on its air loop, the
        loop's served-zone set would stop depending on the held accessor — and
        the next re-freeze would bless a sample that no longer discriminates,
        with every test still green. This fails first instead.
        """
        from btap.codes.necb.hvac import efficiency

        model17, c17 = self._reheat_and_coil_census("17-vav-hw-reheat")
        self.assertEqual(
            {"terminals": 5, "water_reheat": 5, "electric_reheat": 0,
             "held": 5, "bare_on_air_loop": 1}, c17,
            "17 is the catalog hydronic VAV: hot water on every terminal AND a "
            "bare air-loop coil, which is exactly why it cannot discriminate")

        model18, c18 = self._reheat_and_coil_census("18-vav-hw-subset-reheat")
        self.assertEqual(
            {"terminals": 5, "water_reheat": 3, "electric_reheat": 2,
             "held": 3, "bare_on_air_loop": 0}, c18,
            "18 must keep hot-water reheat on a STRICT SUBSET and nothing "
            "hydronic on the air loop, or the held accessor stops being the "
            "only route to its zones")

        def hot_water_loop(model):
            loops = [loop for loop in model.getPlantLoops()
                     if efficiency._loop_role(loop) == "hot_water"]
            self.assertEqual(1, len(loops), "expected exactly one hot-water loop")
            return loops[0]

        self.assertEqual(
            {"Thermal Zone 1", "Thermal Zone 2", "Thermal Zone 3"},
            efficiency._served_zone_names(hot_water_loop(model18)),
            "18's hot-water loop must reach ONLY the three zones it serves — "
            "all five means the subset premise is gone")
        self.assertEqual(
            5, len(efficiency._served_zone_names(hot_water_loop(model17))),
            "17's loop reaches every zone through its bare air-loop coil; that "
            "is the masking this pair exists to contrast")

    def test_the_storey_pair_declares_the_storey_counts_the_flip_needs(self):
        # Table 8.4.4.7.-A selects System 3 at 2 storeys and System 6 at 3.
        # The pair is the whole point of samples 14/15 — one sample cannot show
        # a flip — and it hangs entirely on this declared property.
        for slug, storeys in (("14-general-2storey", 2), ("15-general-3storey", 3)):
            with self.subTest(slug=slug):
                declared = self.load(slug).getBuilding() \
                    .standardsNumberOfAboveGroundStories()
                self.assertTrue(declared.is_initialized(),
                                f"{slug} must DECLARE its above-ground storeys")
                self.assertEqual(storeys, declared.get())

    def test_district_heating_sample_has_purchased_heating_and_no_boiler(self):
        # 8.4.4.6.(1)(a) is only exercisable if the PROPOSED actually carries
        # purchased heating and no boiler; the reference transform is asserted
        # in test_reference_rules.py. This pins the sample's premise.
        model = self.load("13-district-heating")
        self.assertEqual(1, district_count(model),
                         "the district-heating sample must carry exactly one "
                         "DistrictHeating object")
        self.assertEqual(0, len(model.getBoilerHotWaters()),
                         "the district-heating sample must have NO boiler — with one, "
                         "8.4.4.6.(1)(a) has nothing to replace")

    def test_the_staged_samples_carry_a_mixed_fuel_sequential_plant(self):
        # 11/12 exist as evidence of the DECLARED 8.4.4.9.(5)/8.4.4.10.(4) gap,
        # which needs TWO boilers on DIFFERENT fuels, staged rather than nominal.
        for slug in ("11-staged-boilers-gas-lead", "12-staged-boilers-electric-lead"):
            with self.subTest(slug=slug):
                model = self.load(slug)
                fuels = {b.fuelType() for b in model.getBoilerHotWaters()}
                self.assertIn("NaturalGas", fuels)
                self.assertIn("Electricity", fuels)
                self.assertIn("SequentialLoad",
                              {pl.loadDistributionScheme() for pl in model.getPlantLoops()},
                              "the staging must be real, not nominal")

    def test_the_shipped_readme_is_written(self):
        readme = (self.out / "README.txt").read_text(encoding="utf-8")
        self.assertIn("Sample models — 18 files, one building", readme)
        for slug, _, _ in self.built:
            self.assertIn(slug, readme, f"{slug} is missing from the shipped README")


if __name__ == "__main__":
    unittest.main()
