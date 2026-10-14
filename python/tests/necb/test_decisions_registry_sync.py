"""The decision sources are canonical; three outputs are generated from them.

One decision is one file, ``docs/decisions/D-NN.md``. This module gates the
repository's actual state: that every source parses, that the three generated
artifacts (the registry, the decision log and the Codes Committee provision
view) are in step with the sources, and that none of them has been
hand-edited. The generator's own behaviour -- its parser, its TOML writer, its
validation and its rendering of the provision view -- is exercised in
``test_decisions_generator.py``.

The registry is schema 2. Every entry keeps the ``id``, ``title``, ``kind``
and ``summary`` the runtime reads; a legacy entry is its front matter, and a
structured one projects ``requirements`` with an ``editions`` derived from
its governing sources. The expected projections here are computed from the
sources directly, not by the generator, and a structured decision is run end
to end beside the committed tree.
"""

from __future__ import annotations

import contextlib
import hashlib
import io
import json
import re
import shutil
import subprocess
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path
from unittest import mock

PYTHON_ROOT = Path(__file__).resolve().parent.parent.parent
REPO_ROOT = PYTHON_ROOT.parent

sys.path.insert(0, str(PYTHON_ROOT / "scripts"))
import generate_decisions as G  # noqa: E402

# G put this checkout's python/ first on sys.path.
import btap.codes as codes  # noqa: E402
from btap.codes import decisions as Loader  # noqa: E402

PYTHON_REGISTRY = PYTHON_ROOT / "btap" / "codes" / "data" / "decisions.json"
DECISIONS_DOC = REPO_ROOT / "docs" / "necb_decisions.md"
PROVISION_VIEW = REPO_ROOT / "docs" / "CODE_DECISIONS_BY_PROVISION.md"
SOURCE_DIR = REPO_ROOT / "docs" / "decisions"
SCRIPT = PYTHON_ROOT / "scripts" / "generate_decisions.py"

#: Unbounded digits, matching the generator: D-01..D-99 were all taken.
ID_PATTERN = re.compile(r"^D-\d+$")
HEADING_PATTERN = re.compile(r"^## (D-\d+)\b", re.MULTILINE)

