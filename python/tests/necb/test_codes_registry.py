"""Stage 0 item 0.3b (docs/NECB_MULTI_EDITION_PLAN.md): a literal
``(edition, site) -> article`` table for the 15 article-renumbering sites
surveyed across the domain modules — each a
``prefix = '8.4.5' if str(vintage) == '2025' else '8.4.4'`` ternary (or, for
``loads/apply.py``, a data-driven ``rules['schedule_table_prefix']``) that
feeds an f-string ``article=`` on an :class:`btap.audit.AuditLog` entry.

This file PINS the exact literal string each site emits for NECB 2020 and
NECB 2025 against UNMODIFIED product code — it must pass first. Stage 2 later
replaces each site's ternary with a registry/data lookup; this suite is the
guard that any one-character drift in the emitted citation fails loudly.

The 15 sites (verified against the code, not against this file's own
literals — computing the expected value the same way it is produced in
product code would be circular):

 1. ``btap/codes/compliance.py#_build_reference``                     ``prefix`` (lighting_subsection)
 2. ``btap/codes/necb/envelope/reference.py#apply``                   ``prefix``
 3. ``btap/codes/necb/hvac/efficiency.py#apply_staging``              ``prefix``
 4. ``btap/codes/necb/hvac/efficiency.py#_apply_fan_power_curve``     ``prefix``
 5. ``btap/codes/necb/hvac/efficiency.py#_apply_pump_rules``          ``prefix``
 6. ``btap/codes/necb/hvac/efficiency.py#_align_heat_pump_heating_capacity``  ``hp_article`` (heat_pump_aux_fuel)
 7. ``btap/codes/necb/hvac/reference.py#_audit_terminal_secondary_split``  ``prefix``
 8. ``btap/codes/necb/hvac/reference.py#_apply_economizers``          ``prefix``
 9. ``btap/codes/necb/hvac/reference.py#_apply_water_economizer``     ``prefix``
10. ``btap/codes/necb/hvac/reference.py#_rebuild_humidification``    ``prefix`` (Table {prefix}.7.-B)
11. ``btap/codes/necb/hvac/reference.py#_apply_dcv``                 ``prefix``
12. ``btap/codes/necb/lighting/reference.py#reference_lighting``      ``prefix`` (lighting_subsection)
13. ``btap/codes/necb/lighting/reference_daylighting.py#apply``       ``prefix`` (lighting_subsection)
14. ``btap/codes/necb/shw/reference.py#reference_shw``               ``prefix``
15. ``btap/codes/necb/loads/apply.py#_apply_ventilation``            edition-invariant citation (the
    ``schedule_table_prefix`` data key was a dead parameter, removed in Stage 2)

Since Stage 2 each ``prefix`` is ``Ruleset.from_edition(vintage).article(key)``
from the edition manifest — no ternary remains — and this table is what
proves the data says exactly what the ternaries used to.

Site 15 is a genuine finding: the ``prefix`` local in ``apply_loads`` is
threaded into ``_apply_ventilation`` as a parameter but that function's own
``article=`` f-string never references it — the emitted citation is
edition-INVARIANT today (a dead parameter). Both editions are pinned to the
same literal deliberately; if a later change makes the parameter actually
drive the citation, this table is re-pinned in the SAME commit as that
change, per house style for a deliberate count/text change.
"""

from __future__ import annotations

import tempfile
import unittest

import openstudio

from btap.audit import AuditLog
from tests.necb.support import load_raw_fixture, needs_sdk

HDD = 3890