#: The schema-2 entry layouts, written out here rather than read from the
#: generator, so a changed field list in the generator fails this module.
LEGACY_FIELDS = ("id", "title", "kind", "articles", "editions", "summary")
STRUCTURED_FIELDS = ("id", "title", "kind", "editions", "summary", "requirements")
#: What `btap.codes.decisions` and the report's rulings appendix read.
RUNTIME_FIELDS = ("id", "title", "kind", "summary")
MIGRATED_IDS = (
    "D-18", "D-27", "D-28", "D-34", "D-37", "D-38", "D-39", "D-42",
    "D-43", "D-45", "D-46", "D-47", "D-48", "D-49", "D-50", "D-51",
    "D-52", "D-54", "D-55", "D-56", "D-57", "D-89", "D-90", "D-91",
    "D-92", "D-93", "D-97", "D-99", "D-100", "D-101", "D-102",
)
#: The eight decisions Phase D batch 1 moved from `unverified` to the
#: structured form; the other 23 are Phase C's. Every digest below is of the
#: decision's title and summary at the commit BEFORE its conversion.
PHASE_D_BATCH_1_IDS = (
    "D-18", "D-28", "D-34", "D-37", "D-42", "D-43", "D-45", "D-55",
)
MIGRATED_RUNTIME_SHA256 = {
    "D-18": "c3e6a182bad6cdbd8a2eb5256e4505bbddb370426272ae2773709f3f0ae4cc50",
    "D-27": "25dfea7660112851261febd2cfe2c44eb2a54014d372a636afae08def6c58d07",
    "D-28": "39659f04a161b019ad9b4982ba1ef651d093661e469816ff410a2ef42571badc",
    "D-34": "9635c9859756a364f52688cf44de2f9f3e4b1103c73143881d4f883721ea9c05",
    "D-37": "2b200a5bafaeb8bd4fcc344cd84762cfe08c5d1c25adac02facef0a680e079bd",
    "D-38": "7ed399a46526a764811be1971bc332aea224e6a4066ae38e8069ffb7e29c3582",
    "D-39": "d44813de15ff044f44a9e642fbc76ddc3a305c6bda6aa8af38d7e779e198594a",
    "D-42": "dc20ba3f9759a34f830511b874a1002cd8fcb16b52203ba34459e16aa1c1ab18",
    "D-43": "34a4774f23867fb28e0fa2d1fe52c8a837fc52914990dc1c4ed427ecace4a6e6",
    "D-45": "b5c19aa93ae1c773b31c32708d287f5f1d264e423bc7c0fb5698ffc024bdf602",
    "D-46": "254d3857a5100162c4663e7998e0fbf6721d040f9a33b1011ea81c77196d3f95",
    "D-47": "eddeb9120b00fad72ff10bbfebbf7954837cee368e5b763bdf53a13b8c964a8d",
    "D-48": "4fdb6f4e2faf227b7f9d3abc37771392d06a9a577b48b6d04f5b931876304c67",
    "D-49": "78298ddeb4c1622ed05049f08a3c82160088b833822dd13c9869ea70678057ec",
    "D-50": "9f2aaead931daf6e81b6be8637a7504e76892c30dc3301fae8ca165d0c9b5d65",
    "D-51": "a382a728f6c53296c69aaf251fdc577e6bcc8c2de4c56f0b9dd4eaa197c33391",
    "D-52": "cb4e9283b3b0d9459272bca55d557263d2c6c0e7eb4cce11453d5a67ca28f416",
    "D-54": "fab7db18575726291ebe8909298cabcc50199ea6718e1e865c7b2f3213dc4d6b",
    "D-55": "16821c6af91a1f57e8b6ed249371c9584ae1c49088bd53c90d68dc5da0bd10d1",
    "D-56": "45fde852ece1c7fda7a6c634d82def8a24300d56b80e50fb8191ec30ff94e372",
    "D-57": "9aa89dd9b6f154800c5458b15442030ca5dc0c138bf94df932280fce2d7676da",
    "D-89": "d2d60bfd9baff780388a68fac64f41ded05363c1390e9a8457d2bb6fefa2dff5",
    "D-90": "80996e2dde0fa7797f6341bcdf7885a4358f96df2347c0f0695c2844dd536e59",
    "D-91": "e411f246aeb43f8c0d608b547a31e5668cdc5219983fe9ca5ac4381cee569efc",
    "D-92": "9c1f0b55ef949707c2ef6dad0f4f09dce379efa97ac36416394daea867fabbf0",
    "D-93": "a1c69a04699af898d68a4348748138841070138b11e790325167165ea21dc8ad",
    "D-97": "f48c06be02a58654d97dbd360e9aea8eb73ad04a16918bc09ce46742062dbd2e",
    "D-99": "ff82fa03293657350d157766d04ae2d7760f2636cb2983b500bfee31c4afcc17",
    "D-100": "15aa0d6080200fea28ec3e04400c89faa7a1d0292815e2ac009a17500ada9c5f",
    "D-101": "fe8c03c393dcfbf4677febbcd0452be8aedfe2799495963945a51b2156fe7ab0",
    "D-102": "c1db1f4f6c220c0ee04cf3bcd7df1debdbf7e6c2a2f97807a4e44084242a2368",
}
#: Each migrated decision's requirement keys in AUTHORED order, as the
#: sources record them. Phase C's 23 had them in the legacy front matter;
#: Phase D batch 1's eight were authored with their structured form.
MIGRATED_KEYS = {
    "D-18": ("multizone_thermal_block_grouping",),
    "D-27": ("reference_hydronic_pump_power",),
    "D-28": (
        "common_ventilation_note_2",
        "multizone_thermal_block_grouping",
    ),
    "D-34": ("heat_pump_block_redirect",),
    "D-37": ("heat_pump_reference_by_source",),
    "D-38": (
        "prescriptive_pump_power_ceiling",
        "reference_hydronic_pump_power",
        "reference_meets_prescriptive_requirements",
    ),
    "D-39": ("system_5_heating_presence",),
    "D-42": ("unmet_cooling_hours_vs_reference",),
    "D-43": ("capacity_iteration_on_unmet_loads",),
    "D-45": ("selection_table_museum_rows",),
    "D-46": ("unitary_equipment_staging",),
    "D-47": ("unitary_equipment_staging",),
    "D-48": ("unitary_equipment_staging",),
    "D-49": ("furnace_staging",),
    "D-50": ("terminal_secondary_split",),
    "D-51": ("reference_photocontrol_evaluation",),
    "D-52": (
        "heat_pump_auxiliary_heating_energy_type",
        "heat_pump_cooling_capacity",
        "heating_energy_type_inheritance",
    ),
    "D-54": (
        "demand_control_ventilation_requirement",
        "reference_demand_control_ventilation",
    ),
    "D-55": ("reference_humidification_energy_source",),
    "D-56": ("reference_outside_air_cooling", "water_economizer_definition"),
    "D-57": (
        "daylight_responsive_photocontrols",
        "daylighted_area_geometry",
        "reference_photocontrol_evaluation",
    ),
    "D-89": (
        "boiler_part_load_fuel_curve",
        "furnace_part_load_fuel_curve",
        "modulating_boiler_part_load",
        "modulating_furnace_part_load",
        "purchased_heating_energy",
    ),
    "D-90": (
        "capacity_iteration_on_unmet_loads",
        "reference_cooling_capacity",
        "reference_heating_capacity",
    ),
    "D-91": (
        "hvac_systems_calculation_basis",
        "reference_heating_system_dispatch",
        "unmet_load_hour_criteria",
    ),
    "D-92": (
        "hydronic_pump_appendix_method",
        "plant_peak_pumping_flow",
        "prescriptive_pump_power_ceiling",
        "reference_hydronic_pump_power",
    ),
    "D-93": (
        "hydronic_pump_appendix_method",
        "plant_peak_pumping_flow",
        "prescriptive_pump_power_ceiling",
        "reference_hydronic_pump_power",
    ),
    "D-97": (
        "hydronic_pump_appendix_method",
        "plant_capacity_basis",
        "prescriptive_pump_power_ceiling",
        "reference_hydronic_pump_power",
    ),
    "D-99": ("multi_energy_heating", "reference_conformity"),
    "D-100": ("reference_conformity",),
    "D-101": (
        "common_ventilation_note_2",
        "plant_sizing_scope",
        "reference_system_selection",
        "thermal_block_identity",
    ),
    "D-102": ("dx_cooling_part_load", "heat_pump_part_load"),
}
#: Each migrated requirement as the sources record it: its label, then its
#: NECB 2020 and NECB 2025 citations in authored order. A requirement the
#: edition's text does not establish carries `None` for that edition (D-42's
#: sentence 8.4.1.2.(4) is NECB 2020 only). Written out rather than hashed, so
#: a reviewer can read the preserved mapping. Phase C changed only canonical
#: spelling -- a trailing period dropped (`Table 5.2.6.3.`, `8.4.1.2.`) and
#: `Note` prefixed to an Appendix A note (`A-8.4.4.14.(2)`) -- which the
#: provision grammar would otherwise refuse as an alias. A key shared by
#: several decisions appears once: it is one requirement.
MIGRATED_REQUIREMENTS = {
    "boiler_part_load_fuel_curve": (
        "Reference boiler part-load fuel consumption and its efficiency curve",
        ("8.4.5.2.(1)", "8.4.5.2.(2)"),
        ("8.4.6.2.(1)", "8.4.6.2.(2)"),
    ),
    "capacity_iteration_on_unmet_loads": (
        ("Incrementally increasing capacity until the unmet-load criteria "
         "are met"),
        ("8.4.1.2.(5)",),
        ("8.4.1.2.(5)",),
    ),
    "common_ventilation_note_2": (
        "Common ventilation system permitted for Systems 1, 2 and 5",
        ("Table 8.4.4.7.-B Note (2)",),
        ("Table 8.4.5.7.-B Note (2)",),
    ),
    "daylight_responsive_photocontrols": (
        ("Where daylight-responsive photocontrols are required, and the "
         "areas exempt from them"),
        ("4.2.2.1.(10)", "4.2.2.1.(12)", "4.2.2.1.(13)", "4.2.2.1.(15)"),
        ("4.2.2.1.(10)", "4.2.2.1.(12)", "4.2.2.1.(13)", "4.2.2.1.(15)"),
    ),
    "daylighted_area_geometry": (
        ("How the sidelighted and toplighted areas a photocontrol serves "
         "are determined"),
        ("4.2.2.3", "4.2.2.4", "4.2.2.5"),
        ("4.2.2.3", "4.2.2.4", "4.2.2.5"),
    ),
    "demand_control_ventilation_requirement": (
        ("The prescriptive requirement that determines which DCV "
         "strategies are required"),
        ("5.2.3.4",),
        ("5.2.3.4",),
    ),
    "dx_cooling_part_load": (
        ("Reference direct-expansion cooling part-load power and its "
         "part-load ratio"),
        ("8.4.5.4.(4)", "8.4.5.4.(5)", "8.4.5.4.(6)"),
        ("8.4.6.4.(4)", "8.4.6.4.(5)", "8.4.6.4.(6)"),
    ),
    "furnace_part_load_fuel_curve": (
        ("Reference furnace part-load fuel consumption and its efficiency "
         "curve"),
        ("8.4.5.3.(1)", "8.4.5.3.(2)"),
        ("8.4.6.3.(1)", "8.4.6.3.(2)"),
    ),
    "furnace_staging": (
        "Reference furnace staging by capacity",
        ("8.4.4.9.(7)",),
        ("8.4.5.9.(7)",),
    ),
    "heat_pump_auxiliary_heating_energy_type": (
        "Auxiliary-heating energy type elected for a reference heat pump",
        ("8.4.4.13.(2)(g)", "8.4.4.13.(2)(h)"),
        ("8.4.5.13.(2)(g)", "8.4.5.13.(2)(h)"),
    ),
    "heat_pump_block_redirect": (
        ("Article 13 heat-pump classification precedes the residential "
         "selection-table branches"),
        ("8.4.4.7.(4)",),
        ("8.4.5.7.(4)",),
    ),
    "heat_pump_cooling_capacity": (
        ("Reference heat-pump cooling capacity set from peak load without "
         "oversizing"),
        ("8.4.4.13.(2)(b)",),
        ("8.4.5.13.(2)(b)",),
    ),
    "heat_pump_part_load": (
        ("Reference air-source heat-pump part-load power and its part-load "
         "ratio"),
        ("8.4.5.7.(4)", "8.4.5.7.(5)", "8.4.5.7.(6)"),
        ("8.4.6.7.(4)", "8.4.6.7.(5)", "8.4.6.7.(6)"),
    ),
    "heat_pump_reference_by_source": (
        "Reference system for a proposed heat pump, by heat source",
        ("8.4.4.13.(1)", "8.4.4.13.(2)(a)", "Note A-8.4.4.13"),
        ("8.4.5.13.(1)", "8.4.5.13.(2)(a)", "Note A-8.4.5.13"),
    ),
    "heating_energy_type_inheritance": (
        "Reference heating-system energy type follows the proposed building",
        ("8.4.4.9.(4)",),
        ("8.4.5.9.(4)",),
    ),
    "hvac_systems_calculation_basis": (
        "The basis on which reference HVAC systems are calculated",
        ("8.4.2.10.(2)",),
        ("8.4.2.10.(2)",),
    ),
    "hydronic_pump_appendix_method": (
        ("The Appendix A note's pump-power method and its one "
         "primary-secondary example"),
        ("Note A-8.4.4.14.(2)",),
        ("Note A-8.4.5.14.(2)",),
    ),
    "modulating_boiler_part_load": (
        "Reference modulating boiler part-load fuel curve",
        ("8.4.5.2.(3)",),
        ("8.4.6.2.(2)",),
    ),
    "modulating_furnace_part_load": (
        "Reference modulating furnace part-load fuel curve",
        ("8.4.5.3.(3)",),
        ("8.4.6.3.(2)",),
    ),
    "multi_energy_heating": (
        "Multi-energy heating capacity allocation and operating priority",
        ("8.4.4.9.(4)", "8.4.4.9.(5)", "8.4.4.9.(6)"),
        ("8.4.5.9.(4)", "8.4.5.9.(5)", "8.4.5.9.(6)"),
    ),
    "multizone_thermal_block_grouping": (
        ("Grouping of thermal blocks onto a multizone reference system by "
         "storey count and facade orientation"),
        ("Table 8.4.4.7.-B Note (3)",),
        ("Table 8.4.5.7.-B Note (3)",),
    ),
    "plant_capacity_basis": (
        ("Plant capacity as the sum of the systems it serves, heating and "
         "cooling"),
        ("8.4.4.9.(6)(a)", "8.4.4.10.(6)(a)"),
        ("8.4.5.9.(6)(a)", "8.4.5.10.(6)(a)"),
    ),
    "plant_peak_pumping_flow": (
        "Plant peak pumping flow rate, heating and cooling",
        ("8.4.4.9.(6)(f)", "8.4.4.10.(6)(e)"),
        ("8.4.5.9.(6)(f)", "8.4.5.10.(6)(e)"),
    ),
    "plant_sizing_scope": (
        "A hydronic plant is sized from the systems it serves",
        ("8.4.4.9.(6)", "8.4.4.10.(6)"),
        ("8.4.5.9.(6)", "8.4.5.10.(6)"),
    ),
    "prescriptive_pump_power_ceiling": (
        ("Prescriptive ceiling on combined pump-motor power, and the table "
         "that supplies it"),
        ("5.2.6.3.(1)", "Table 5.2.6.3"),
        ("5.2.6.3.(1)", "Table 5.2.6.3"),
    ),
    "purchased_heating_energy": (
        ("How purchased heating energy is represented in the reference "
         "building"),
        ("8.4.4.6.(1)",),
        ("8.4.5.6.(1)",),
    ),
    "reference_conformity": (
        "Performance-compliance reference conformity",
        ("8.4.1.2", "8.4.2.10"),
        ("8.4.1.2", "8.4.2.10"),
    ),
    "reference_cooling_capacity": (
        "The reference cooling system's capacity basis",
        ("8.4.4.10.(6)",),
        ("8.4.5.10.(6)",),
    ),
    "reference_demand_control_ventilation": (
        ("Reference building inherits the proposed demand-control "
         "ventilation strategies"),
        ("8.4.4.15.(2)",),
        ("8.4.5.15.(2)",),
    ),
    "reference_heating_capacity": (
        "The reference heating system's capacity basis",
        ("8.4.4.9.(6)",),
        ("8.4.5.9.(6)",),
    ),
    "reference_heating_system_dispatch": (
        "How the reference heating system serves a thermal block",
        ("8.4.4.9.(3)",),
        ("8.4.5.9.(3)",),
    ),
    "reference_humidification_energy_source": (
        "Energy source of humidification in the reference building",
        ("Table 8.4.4.7.-B Note (1)",),
        ("Table 8.4.5.7.-B Note (1)",),
    ),
    "reference_hydronic_pump_power": (
        ("Reference hydronic pump power: the sentences that state it and "
         "its scope"),
        ("8.4.4.14.(1)", "8.4.4.14.(2)", "8.4.4.14.(3)"),
        ("8.4.5.14.(1)", "8.4.5.14.(2)", "8.4.5.14.(3)"),
    ),
    "reference_meets_prescriptive_requirements": (
        ("The reference building's systems meet the Part 5 prescriptive "
         "requirements"),
        ("8.4.4.1.(2)",),
        ("8.4.5.1.(2)",),
    ),
    "reference_outside_air_cooling": (
        ("Whether the reference building cools with outside air, and by "
         "which system"),
        ("8.4.4.12",),
        ("8.4.5.12",),
    ),
    "reference_photocontrol_evaluation": (
        ("How the reference building evaluates the effect of required "
         "photocontrols"),
        ("8.4.4.5.(9)", "8.4.4.5.(10)", "8.4.4.5.(11)", "8.4.4.5.(12)"),
        ("8.4.5.5.(9)", "8.4.5.5.(10)", "8.4.5.5.(11)", "8.4.5.5.(12)"),
    ),
    "reference_system_selection": (
        "Reference HVAC system assigned to each thermal block",
        ("8.4.4.7.(1)", "8.4.4.9.(1)", "8.4.4.10.(1)"),
        ("8.4.5.7.(1)", "8.4.5.9.(1)", "8.4.5.10.(1)"),
    ),
    "selection_table_museum_rows": (
        ("Selection-table rows that can apply to a museum, gallery or "
         "exhibit space"),
        ("Table 8.4.4.7.-A",),
        ("Table 8.4.5.7.-A",),
    ),
    "system_5_heating_presence": (
        ("Heating presence where the general reference rule and the System "
         "5 row conflict"),
        ("8.4.4.1.(5)", "Table 8.4.4.7.-A", "Table 8.4.4.7.-B"),
        ("8.4.5.1.(5)", "Table 8.4.5.7.-A", "Table 8.4.5.7.-B"),
    ),
    "terminal_secondary_split": (
        "Reference terminal and secondary heating/cooling capacity split",
        ("8.4.4.9.(3)", "8.4.4.10.(7)"),
        ("8.4.5.9.(3)", "8.4.5.10.(7)"),
    ),
    "thermal_block_identity": (
        "The reference retains the proposed building's thermal blocks",
        ("8.4.4.1.(4)",),
        ("8.4.5.1.(4)",),
    ),
    "unitary_equipment_staging": (
        "Reference unitary heating and cooling equipment staging by capacity",
        ("8.4.4.9.(7)", "8.4.4.10.(8)"),
        ("8.4.5.9.(7)", "8.4.5.10.(8)"),
    ),
    "unmet_cooling_hours_vs_reference": (
        ("Proposed-building unmet cooling hours compared with the reference "
         "building's"),
        ("8.4.1.2.(4)",),
        None,
    ),
    "unmet_load_hour_criteria": (
        ("The unmet heating and cooling hour criteria a compliant model "
         "must meet"),
        ("8.4.1.2.(3)", "8.4.1.2.(4)"),
        ("8.4.1.2.(3)", "8.4.1.2.(4)"),
    ),
    "water_economizer_definition": (
        "What qualifies as cooling by indirect use of outdoor air",
        ("5.2.2.9",),
        ("5.2.2.9",),
    ),
}
#: The requirement keys several migrated decisions share, and who shares
#: them. Each is ONE requirement with one label and one mapping.
SHARED_KEY_USERS = {
    "capacity_iteration_on_unmet_loads": ("D-43", "D-90"),
    "common_ventilation_note_2": ("D-28", "D-101"),
    "hydronic_pump_appendix_method": ("D-92", "D-93", "D-97"),
    "multizone_thermal_block_grouping": ("D-18", "D-28"),
    "plant_peak_pumping_flow": ("D-92", "D-93"),
    "prescriptive_pump_power_ceiling": ("D-38", "D-92", "D-93", "D-97"),
    "reference_conformity": ("D-99", "D-100"),
    "reference_hydronic_pump_power": (
        "D-27", "D-38", "D-92", "D-93", "D-97"),
    "reference_photocontrol_evaluation": ("D-51", "D-57"),
    "unitary_equipment_staging": ("D-46", "D-47", "D-48"),
}


def migrated_sources(key):
    """The governing records a migrated requirement carries: NECB 2020, then
    NECB 2025 where the requirement is established for it."""
    _label, *citations = MIGRATED_REQUIREMENTS[key]
    return [{"code": "necb", "edition": edition, "role": "governing",
             "references": list(references)}
            for edition, references in zip(("2020", "2025"), citations)
            if references is not None]


def migrated_editions(decision_id):
    """The code ids a migrated decision governs, read off the literal table."""
    return sorted({"necb" + source["edition"]
                   for key in MIGRATED_KEYS[decision_id]
                   for source in migrated_sources(key)})


def runtime_editions():
    """``(family, edition) -> code id``, from the runtime registry."""
    return {(codes.resolve(code_id).family, codes.resolve(code_id).edition): code_id
            for code_id in codes.code_ids()}


def expected_entry(meta):
    """The registry entry one front matter must project to.

    The form is read off the source: a structured requirement carries
    ``sources``. Only governing records contribute to ``editions``.
    """
    articles = meta["articles"]
    if not any(isinstance(block, dict) and "sources" in block
               for block in articles.values()):
        return {field: meta[field] for field in LEGACY_FIELDS}
    runtime = runtime_editions()
    editions = sorted({runtime[(source["code"], source["edition"])]
                       for block in articles.values()
                       for source in block["sources"]
                       if source["role"] == "governing"})
    requirements = [
        {"id": key, "label": block["label"], "decided": block["decided"],
         "sources": [{field: source[field]
                      for field in ("code", "edition", "role", "references")}
                     for source in block["sources"]]}
        for key, block in sorted(articles.items())]
    return {"id": meta["id"], "title": meta["title"], "kind": meta["kind"],
            "editions": editions, "summary": meta["summary"],
            "requirements": requirements}


def ordered(value):
    """JSON text, so a comparison also holds every level's key ORDER."""
    return json.dumps(value, indent=1, ensure_ascii=False)


#: A table cell separator: a pipe the generator did not escape.
CELL_SPLIT = re.compile(r"(?<!\\)\|")
#: A link to a decision's section in the decision log. The file name and the
#: fragment are joined here, at runtime, so this module does not itself read as
#: an inbound link for the tree-wide short-link scan.
DECISION_LINK = re.compile(r"\]\(" + re.escape(DECISIONS_DOC.name) + r"#(d-\d+)\)")
SUMMARY_ANCHOR = re.compile(r'^<a id="transitional-summary-(d-\d+)"></a>$',
                            re.MULTILINE)
EDITION_HEADING = re.compile(r"^(.+) \(code id `([^`]+)`\)$")
#: The `##` sections that are not a code. Every other one is a code family.
VIEW_SECTIONS = ("Scope", "Definitions", "Transitional decision summaries",
                 "Edition not yet attributed")
NOT_ATTRIBUTED = "Edition not yet attributed"


def raw_front_matter():
    """``{id: front matter}`` read straight from the files, in numeric id
    order and with no generator code, so what the view must contain is worked
    out independently of it."""
    paths = sorted(SOURCE_DIR.glob("D-*.md"),
                   key=lambda path: int(path.stem.split("-")[1]))
    return {path.stem: tomllib.loads(
                path.read_text(encoding="utf-8").split("+++\n")[1])
            for path in paths}


def raw_body(decision_id):
    """A decision's authored body: everything after its front matter."""
    text = (SOURCE_DIR / (decision_id + ".md")).read_text(encoding="utf-8")
    return text.split("+++\n", 2)[2]


#: A run of this many words shared with the recorded Code text is a copy.
AUTHORITY_RUN = 8
NECB_DATA = PYTHON_ROOT / "btap" / "codes" / "necb" / "data"


def word_runs(text, length):
    words = re.findall(r"[a-z0-9]+(?:[.'-][a-z0-9]+)*",
                       text.casefold().replace("\u2019", "'"))
    return [tuple(words[i:i + length]) for i in range(len(words) - length + 1)]