EXPECTED = {
    ("2020", "compliance.reference_daylighting_gap"): "8.4.4.5.(9)-(12)",
    ("2025", "compliance.reference_daylighting_gap"): "8.4.5.5.(9)-(12)",

    ("2020", "envelope.reference.prescriptive"): "8.4.4.1.(2)",
    ("2025", "envelope.reference.prescriptive"): "8.4.5.1.(2)",

    ("2020", "hvac.efficiency.staging_dx_cooling"): "8.4.4.10.(8)",
    ("2025", "hvac.efficiency.staging_dx_cooling"): "8.4.5.10.(8)",

    ("2020", "hvac.efficiency.fan_power_curve"): "8.4.4.17.(2)-(5); Table 8.4.4.17.",
    ("2025", "hvac.efficiency.fan_power_curve"): "8.4.5.17.(2)-(5); Table 8.4.5.17.",

    ("2020", "hvac.efficiency.pump_riding_curve"): "8.4.4.14.(4)-(5); Table 8.4.4.14.",
    ("2025", "hvac.efficiency.pump_riding_curve"): "8.4.5.14.(4)-(5); Table 8.4.5.14.",

    ("2020", "hvac.efficiency.heat_pump_capacity_alignment"): "8.4.4.13.(2)(c)",
    ("2025", "hvac.efficiency.heat_pump_capacity_alignment"): "8.4.5.13.(2)(c)",

    ("2020", "hvac.reference.terminal_secondary_split"): "8.4.4.9.(3); 8.4.4.10.(7)",
    ("2025", "hvac.reference.terminal_secondary_split"): "8.4.5.9.(3); 8.4.5.10.(7)",

    ("2020", "hvac.reference.economizer_air"): "8.4.4.12.",
    ("2025", "hvac.reference.economizer_air"): "8.4.5.12.",

    ("2020", "hvac.reference.economizer_water"): "8.4.4.12. (Table -12 -> 5.2.2.9)",
    ("2025", "hvac.reference.economizer_water"): "8.4.5.12. (Table -12 -> 5.2.2.9)",

    ("2020", "hvac.reference.humidification"): "Table 8.4.4.7.-B Note (1)",
    ("2025", "hvac.reference.humidification"): "Table 8.4.5.7.-B Note (1)",

    ("2020", "hvac.reference.dcv"): "8.4.4.15.(2)",
    ("2025", "hvac.reference.dcv"): "8.4.5.15.(2)",

    ("2020", "lighting.reference.part4_allowance"): "8.4.4.5.(1)",
    ("2025", "lighting.reference.part4_allowance"): "8.4.5.5.(1)",

    ("2020", "lighting.reference_daylighting.reflectances"): "8.4.4.5.(10)(b)",
    ("2025", "lighting.reference_daylighting.reflectances"): "8.4.5.5.(10)(b)",

    ("2020", "shw.reference.identical_to_proposed"): "8.4.4.20.(1)",
    ("2025", "shw.reference.identical_to_proposed"): "8.4.5.20.(1)",

    ("2020", "loads.apply.ventilation"): "8.4.3.2.(1)-(2); OA basis ASHRAE 62.1-2016 Table 6-1",
    ("2025", "loads.apply.ventilation"): "8.4.3.2.(1)-(2); OA basis ASHRAE 62.1-2016 Table 6-1",
}

SITE_IDS = sorted({site for _edition, site in EXPECTED})


def tagged_space_type(model, building_type, space_type):
    """A bare SpaceType tagged with real NECB catalog names, no spaces attached
    — the minimal fixture the lighting-reference sites need."""
    st = openstudio.model.SpaceType(model)
    st.setName(f"{building_type} {space_type}")
    st.setStandardsBuildingType(building_type)
    st.setStandardsSpaceType(space_type)
    return st


def windowed_office_model(vintage):
    """A raw-fixture proposed model tagged office-everywhere, windowed, with
    lights applied — the minimal fixture reference_daylighting needs (ported
    from tests/necb/test_lighting_reference_daylighting.py's helper)."""
    from btap.codes.necb import lighting, loads

    model = load_raw_fixture()
    map_ = {s.nameString(): ["Space Function", "Office enclosed > 25 m2"]
            for s in model.getSpaces()}
    loads.assign_space_types(model, map_, vintage=vintage)
    for w in model.getSurfaces():
        if w.outsideBoundaryCondition() == "Outdoors" and w.surfaceType() == "Wall":
            w.setWindowToWallRatio(0.4)
    lighting.apply_lights(model, vintage=vintage)
    return model


def find_entry(entries, predicate):
    return next((e for e in entries if predicate(e)), None)