def authority_runs(length):
    """Every `length`-word run of Code text an edition snapshot records as
    evidence: the archived hbix payloads and the Section 8.4 cache."""
    runs = set()

    def walk(value):
        if isinstance(value, str):
            runs.update(word_runs(value, length))
        elif isinstance(value, dict):
            for item in value.values():
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)

    snapshots = sorted(NECB_DATA.glob("necb*/manifest.json"))
    assert len(snapshots) >= 2, snapshots
    for manifest in snapshots:
        for name in ("provenance/provisions.result.json",
                     "coverage/articles_8_4.json"):
            walk(json.loads((manifest.parent / name).read_text(encoding="utf-8")))
    return runs


def recorded_citations(articles):
    """Every citation a decision records, in any of its three forms."""
    found = []
    for block in articles.values():
        if isinstance(block, list):                       # unverified / not_applicable
            found += block
        elif "sources" in block:                          # structured
            found += [reference for record in block["sources"]
                      for reference in record["references"]]
        else:                                             # legacy, per code id
            found += [citation for code_id, citations in block.items()
                      if code_id != "label" for citation in citations]
    return found


def classify(front):
    """``(structured, established, held, omitted)`` decision ids, decided from
    what each decision RECORDS and not from the generator's classification."""
    structured, established, held, omitted = [], [], [], []
    for decision_id, meta in front.items():
        articles = meta["articles"]
        if not recorded_citations(articles):
            omitted.append(decision_id)
        elif any(isinstance(block, dict) and "sources" in block
                 for block in articles.values()):
            structured.append(decision_id)
        elif set(articles) == {"unverified"}:
            held.append(decision_id)
        else:
            established.append(decision_id)
    return structured, established, held, omitted


def view_rows(view):
    """``(section, heading, cells)`` for every table body row of a provision
    view, where ``section`` is the `##` heading and ``heading`` the `###`."""
    section = heading = ""
    rows = []
    for line in view.splitlines():
        if line.startswith("### "):
            heading = line[4:]
        elif line.startswith("## "):
            section, heading = line[3:], ""
        elif line.startswith("|---"):
            rows.pop()          # the header row this rule underlines
        elif line.startswith("|"):
            rows.append((section, heading,
                         [cell.strip() for cell in CELL_SPLIT.split(line)[1:-1]]))
    return rows


def code_spans(cell):
    return [span.replace("\\|", "|") for span in re.findall(r"`([^`]+)`", cell)]


def unescape(text):
    """The text a Markdown reader sees once backslash escapes are applied."""
    return re.sub(r"\\(.)", r"\1", text)


def leading_number(span):
    """A citation's provision number as integers, Division A first."""
    number = re.search(r"\d+(?:\.\d+)*", span).group()
    return (0 if span.startswith("Division A") else 1,
            tuple(int(part) for part in number.split(".")))


class TestDecisionSources(unittest.TestCase):
    """Every source file parses and carries a well-formed entry."""

    @classmethod
    def setUpClass(cls):
        cls.preamble, cls.entries, cls.meta = G.read_sources(SOURCE_DIR)

    def test_every_source_parses_and_has_a_unique_well_formed_id(self):
        # parse_source validates as it reads, so reaching here is the schema
        # check; what remains is that the ids are unique and well formed.
        self.assertGreater(len(self.entries), 0)
        for decision_id in self.entries:
            self.assertRegex(decision_id, ID_PATTERN,
                             f"malformed decision id: {decision_id!r}")
        # Through the PRODUCTION helper. The first version of this assertion
        # recomputed the stray set from a byte-for-byte copy of the generator's
        # expression, so deleting the generator's guard left the whole suite
        # green -- the fourth instance in this repository of a test agreeing
        # with its own reimplementation rather than with the code (Fable, PR
        # #64). One implementation, two callers. The rejection case lives in
        # test_decisions_generator.py.
        stray = G.stray_files(SOURCE_DIR)
        self.assertEqual(
            [], stray,
            "entr(ies) in the canonical directory that reach none of the "
            f"generated outputs: {stray}")

    def test_a_source_file_rewrites_to_itself(self):
        """The writer is the inverse of the parser, for every real source.

        A source that does not survive a parse/write round trip means editing
        any one decision through the tooling would silently reformat it.
        """
        for path in sorted(SOURCE_DIR.glob("D-*.md")):
            with self.subTest(source=path.name):
                meta, body = G.parse_source(path)
                self.assertEqual(path.read_text(encoding="utf-8"),
                                 G.source_text(meta, body))

    def test_runtime_entries_declare_articles_or_say_why_not(self):
        """A ``kind`` is one of the four the registry defines."""
        for decision_id, (meta, _body) in self.entries.items():
            with self.subTest(decision=decision_id):
                self.assertIn(meta["kind"], G.KINDS)


class TestGeneratedOutputsAreInStep(unittest.TestCase):
    """No generated artifact may drift from, or be edited beside, its sources."""

    @classmethod
    def setUpClass(cls):
        cls.doc, cls.registry, cls.provision_view = G.generate(SOURCE_DIR)
        cls.entries = G.read_sources(SOURCE_DIR)[1]

    def test_check_passes_on_the_committed_tree(self):
        """The drift gate itself -- the same command CI runs."""
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "--check"],
            cwd=REPO_ROOT, capture_output=True, text=True, check=False)
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)

    def test_committed_document_is_exactly_what_the_sources_render(self):
        self.assertEqual(DECISIONS_DOC.read_text(encoding="utf-8"), self.doc,
                         "docs/necb_decisions.md is generated; edit "
                         "docs/decisions/D-NN.md and regenerate")

    def test_committed_registry_is_exactly_what_the_sources_render(self):
        self.assertEqual(PYTHON_REGISTRY.read_text(encoding="utf-8"), self.registry,
                         "decisions.json is generated; edit "
                         "docs/decisions/D-NN.md and regenerate")

    def test_committed_provision_view_is_exactly_what_the_sources_render(self):
        self.assertEqual(PROVISION_VIEW.read_text(encoding="utf-8"),
                         self.provision_view,
                         "docs/CODE_DECISIONS_BY_PROVISION.md is generated; "
                         "edit docs/decisions/D-NN.md and regenerate")

    def test_the_generator_writes_the_view_where_the_documents_live(self):
        """The default output path IS the committed file, so a plain
        `generate_decisions.py` and `--check` read and write it."""
        self.assertEqual(PROVISION_VIEW, G.PROVISION_VIEW)
        self.assertEqual(DECISIONS_DOC.parent, G.PROVISION_VIEW.parent)

    def test_the_log_and_the_registry_carry_exactly_the_source_id_set(self):
        headings = HEADING_PATTERN.findall(self.doc)
        self.assertEqual(len(headings), len(set(headings)),
                         "duplicate ## D-XX headings in the generated document")
        self.assertEqual(set(headings), set(self.entries))
        registry_ids = [entry["id"] for entry in json.loads(self.registry)["decisions"]]
        self.assertEqual(len(registry_ids), len(set(registry_ids)),
                         "duplicate ids in the generated registry")
        self.assertEqual(set(registry_ids), set(self.entries))

    def test_the_log_and_the_registry_are_in_numeric_id_order(self):
        """Numeric id order is the ordering invariant of these two, and the
        only one. The provision view is ordered by code, edition and provision
        instead.

        The pre-migration files carried three different sequences -- document,
        registry and numeric -- and claimed a chronology that did not hold
        (D-58..D-60, dated 2026-08-02, preceded D-53..D-57, dated 2026-07-29).
        """
        expected = G.numeric_order(self.entries)
        self.assertEqual(HEADING_PATTERN.findall(self.doc), expected)
        self.assertEqual(
            [entry["id"] for entry in json.loads(self.registry)["decisions"]], expected)

    def test_the_index_does_not_claim_a_chronology(self):
        self.assertIn(G.INDEX_HEADING, self.doc)
        self.assertNotIn("chronological", self.doc.split(G.END_MARK)[0])

    def test_every_decision_has_exactly_one_generated_anchor(self):
        """The structural gate: generation emits one anchor per decision.

        This checks the LITERAL form the generator writes, which is exact and
        needs no model of Markdown. It does NOT establish that an authored
        body cannot introduce a second owner of the same short id in some
        other spelling -- that rule was cut from this PR after five review
        rounds kept finding further spellings, and the residual risk is an
        ambiguous `#d-NN` fragment rather than a dead link. The dead-link
        class is closed structurally, because every anchor is emitted outside
        every authored body.
        """
        anchors = re.findall(r'^<a id="(d-\d+)"></a>$', self.doc, re.MULTILINE)
        self.assertEqual(len(anchors), len(set(anchors)), "duplicate generated anchor")
        self.assertEqual({i.lower() for i in self.entries}, set(anchors),
                         "every decision must carry its generated anchor")
        for decision_id in self.entries:
            with self.subTest(decision=decision_id):
                self.assertIn(
                    '<a id="{}"></a>\n\n## {} '.format(decision_id.lower(), decision_id),
                    self.doc, "the anchor must sit immediately above its heading")

    def test_the_registry_is_the_front_matter_projection(self):
        """Each entry is its source's schema-2 projection, field order
        included: the front matter for a legacy decision, ``requirements``
        and the derived ``editions`` for a structured one."""
        for entry in json.loads(self.registry)["decisions"]:
            with self.subTest(decision=entry["id"]):
                self.assertEqual(
                    ordered(expected_entry(self.entries[entry["id"]][0])),
                    ordered(entry))
                self.assertIn(tuple(entry), (LEGACY_FIELDS, STRUCTURED_FIELDS))

    def test_the_registry_is_schema_2_around_its_root_array(self):
        payload = json.loads(self.registry)
        self.assertEqual(["_comment", "schema", "decisions"], list(payload))
        self.assertIs(int, type(payload["schema"]))
        self.assertEqual(2, payload["schema"])
        self.assertEqual(Loader.SCHEMA, payload["schema"])
        meta = json.loads((SOURCE_DIR / G.META_FILE).read_text(encoding="utf-8"))
        self.assertEqual(meta["registry_comment"], payload["_comment"])

    def test_every_entry_keeps_the_fields_the_runtime_reads(self):
        """``id``, ``title``, ``kind`` and ``summary`` are what resolves a
        ruling and fills the report's rulings appendix, in either form."""
        for entry in json.loads(self.registry)["decisions"]:
            meta = self.entries[entry["id"]][0]
            with self.subTest(decision=entry["id"]):
                self.assertEqual({field: meta[field] for field in RUNTIME_FIELDS},
                                 {field: entry[field] for field in RUNTIME_FIELDS})

    def test_the_runtime_loader_serves_the_generated_array(self):
        self.assertTrue(Path(Loader.__file__).resolve().is_relative_to(
            PYTHON_ROOT / "btap"), Loader.__file__)
        with mock.patch.object(Loader, "_all", None), \
                mock.patch.object(Loader, "_by_id", None):
            self.assertEqual(json.loads(self.registry)["decisions"],
                             Loader.all_decisions())


#: A structured decision as an author writes it, in the writer's own layout.
#: Its NECB references are ones each edition's committed provision index
#: records as present; the related NECB record and the incorporated external
#: standard sit beside the two governing records and establish nothing.
STRUCTURED_SOURCE = """\
+++
id = "{id}"
title = "Fixture: a structured decision beside the committed tree"
kind = "runtime"
summary = "A fixture decision that exists only inside this test."

[articles.fixture_heat_pump_source_split]
label = "Reference system for a proposed heat pump, by heat source"
decided = "Water-loop and other heat pumps follow different reference-system selection branches."

[[articles.fixture_heat_pump_source_split.sources]]
code = "necb"
edition = "2020"
role = "governing"
references = [
  "8.4.4.13.(1)",
  "8.4.4.13.(2)",
  "Note A-8.4.4.13",
]

[[articles.fixture_heat_pump_source_split.sources]]
code = "necb"
edition = "2025"
role = "governing"
references = [
  "8.4.5.13.(1)",
  "8.4.5.13.(2)",
  "Note A-8.4.5.13",
]

[[articles.fixture_heat_pump_source_split.sources]]
code = "necb"
edition = "2020"
role = "related"
references = [
  "Table 8.4.4.7.-B",
]

[[articles.fixture_heat_pump_source_split.sources]]
code = "ashrae-62.1"
edition = "2016"
role = "incorporated-reference"
references = [
  "6.2.2.1",
]
+++

## {id} — A structured fixture decision

Body text.
"""


class TestAStructuredDecisionBesideTheCommittedTree(unittest.TestCase):
    """End to end, on a COPY of the committed sources plus one structured
    decision at the next free id: the generator accepts it beside every
    legacy decision, no committed entry or section moves, and the runtime
    loader resolves it from the file the generator wrote."""

    KEY = "fixture_heat_pump_source_split"

    @classmethod
    def setUpClass(cls):
        scratch = tempfile.TemporaryDirectory()
        cls.addClassCleanup(scratch.cleanup)
        root = Path(scratch.name)
        cls.source_dir = root / "decisions"
        shutil.copytree(SOURCE_DIR, cls.source_dir)
        taken = [int(path.stem[len("D-"):]) for path in SOURCE_DIR.glob("D-*.md")]
        cls.new_id = "D-{}".format(max(taken) + 1)
        cls.text = STRUCTURED_SOURCE.format(id=cls.new_id)
        cls.path = cls.source_dir / (cls.new_id + ".md")
        cls.path.write_text(cls.text, encoding="utf-8")
        cls.front = tomllib.loads(cls.text.split(G.FENCE + "\n")[1])
        cls.body = cls.text.split("\n" + G.FENCE + "\n\n", 1)[1]

        cls.doc_path = root / "necb_decisions.md"
        cls.registry_path = root / "data" / "decisions.json"
        cls.view_path = root / "CODE_DECISIONS_BY_PROVISION.md"
        cls.registry_path.parent.mkdir()
        arguments = ["--source-dir", str(cls.source_dir), "--doc", str(cls.doc_path),
                     "--registry", str(cls.registry_path),
                     "--provision-view", str(cls.view_path)]
        cls.outcomes = {}
        for mode, argv in (("write", arguments), ("check", ["--check", *arguments])):
            out = io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
                cls.outcomes[mode] = (G.main(argv), out.getvalue())
        cls.doc = cls.doc_path.read_text(encoding="utf-8")
        cls.view = cls.view_path.read_text(encoding="utf-8")
        cls.payload = json.loads(cls.registry_path.read_text(encoding="utf-8"))
        cls.committed = json.loads(PYTHON_REGISTRY.read_text(encoding="utf-8"))

    def test_the_fixture_key_is_not_a_committed_requirement(self):
        """Otherwise the shared-key rule, not the structured form, would be
        what this class exercises."""
        _, entries, _ = G.read_sources(SOURCE_DIR)
        self.assertFalse(any(self.KEY in meta["articles"]
                             for meta, _ in entries.values()))

    def test_both_branches_accept_it(self):
        for mode, (code, output) in self.outcomes.items():
            with self.subTest(mode=mode):
                self.assertEqual(0, code, output)

    def test_the_authored_file_is_already_in_the_writers_layout(self):
        meta, body = G.parse_source(self.path)
        self.assertEqual(self.text, G.source_text(meta, body))

    def test_its_entry_is_the_structured_projection(self):
        entry = self.payload["decisions"][-1]
        self.assertEqual(self.new_id, entry["id"])
        self.assertEqual(ordered(expected_entry(self.front)), ordered(entry))
        self.assertEqual(STRUCTURED_FIELDS, tuple(entry))
        self.assertNotIn("articles", entry)
        # Literal, not derived: the two governing records and nothing else.
        self.assertEqual(["necb2020", "necb2025"], entry["editions"])
        (requirement,) = entry["requirements"]
        self.assertEqual(self.KEY, requirement["id"])
        self.assertEqual(
            [("necb", "2020", "governing"), ("necb", "2025", "governing"),
             ("necb", "2020", "related"),
             ("ashrae-62.1", "2016", "incorporated-reference")],
            [(source["code"], source["edition"], source["role"])
             for source in requirement["sources"]])

    def test_no_committed_entry_moves(self):
        self.assertEqual(self.committed["_comment"], self.payload["_comment"])
        self.assertEqual(self.committed["schema"], self.payload["schema"])
        self.assertEqual(ordered(self.committed["decisions"]),
                         ordered(self.payload["decisions"][:-1]))

    def test_the_document_gains_one_index_line_and_one_section(self):
        """Byte-exact: the committed document with exactly the new decision's
        index line and its anchored section added, and nothing else."""
        committed = DECISIONS_DOC.read_text(encoding="utf-8")
        head, end, tail = committed.partition("\n\n<!-- TOC END -->")
        self.assertTrue(end, "the committed document has no index end marker")
        line = "- **{}** — {} _(runtime)_".format(self.new_id, self.front["title"])
        self.assertEqual(
            head + "\n" + line + end + tail + "\n"
            + '<a id="{}"></a>\n\n'.format(self.new_id.lower()) + self.body,
            self.doc)

    def new_rows(self):
        """``(heading, cells)`` for every provision-view row of the new id."""
        return [(heading, cells) for section, heading, cells in view_rows(self.view)
                if section not in VIEW_SECTIONS
                and DECISION_LINK.search(cells[1]).group(1) == self.new_id.lower()]

    def test_the_provision_view_gains_only_its_two_rows_and_three_counts(self):
        """Every committed line survives in its place; the only lines that
        change are the three scope counts, and two rows are added."""
        committed = PROVISION_VIEW.read_text(encoding="utf-8")
        counted = ("| Decisions with concrete rows from structured",
                   "| Decisions included in this view", "| All decisions")
        before = [line for line in committed.splitlines()
                  if not line.startswith(counted)]
        after = [line for line in self.view.splitlines()
                 if not line.startswith(counted)]
        known = set(before)
        added = [line for line in after if line not in known]
        self.assertEqual(before, [line for line in after if line in known],
                         "no committed line moves, changes or disappears")
        self.assertEqual(2, len(added), added)
        for line in added:
            self.assertIn(
                "]({}#{})".format(DECISIONS_DOC.name, self.new_id.lower()), line)

        def scope(view):
            return {cells[0]: int(cells[1]) for section, _h, cells in view_rows(view)
                    if section == "Scope"}
        old, new = scope(committed), scope(self.view)
        self.assertEqual(
            {"Decisions with concrete rows from structured source records": 1,
             "Decisions included in this view": 1, "All decisions": 1},
            {name: new[name] - old[name] for name in new if new[name] != old[name]})

    def test_its_rows_are_its_governing_records_and_nothing_else(self):
        rows = self.new_rows()
        self.assertEqual(
            ["NECB 2020 (code id `necb2020`)", "NECB 2025 (code id `necb2025`)"],
            [heading for heading, _cells in rows])
        (_, row_2020), (_, row_2025) = rows
        # Sentences, then the Appendix note, in provision order.
        self.assertEqual(["8.4.4.13.(1)", "8.4.4.13.(2)", "Note A-8.4.4.13"],
                         code_spans(row_2020[0]))
        self.assertEqual(["8.4.5.13.(1)", "8.4.5.13.(2)", "Note A-8.4.5.13"],
                         code_spans(row_2025[0]))
        for cells in (row_2020, row_2025):
            for related in ("Table 8.4.4.7.-B", "6.2.2.1"):
                self.assertNotIn(related, code_spans(cells[0]))
        self.assertEqual(
            "NECB 2025: " + ", ".join("`{}`".format(c) for c in
                                      ("8.4.5.13.(1)", "8.4.5.13.(2)",
                                       "Note A-8.4.5.13")), row_2020[4])
        self.assertEqual(
            "NECB 2020: " + ", ".join("`{}`".format(c) for c in
                                      ("8.4.4.13.(1)", "8.4.4.13.(2)",
                                       "Note A-8.4.4.13")), row_2025[4])
        # The related NECB record and the incorporated standard are other
        # sources on BOTH rows, and never a row, a heading or an edition.
        sources = ("*incorporated-reference* ashrae-62.1 2016: `6.2.2.1`<br>"
                   "*related* NECB 2020: `Table 8.4.4.7.-B`")
        self.assertEqual([sources, sources], [row_2020[5], row_2025[5]])
        self.assertEqual([], re.findall(r"^#{2,3} .*ashrae", self.view,
                                        re.MULTILINE | re.IGNORECASE))

    def test_its_rows_carry_the_requirements_own_decided_text(self):
        decided = self.front["articles"][self.KEY]["decided"]
        for _heading, cells in self.new_rows():
            self.assertEqual(decided, cells[3])
            self.assertNotIn("Transitional", cells[3])
        self.assertNotIn(self.front["summary"], self.view)
        self.assertNotIn("transitional-summary-" + self.new_id.lower(), self.view)

    def test_the_runtime_loader_resolves_it_from_the_written_file(self):
        with mock.patch.object(Loader, "DATA_DIR", self.registry_path.parent), \
                mock.patch.object(Loader, "_all", None), \
                mock.patch.object(Loader, "_by_id", None):
            entry = Loader.lookup(self.new_id)
            self.assertEqual(self.front["title"], entry["title"])
            self.assertEqual(self.front["summary"], entry["summary"])
            self.assertIn(entry, Loader.of_kind("runtime"))
            self.assertEqual([item["id"] for item in self.payload["decisions"]],
                             Loader.ids())

    def test_only_its_external_record_is_disclosed(self):
        """The committed tree carries no source an index cannot validate, the
        related NECB 2020 record is validated, and the external standard is
        named on both branches."""
        note = ("decisions: note — {} articles[{!r}] cites ashrae-62.1 2016 "
                "(incorporated-reference), which no registered provision index "
                "validates; it is carried as authored and establishes no "
                "edition").format(self.new_id, self.KEY)
        for mode, (_, output) in self.outcomes.items():
            with self.subTest(mode=mode):
                self.assertEqual(
                    [note], [line for line in output.splitlines()
                             if "provision index validates" in line])