@needs_sdk
class TestCodesRegistry(unittest.TestCase):
    """One test per site: build the minimal fixture, run the site's real
    product code path with a fresh AuditLog, find the entry it emits, and
    assert its ``article`` against the EXPECTED literal table above."""

    def test_expected_table_is_complete(self):
        self.assertEqual(15, len(SITE_IDS), "15 sites surveyed")
        self.assertEqual(30, len(EXPECTED), "15 sites x 2 editions")
        for site in SITE_IDS:
            self.assertIn(("2020", site), EXPECTED, site)
            self.assertIn(("2025", site), EXPECTED, site)

    # ---- 1. compliance.py:321 prefix (consumed at 342/347/355/358) ----
    def test_compliance_reference_daylighting_gap(self):
        from btap.codes import performance_compliance
        from tests.necb.support import proposed_with_hvac, zone_types_for

        site = "compliance.reference_daylighting_gap"
        for edition in ("2020", "2025"):
            with self.subTest(edition=edition):
                building = {"storeys": 1, "zone_types": zone_types_for(load_raw_fixture()),
                           "winter_design_temp_c": -20}
                result = performance_compliance(
                    proposed_with_hvac(), vintage=edition, simulate="none", hdd=HDD,
                    building=building,
                    run_dir=tempfile.mkdtemp(prefix="codes-registry-compliance-"))
                entry = find_entry(
                    result.audit.entries,
                    lambda e: e.get("step") == "compliance"
                    and "D-51" in str(e.get("ruling") or "")
                    and e.get("building") == "reference building")
                self.assertIsNotNone(entry, f"{edition}: D-51 reference-daylighting decision emitted")
                self.assertEqual(EXPECTED[(edition, site)], entry["article"])

    # ---- 2. envelope/reference.py:57 prefix (consumed at :66 prescriptive) ----
    def test_envelope_reference_prescriptive(self):
        from btap.codes.necb import envelope

        site = "envelope.reference.prescriptive"
        for edition in ("2020", "2025"):
            with self.subTest(edition=edition):
                model = load_raw_fixture()
                audit = AuditLog()
                envelope.reference_envelope(model, vintage=edition, hdd=HDD, audit=audit)
                entry = find_entry(
                    audit.entries,
                    lambda e: e["action"] == "reference envelope meets prescriptive Section 3.2")
                self.assertIsNotNone(entry, f"{edition}: prescriptive Section 3.2 decision emitted")
                self.assertEqual(EXPECTED[(edition, site)], entry["article"])

    # ---- 3. hvac/efficiency.py:280 prefix (apply_staging, DX cooling) ----
    def test_hvac_efficiency_staging_dx_cooling(self):
        import btap.modeling as modeling
        from btap.codes.necb import hvac
        from btap.codes.necb.hvac import efficiency
        from btap.modeling.hvac.components import coils
        from tests.necb.hvac_helpers import load_fixture, sorted_zones

        site = "hvac.efficiency.staging_dx_cooling"
        gas_psz = "PSZ RTU Gas and DX Coils and Electric Baseboard"
        for edition in ("2020", "2025"):
            with self.subTest(edition=edition):
                model = load_fixture()
                zones = sorted_zones(model)
                modeling.build_system(model, gas_psz, zones, control_zone=zones[0],
                                      config={"staged_coils": True})
                unitary = model.getAirLoopHVACUnitarySystems()[0]
                coil = coils.multispeed(unitary.coolingCoil())
                n = len(coil.stages())
                for i, s in enumerate(coil.stages()):
                    s.setGrossRatedTotalCoolingCapacity(100_000.0 * (i + 1) / n)
                audit = AuditLog()
                efficiency.apply_staging(model, hvac.rules(edition), edition, audit)
                entry = find_entry(
                    audit.entries,
                    lambda e: e["action"].startswith("DX cooling modelled as"))
                self.assertIsNotNone(entry, f"{edition}: DX cooling staging decision emitted")
                self.assertEqual(EXPECTED[(edition, site)], entry["article"])

    # ---- 4. hvac/efficiency.py:547 prefix (VAV fan power curve) ----
    def test_hvac_efficiency_fan_power_curve(self):
        from btap.codes.necb.hvac import efficiency

        site = "hvac.efficiency.fan_power_curve"
        for edition in ("2020", "2025"):
            with self.subTest(edition=edition):
                model = openstudio.model.Model()
                always_on = model.alwaysOnDiscreteSchedule()
                fan = openstudio.model.FanVariableVolume(model, always_on)
                fan.setMaximumFlowRate(2.0)
                fan.setPressureRise(1000.0)
                fan.setFanTotalEfficiency(0.6)
                audit = AuditLog()
                efficiency.apply(model, vintage=edition, audit=audit)
                entry = find_entry(audit.entries, lambda e: "VAV fan power curve set" in e["action"])
                self.assertIsNotNone(entry, f"{edition}: VAV fan power curve decision emitted")
                self.assertEqual(EXPECTED[(edition, site)], entry["article"])

    # ---- 5. hvac/efficiency.py:572 prefix (hydronic pump riding-curve) ----
    def test_hvac_efficiency_pump_riding_curve(self):
        from btap.codes.necb.hvac import efficiency

        site = "hvac.efficiency.pump_riding_curve"
        for edition in ("2020", "2025"):
            with self.subTest(edition=edition):
                model = openstudio.model.Model()
                loop_ = openstudio.model.PlantLoop(model)
                pump = openstudio.model.PumpVariableSpeed(model)
                pump.addToNode(loop_.supplyInletNode())
                pump.setRatedFlowRate(0.5)
                loop_.sizingPlant().setLoopType("Heating")
                audit = AuditLog()
                efficiency.apply(model, vintage=edition, audit=audit)
                entry = find_entry(audit.entries,
                                   lambda e: "riding its curve" in e["action"])
                self.assertIsNotNone(entry, f"{edition}: pump riding-curve decision emitted")
                self.assertEqual(EXPECTED[(edition, site)], entry["article"])

    # ---- 6. hvac/efficiency.py:845 hp_article (single-speed heat pump alignment) ----
    def test_hvac_efficiency_heat_pump_capacity_alignment(self):
        from btap.codes.necb.hvac import efficiency

        site = "hvac.efficiency.heat_pump_capacity_alignment"
        for edition in ("2020", "2025"):
            with self.subTest(edition=edition):
                model = openstudio.model.Model()
                loop_ = openstudio.model.AirLoopHVAC(model)
                cool = openstudio.model.CoilCoolingDXSingleSpeed(model)
                heat = openstudio.model.CoilHeatingDXSingleSpeed(model)
                cool.addToNode(loop_.supplyOutletNode())
                heat.addToNode(loop_.supplyOutletNode())
                cool.setRatedTotalCoolingCapacity(12_000.0)
                heat.setRatedTotalHeatingCapacity(5_000.0)
                audit = AuditLog()
                efficiency.apply(model, vintage=edition, audit=audit)
                entry = find_entry(audit.entries,
                                   lambda e: "pinned to cooling capacity" in e["action"]
                                   and "staged" not in e["action"])
                self.assertIsNotNone(entry, f"{edition}: heat-pump capacity alignment decision emitted")
                self.assertEqual(EXPECTED[(edition, site)], entry["article"])

    # ---- 7. hvac/reference.py:607 prefix (terminal/secondary capacity split) ----
    def test_hvac_reference_terminal_secondary_split(self):
        from btap.codes.necb.hvac import reference

        site = "hvac.reference.terminal_secondary_split"
        for edition in ("2020", "2025"):
            with self.subTest(edition=edition):
                model = openstudio.model.Model()
                zone = openstudio.model.ThermalZone(model)
                zone.sizingZone().setAccountforDedicatedOutdoorAirSystem(True)
                audit = AuditLog()
                reference._audit_terminal_secondary_split([zone], 1, edition, audit)
                entry = find_entry(
                    audit.entries,
                    lambda e: e["action"] == "terminal/secondary capacity split accounted at zone sizing")
                self.assertIsNotNone(entry, f"{edition}: terminal/secondary split decision emitted")
                self.assertEqual(EXPECTED[(edition, site)], entry["article"])

    # ---- 8. hvac/reference.py:929 prefix (air economizer, system 1 exemption) ----
    def test_hvac_reference_economizer_air(self):
        from btap.codes.necb.hvac import reference

        site = "hvac.reference.economizer_air"
        for edition in ("2020", "2025"):
            with self.subTest(edition=edition):
                model = openstudio.model.Model()
                audit = AuditLog()
                reference._apply_economizers(model, [], 1, edition, {}, audit)
                entry = find_entry(
                    audit.entries,
                    lambda e: "economizer not applicable" in e["action"])
                self.assertIsNotNone(entry, f"{edition}: System 1 economizer-exempt info emitted")
                self.assertEqual(EXPECTED[(edition, site)], entry["article"])

    # ---- 9. hvac/reference.py:996 prefix (water economizer) ----
    def test_hvac_reference_economizer_water(self):
        from btap.codes.necb.hvac import reference

        site = "hvac.reference.economizer_water"
        for edition in ("2020", "2025"):
            with self.subTest(edition=edition):
                model = openstudio.model.Model()
                audit = AuditLog()
                reference._apply_water_economizer(model, 2, edition, {"water_economizer": {}}, audit)
                entry = find_entry(
                    audit.entries,
                    lambda e: "5.2.2.9 water economizer" in e["action"])
                self.assertIsNotNone(entry, f"{edition}: no-chilled-water-loop water economizer warn emitted")
                self.assertEqual(EXPECTED[(edition, site)], entry["article"])

    # ---- 10. hvac/reference.py:1220 table/article (humidification) ----
    def test_hvac_reference_humidification(self):
        from btap.codes.necb.hvac import reference

        site = "hvac.reference.humidification"
        for edition in ("2020", "2025"):
            with self.subTest(edition=edition):
                model = openstudio.model.Model()
                captured = {"Zone1": {"air_loop": "AHU1", "kind": "gas",
                                      "name": "Humidifier1", "scheduled_setpoint": None}}
                audit = AuditLog()
                reference._rebuild_humidification(model, captured, {"humidification": {}}, edition, audit)
                entry = find_entry(
                    audit.entries,
                    lambda e: "NO reference loop to carry" in e["action"])
                self.assertIsNotNone(entry, f"{edition}: orphaned-humidification warn emitted")
                self.assertEqual(EXPECTED[(edition, site)], entry["article"])

    # ---- 11. hvac/reference.py:1351 prefix (demand-controlled ventilation) ----
    def test_hvac_reference_dcv(self):
        from btap.codes.necb.hvac import reference

        site = "hvac.reference.dcv"
        for edition in ("2020", "2025"):
            with self.subTest(edition=edition):
                model = openstudio.model.Model()
                air_loop = openstudio.model.AirLoopHVAC(model)
                oa_controller = openstudio.model.ControllerOutdoorAir(model)
                oa_system = openstudio.model.AirLoopHVACOutdoorAirSystem(model, oa_controller)
                oa_system.addToNode(air_loop.supplyInletNode())
                audit = AuditLog()
                reference._apply_dcv([air_loop], [], {}, edition, audit)
                entry = find_entry(
                    audit.entries,
                    lambda e: "no demand-controlled ventilation" in e["action"])
                self.assertIsNotNone(entry, f"{edition}: no-DCV info emitted")
                self.assertEqual(EXPECTED[(edition, site)], entry["article"])

    # ---- 12. lighting/reference.py:40 prefix (Part 4 allowance) ----
    def test_lighting_reference_part4_allowance(self):
        from btap.codes.necb import lighting

        site = "lighting.reference.part4_allowance"
        for edition in ("2020", "2025"):
            with self.subTest(edition=edition):
                model = openstudio.model.Model()
                tagged_space_type(model, "Space Function", "Office enclosed > 25 m2")
                audit = AuditLog()
                lighting.reference_lighting(model, vintage=edition, audit=audit)
                entry = find_entry(
                    audit.entries,
                    lambda e: "Part 4 allowance" in e["action"])
                self.assertIsNotNone(entry, f"{edition}: Part 4 allowance decision emitted")
                self.assertEqual(EXPECTED[(edition, site)], entry["article"])

    # ---- 13. lighting/reference_daylighting.py:60 prefix (reflectances) ----
    def test_lighting_reference_daylighting_reflectances(self):
        from btap.codes.necb import lighting

        site = "lighting.reference_daylighting.reflectances"
        for edition in ("2020", "2025"):
            with self.subTest(edition=edition):
                proposed = windowed_office_model(edition)
                reference = proposed.clone(True).to_Model()
                audit = AuditLog()
                lighting.reference_daylighting(reference, vintage=edition, placement="all", audit=audit)
                entry = find_entry(
                    audit.entries,
                    lambda e: "reflectances set" in e["action"])
                self.assertIsNotNone(entry, f"{edition}: reference reflectances decision emitted")
                self.assertEqual(EXPECTED[(edition, site)], entry["article"])

    # ---- 14. shw/reference.py:22 prefix (identical-to-proposed) ----
    def test_shw_reference_identical_to_proposed(self):
        from btap.codes.necb import shw

        site = "shw.reference.identical_to_proposed"
        for edition in ("2020", "2025"):
            with self.subTest(edition=edition):
                model = openstudio.model.Model()
                audit = AuditLog()
                shw.reference_shw(model, vintage=edition, audit=audit)
                entry = find_entry(
                    audit.entries,
                    lambda e: e["step"] == "shw_reference"
                    and "identical to" in e["action"])
                self.assertIsNotNone(entry, f"{edition}: SWH identical-to-proposed info emitted")
                self.assertEqual(EXPECTED[(edition, site)], entry["article"])

    # ---- 15. loads/apply.py:78 rules['schedule_table_prefix'] (ventilation) ----
    def test_loads_apply_ventilation(self):
        from btap.codes.necb import loads

        site = "loads.apply.ventilation"
        for edition in ("2020", "2025"):
            with self.subTest(edition=edition):
                model = openstudio.model.Model()
                tagged_space_type(model, "Space Function", "Office enclosed > 25 m2")
                audit = AuditLog()
                loads.apply_loads(model, vintage=edition, audit=audit)
                entry = find_entry(
                    audit.entries,
                    lambda e: e["action"] == "ventilation outdoor air set")
                self.assertIsNotNone(entry, f"{edition}: ventilation outdoor air info emitted")
                self.assertEqual(EXPECTED[(edition, site)], entry["article"])


if __name__ == "__main__":
    unittest.main()