class TestTheCommittedProvisionView(unittest.TestCase):
    """``docs/CODE_DECISIONS_BY_PROVISION.md`` against the RAW decision files.

    ``TestGeneratedOutputsAreInStep`` already proves the file is what the
    generator renders. That proves nothing about whether the generator is
    right, so everything here is worked out from the front matter directly,
    with no generator code: which decisions the view must include and omit,
    which row each requirement owes each edition, and where it may not appear.
    """

    #: Phase C converted every established mapping (23 structured), and Phase
    #: D batch 1 moved eight held decisions to the structured form (31), 45
    #: held down to 37. Neither moves the 68 citation-bearing or the 35
    #: citation-free totals. SOURCE_ROWS counts governing source records
    #: (D-42 has one, the other 61 requirements two each); REQUIREMENTS counts
    #: requirement instances, a shared key once per decision that uses it.
    STRUCTURED, ESTABLISHED, HELD, INCLUDED, OMITTED = 31, 0, 37, 68, 35
    SOURCE_ROWS = 123
    REQUIREMENTS = 62

    @classmethod
    def setUpClass(cls):
        cls.view = PROVISION_VIEW.read_text(encoding="utf-8")
        cls.doc = DECISIONS_DOC.read_text(encoding="utf-8")
        cls.front = raw_front_matter()
        (cls.structured, cls.established, cls.held,
         cls.omitted) = classify(cls.front)
        cls.included = cls.structured + cls.established + cls.held
        cls.rows = view_rows(cls.view)
        cls.edition_rows = []
        for section, heading, cells in cls.rows:
            if section not in VIEW_SECTIONS:
                match = EDITION_HEADING.match(heading)
                assert match, "a code section row sits under {!r}".format(heading)
                cls.edition_rows.append((match.group(2), cells))
        cls.held_rows = [cells for section, _heading, cells in cls.rows
                         if section == NOT_ATTRIBUTED]

    @staticmethod
    def linked(cell):
        return DECISION_LINK.search(cell).group(1).upper()

    def test_the_scope_table_counts_what_the_raw_sources_say(self):
        scope = {cells[0]: int(cells[1]) for section, _heading, cells in self.rows
                 if section == "Scope"}
        self.assertEqual({
            "Decisions with concrete rows from structured source records":
                len(self.structured),
            "Decisions with concrete rows from an established legacy mapping":
                len(self.established),
            "Decisions held under Edition not yet attributed": len(self.held),
            "Decisions included in this view": len(self.included),
            "Decisions omitted because they cite no provision":
                len(self.omitted),
            "All decisions": len(self.front)}, scope)

    def test_the_migration_census_and_ids_are_exact(self):
        self.assertEqual(
            (
                self.STRUCTURED,
                self.ESTABLISHED,
                self.HELD,
                self.INCLUDED,
                self.OMITTED,
            ),
            (
                len(self.structured),
                len(self.established),
                len(self.held),
                len(self.included),
                len(self.omitted),
            ),
        )
        self.assertEqual(MIGRATED_IDS, tuple(self.structured))
        self.assertEqual(
            self.REQUIREMENTS,
            sum(
                len(self.front[decision_id]["articles"])
                for decision_id in self.structured
            ),
        )
        self.assertEqual(
            self.SOURCE_ROWS,
            sum(
                len(block["sources"])
                for decision_id in self.structured
                for block in self.front[decision_id]["articles"].values()
            ),
        )

    def test_phase_d_batch_1_is_eight_of_the_structured_decisions(self):
        """The eight decisions this batch moved out of `unverified`, beside
        Phase C's 23, and none of the 37 still held."""
        self.assertEqual(8, len(set(PHASE_D_BATCH_1_IDS)))
        self.assertLessEqual(set(PHASE_D_BATCH_1_IDS), set(self.structured))
        self.assertEqual(23, len(set(self.structured) - set(PHASE_D_BATCH_1_IDS)))
        self.assertEqual(set(), set(PHASE_D_BATCH_1_IDS) & set(self.held))
        self.assertEqual(set(), set(PHASE_D_BATCH_1_IDS) & set(self.omitted))

    def test_a_requirement_established_for_one_edition_asserts_no_other(self):
        """D-42 is NECB 2020 only. NECB 2025 8.4.1.2.(4) states a different
        criterion -- a ceiling of 100 h under Subsection 8.4.4, +10 % or 20 h
        under 8.4.5 -- so the 2020 mapping must not be claimed for it."""
        single = {
            decision_id for decision_id in self.structured
            if any(len(block["sources"]) == 1
                   for block in self.front[decision_id]["articles"].values())
        }
        self.assertEqual({"D-42"}, single)
        meta = self.front["D-42"]
        self.assertEqual(["necb2020"], meta["editions"])
        (block,) = meta["articles"].values()
        self.assertEqual(
            [("necb", "2020", "governing", ["8.4.1.2.(4)"])],
            [(source["code"], source["edition"], source["role"],
              source["references"]) for source in block["sources"]],
        )
        self.assertEqual(
            ["necb2020"],
            [code_id for code_id, cells in self.edition_rows
             if self.linked(cells[1]) == "D-42"],
        )

    def test_migration_keeps_each_title_and_summary_byte_stable(self):
        """A report reads these fields, so representation-only work may not
        amend them while adding its committee metadata."""
        actual = {
            decision_id: hashlib.sha256(
                json.dumps(
                    [
                        self.front[decision_id]["title"],
                        self.front[decision_id]["summary"],
                    ],
                    ensure_ascii=False,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest()
            for decision_id in self.structured
        }
        self.assertEqual(MIGRATED_RUNTIME_SHA256, actual)

    def test_each_migrated_requirement_is_its_legacy_mapping_verbatim(self):
        """Keys in authored order, labels, and each established edition's
        citations in authored order, against the literal tables -- and
        nothing else in a requirement but its `decided`. Phase D mappings
        also include the narrowings and requirement splits recorded by the
        decisions."""
        self.assertEqual(MIGRATED_IDS, tuple(MIGRATED_KEYS))
        self.assertEqual(
            sorted(MIGRATED_REQUIREMENTS),
            sorted({key for keys in MIGRATED_KEYS.values() for key in keys}),
            "the literal table names exactly the requirements in use")
        for decision_id, keys in MIGRATED_KEYS.items():
            meta = self.front[decision_id]
            self.assertEqual(keys, tuple(meta["articles"]), decision_id)
            # Top-level editions are kept as authored; the generator holds
            # them equal to what the governing records derive.
            self.assertEqual(migrated_editions(decision_id), meta["editions"])
            for key in keys:
                label = MIGRATED_REQUIREMENTS[key][0]
                block = meta["articles"][key]
                with self.subTest(decision=decision_id, requirement=key):
                    self.assertEqual(("label", "decided", "sources"),
                                     tuple(block))
                    self.assertEqual(label, block["label"])
                    self.assertEqual(migrated_sources(key), block["sources"])
                    self.assertEqual(
                        [("code", "edition", "role", "references")]
                        * len(block["sources"]),
                        [tuple(source) for source in block["sources"]])

    def test_each_requirement_has_its_own_committee_paraphrase(self):
        """`decided` says what was decided about THIS requirement in THIS
        decision. It is not the summary, the label, the title or a passage of
        the body cut to fit; no two requirement instances share one, not even
        the users of a shared key; and it reproduces no run of the Code's own
        text recorded as evidence for either edition."""
        corpus = authority_runs(AUTHORITY_RUN)
        seen = {}
        for decision_id in self.structured:
            meta = self.front[decision_id]
            body = raw_body(decision_id)
            for key, block in meta["articles"].items():
                decided = block["decided"]
                with self.subTest(decision=decision_id, requirement=key):
                    self.assertEqual(decided.strip(), decided)
                    self.assertNotIn("\n", decided)
                    self.assertGreaterEqual(len(decided.split()), 8)
                    for name, text in (("summary", meta["summary"]),
                                       ("title", meta["title"]),
                                       ("label", block["label"]),
                                       ("body", body)):
                        self.assertNotIn(decided.casefold(), text.casefold(),
                                         "decided is copied from the " + name)
                    self.assertNotIn(block["label"].casefold(),
                                     decided.casefold())
                    self.assertNotIn(decided, seen,
                                     "already used by {}".format(seen.get(decided)))
                    seen[decided] = (decision_id, key)
                    copied = sorted(set(word_runs(decided, AUTHORITY_RUN)) & corpus)
                    self.assertEqual([], copied,
                                     "decided reproduces recorded Code text")
        self.assertEqual(self.REQUIREMENTS, len(seen))

    def test_every_citation_free_decision_is_omitted(self):
        """Not a row, not a link, not a summary anchor, not a held entry."""
        self.assertTrue(self.omitted, "no citation-free decision to test with")
        linked = {self.linked(cells[1]) for _code, cells in self.edition_rows}
        linked |= {self.linked(cells[0]) for cells in self.held_rows}
        anchored = {i.upper() for i in SUMMARY_ANCHOR.findall(self.view)}
        for decision_id in self.omitted:
            with self.subTest(decision=decision_id):
                self.assertNotIn(decision_id, linked | anchored)
                self.assertNotIn(
                    "]({}#{})".format(DECISIONS_DOC.name, decision_id.lower()),
                    self.view)

    def test_every_included_decision_is_present_and_nothing_else_is_linked(self):
        every_link = {i.upper() for i in DECISION_LINK.findall(self.view)}
        self.assertEqual(set(self.included), every_link)
        # Present in the place its class says, and in no other.
        in_editions = {self.linked(cells[1]) for _code, cells in self.edition_rows}
        in_held = {self.linked(cells[0]) for cells in self.held_rows}
        self.assertEqual(set(self.structured) | set(self.established), in_editions)
        self.assertEqual(set(self.held), in_held)
        self.assertEqual(set(), in_editions & in_held)

    def test_a_held_decision_is_never_placed_in_an_edition(self):
        held = set(self.held)
        self.assertTrue(held, "no held decision to test with")
        for code_id, cells in self.edition_rows:
            with self.subTest(code=code_id, row=cells[1][:40]):
                self.assertNotIn(self.linked(cells[1]), held)

    def test_the_held_table_is_the_raw_unverified_decisions_as_recorded(self):
        headings = re.findall(r"^## (.+)$", self.view, re.MULTILINE)
        self.assertEqual(NOT_ATTRIBUTED, headings[-1],
                         "the held decisions are the last section")
        self.assertEqual(
            [self.linked(cells[0]) for cells in self.held_rows], self.held,
            "one row per held decision, in numeric id order")
        for cells in self.held_rows:
            meta = self.front[self.linked(cells[0])]
            with self.subTest(decision=meta["id"]):
                self.assertEqual(4, len(cells))
                self.assertEqual(meta["title"], unescape(cells[1]))
                self.assertEqual([meta["kind"]], code_spans(cells[2]))
                self.assertEqual(meta["articles"]["unverified"],
                                 code_spans(cells[3]),
                                 "citations are listed as recorded, in order")

    def test_each_structured_requirement_is_one_row_per_edition(self):
        """One row per governing source record, with its exact source order."""
        expected = {}
        for decision_id in self.structured:
            for key, block in self.front[decision_id]["articles"].items():
                for source in block["sources"]:
                    if source["role"] == "governing":
                        code_id = codes.resolve(
                            "{}{}".format(source["code"], source["edition"])
                        ).id
                        expected[(code_id, decision_id, key)] = (block, source)
        actual = {}
        for code_id, cells in self.edition_rows:
            identity = (code_id, self.linked(cells[1]), code_spans(cells[2])[-1])
            self.assertNotIn(identity, actual, "a requirement is one row per edition")
            actual[identity] = cells
        self.assertEqual(set(expected), set(actual))
        self.assertEqual(len(self.edition_rows), len(expected))
        for identity, (block, source) in expected.items():
            cells = actual[identity]
            with self.subTest(row=identity):
                self.assertEqual(source["references"], code_spans(cells[0]))
                self.assertEqual(self.front[identity[1]]["title"],
                                 unescape(cells[1].split(") ", 1)[1]))
                self.assertEqual(block["label"],
                                 unescape(cells[2].split("<br>")[0]))
                self.assertEqual(block["decided"], unescape(cells[3]))

    def test_each_migrated_requirement_owns_exactly_its_literal_rows(self):
        """Read off the view against the literal tables, not the sources: one
        row per established edition of each migrated requirement instance,
        each with that edition's citations in authored order, the label, the
        decision's own `decided`, the other edition's citations (a dash where
        only one edition is established) and no other source."""
        label_of = {code_id: codes.resolve(code_id).label
                    for code_id in ("necb2020", "necb2025")}
        expected = {}
        for decision_id, keys in MIGRATED_KEYS.items():
            for key in keys:
                label = MIGRATED_REQUIREMENTS[key][0]
                decided = self.front[decision_id]["articles"][key]["decided"]
                mine = {"necb" + source["edition"]: source["references"]
                        for source in migrated_sources(key)}
                for code_id, references in mine.items():
                    others = [
                        "{}: {}".format(label_of[other_id], ", ".join(
                            "`{}`".format(citation) for citation in other))
                        for other_id, other in mine.items()
                        if other_id != code_id]
                    expected[(code_id, decision_id, key)] = (
                        list(references), label, decided,
                        "<br>".join(others) or "—", "—")
        actual = {}
        for code_id, cells in self.edition_rows:
            identity = (code_id, self.linked(cells[1]), code_spans(cells[2])[-1])
            if identity[1] in MIGRATED_KEYS:
                self.assertNotIn(identity, actual)
                actual[identity] = (code_spans(cells[0]),
                                    unescape(cells[2].split("<br>")[0]),
                                    unescape(cells[3]), cells[4], cells[5])
        self.assertEqual(self.SOURCE_ROWS, len(expected))
        self.assertEqual(expected, actual)

    def test_other_editions_are_same_requirement_governing_sources(self):
        for code_id, cells in self.edition_rows:
            decision_id, key = self.linked(cells[1]), code_spans(cells[2])[-1]
            block = self.front[decision_id]["articles"][key]
            others = [
                source for source in block["sources"]
                if source["role"] == "governing"
                and codes.resolve(
                    "{}{}".format(source["code"], source["edition"])
                ).id != code_id
            ]
            with self.subTest(code=code_id, decision=decision_id, key=key):
                if not others:
                    self.assertEqual("—", cells[4])
                    continue
                self.assertEqual(
                    [
                        reference
                        for source in others
                        for reference in source["references"]
                    ],
                    code_spans(cells[4]),
                )
                for source in others:
                    other = codes.resolve(
                        "{}{}".format(source["code"], source["edition"])
                    )
                    self.assertIn(other.label + ": ", cells[4])
                self.assertNotIn(codes.resolve(code_id).label + ": ", cells[4])
                self.assertEqual("—", cells[5])

    def test_no_concrete_legacy_or_transitional_form_remains(self):
        self.assertEqual([], self.established)
        self.assertNotIn("## Transitional decision summaries\n", self.view)
        self.assertEqual([], SUMMARY_ANCHOR.findall(self.view))
        for decision_id in self.structured:
            for key, block in self.front[decision_id]["articles"].items():
                with self.subTest(decision=decision_id, requirement=key):
                    self.assertEqual(
                        {"label", "decided", "sources"}, set(block),
                    )
                    self.assertEqual(
                        [source["edition"] for source in migrated_sources(key)],
                        [source["edition"] for source in block["sources"]],
                    )
                    self.assertTrue(
                        all(
                            source["code"] == "necb"
                            and source["role"] == "governing"
                            for source in block["sources"]
                        )
                    )

    def test_shared_requirement_keys_keep_one_label_and_mapping(self):
        shared = {}
        for decision_id in self.structured:
            for key, block in self.front[decision_id]["articles"].items():
                shared.setdefault(key, []).append((decision_id, block))
        shared = {key: records for key, records in shared.items()
                  if len(records) > 1}
        self.assertEqual(
            SHARED_KEY_USERS,
            {key: tuple(decision_id for decision_id, _block in records)
             for key, records in shared.items()},
        )
        # No unconverted decision uses a migrated key: a key is one
        # requirement, so it may not be structured in one place and legacy
        # or held in another.
        for decision_id, meta in self.front.items():
            if decision_id not in MIGRATED_KEYS:
                self.assertEqual(set(), set(meta["articles"]) & set(MIGRATED_REQUIREMENTS),
                                 decision_id)
        for key, records in shared.items():
            with self.subTest(requirement=key):
                expected = (
                    records[0][1]["label"],
                    [
                        (
                            source["code"],
                            source["edition"],
                            source["role"],
                            source["references"],
                        )
                        for source in records[0][1]["sources"]
                    ],
                )
                for _decision_id, block in records[1:]:
                    self.assertEqual(
                        expected,
                        (
                            block["label"],
                            [
                                (
                                    source["code"],
                                    source["edition"],
                                    source["role"],
                                    source["references"],
                                )
                                for source in block["sources"]
                            ],
                        ),
                    )

    def test_rows_read_the_provision_number_numerically(self):
        """8.4.4.9 before 8.4.4.10 -- a string sort puts them the other way."""
        by_code = {}
        for code_id, cells in self.edition_rows:
            by_code.setdefault(code_id, []).append(code_spans(cells[0])[0])
        self.assertTrue(by_code)
        for code_id, firsts in by_code.items():
            numbers = [leading_number(span) for span in firsts]
            with self.subTest(code=code_id):
                self.assertGreater(len(firsts), 1)
                self.assertEqual(sorted(numbers), numbers, firsts)

    def test_every_row_has_exactly_the_six_columns(self):
        for code_id, cells in self.edition_rows:
            with self.subTest(code=code_id, row=cells[1][:40]):
                self.assertEqual(6, len(cells))
                self.assertTrue(all(cells))

    def test_every_decision_link_resolves_to_its_log_anchor(self):
        anchors = set(re.findall(r'^<a id="(d-\d+)"></a>$', self.doc, re.MULTILINE))
        links = set(DECISION_LINK.findall(self.view))
        self.assertTrue(links)
        self.assertEqual(set(), links - anchors)

    def test_the_view_states_what_its_source_provenance_and_status_mean(self):
        for heading in ("### Source", "### Provenance", "### Status",
                        "### Reading a row"):
            self.assertIn("\n" + heading + "\n", self.view)
        status = {cells[0] for section, heading, cells in self.rows
                  if section == "Definitions" and heading == "Status"}
        self.assertEqual({"Governing", "Incorporated reference, related",
                          "Transitional", "Not yet attributed"}, status)
        self.assertIn("reproduces no Code text", self.view)

    def test_the_view_is_a_pure_function_of_the_sources(self):
        entries = G.read_sources(SOURCE_DIR)[1]
        reversed_entries = dict(reversed(list(entries.items())))
        self.assertEqual(self.view, G.render_provision_view(entries))
        self.assertEqual(self.view, G.render_provision_view(reversed_entries))
        self.assertEqual(self.view, G.generate(SOURCE_DIR)[2])


#: A legacy per-edition citation list, `necb2020 = [`, at the start of a
#: front-matter line. The structured form never writes one.
LEGACY_LIST_LINE = re.compile(r"^necb\d{4}\s*=", re.MULTILINE)
#: The two legacy holding keys an unconverted decision may still use.
HOLDING_KEYS = ("unverified", "not_applicable")


class TestThePhaseCMigration(unittest.TestCase):
    """Phase C converted every established mapping and Phase D batch 1 eight
    held decisions, read straight from the committed files: no legacy
    per-code-id shape survives in a converted source or registry entry, the
    registry projects each migrated requirement exactly as the literal tables
    say, and the decision log carries none of the new committee metadata."""

    @classmethod
    def setUpClass(cls):
        cls.front = raw_front_matter()
        cls.fronts = {path.stem: path.read_text(encoding="utf-8").split("+++\n")[1]
                      for path in SOURCE_DIR.glob("D-*.md")}
        cls.registry = json.loads(
            PYTHON_REGISTRY.read_text(encoding="utf-8"))["decisions"]
        cls.by_id = {entry["id"]: entry for entry in cls.registry}

    def test_no_source_keeps_a_per_code_id_mapping(self):
        self.assertEqual(set(self.front), set(self.fronts))
        for decision_id, meta in self.front.items():
            articles = meta["articles"]
            with self.subTest(decision=decision_id):
                self.assertIsNone(LEGACY_LIST_LINE.search(self.fronts[decision_id]))
                if decision_id in MIGRATED_KEYS:
                    for block in articles.values():
                        self.assertIsInstance(block, dict)
                        self.assertEqual(("label", "decided", "sources"),
                                         tuple(block))
                    continue
                # Every other decision is held or omitted under ONE holding
                # key, which its `editions` repeats.
                (holding,) = articles
                self.assertIn(holding, HOLDING_KEYS)
                self.assertIsInstance(articles[holding], list)
                self.assertEqual([holding], meta["editions"])
                if holding == "not_applicable":
                    self.assertEqual([], articles[holding])

    def test_no_registry_entry_keeps_a_per_code_id_mapping(self):
        self.assertEqual(list(self.front), [entry["id"] for entry in self.registry])
        for entry in self.registry:
            with self.subTest(decision=entry["id"]):
                if entry["id"] in MIGRATED_KEYS:
                    self.assertEqual(STRUCTURED_FIELDS, tuple(entry))
                    continue
                self.assertEqual(LEGACY_FIELDS, tuple(entry))
                self.assertEqual(entry["editions"], list(entry["articles"]))
                self.assertIn(entry["editions"][0], HOLDING_KEYS)
                self.assertIsInstance(entry["articles"][entry["editions"][0]], list)

    def test_the_registry_projects_each_migrated_requirement_exactly(self):
        """Requirements sorted by key, each the literal mapping plus its own
        `decided`; the runtime fields and `editions` as authored."""
        for decision_id, keys in MIGRATED_KEYS.items():
            entry, meta = self.by_id[decision_id], self.front[decision_id]
            with self.subTest(decision=decision_id):
                self.assertEqual({field: meta[field] for field in RUNTIME_FIELDS},
                                 {field: entry[field] for field in RUNTIME_FIELDS})
                self.assertEqual(migrated_editions(decision_id), entry["editions"])
                expected = []
                for key in sorted(keys):
                    expected.append({
                        "id": key, "label": MIGRATED_REQUIREMENTS[key][0],
                        "decided": meta["articles"][key]["decided"],
                        "sources": migrated_sources(key)})
                self.assertEqual(ordered(expected), ordered(entry["requirements"]))

    def test_the_decision_log_carries_no_committee_metadata(self):
        """The log renders titles, kinds and bodies. A `decided` reaching it
        would mean the representation change moved a document it may not."""
        doc = DECISIONS_DOC.read_text(encoding="utf-8")
        for decision_id, keys in MIGRATED_KEYS.items():
            for key in keys:
                with self.subTest(decision=decision_id, requirement=key):
                    self.assertNotIn(
                        self.front[decision_id]["articles"][key]["decided"], doc)


class TestTheMigrationCannotRunAgain(unittest.TestCase):
    def test_split_refuses_once_the_sources_exist(self):
        """``--split`` bootstrapped the sources; it must never overwrite them."""
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "--split"],
            cwd=REPO_ROOT, capture_output=True, text=True, check=False)
        self.assertEqual(1, result.returncode,
                         "--split must fail closed against real sources")
        self.assertIn("refusing to split", result.stdout + result.stderr)

    def test_the_retired_toc_generator_is_gone(self):
        """One writer. A second one would let the two drift apart silently."""
        self.assertFalse((PYTHON_ROOT / "scripts" / "generate_decisions_toc.py").exists())


if __name__ == "__main__":
    unittest.main()
