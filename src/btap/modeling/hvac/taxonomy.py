"""The HVAC catalogue TAXONOMY: what each system is, in terms an engineer browses.

The catalogue grew from six sources (NECB, CBECS, campus, NECB ECMs, the NECB
reference heat pumps, generic), each with its own naming style, and its 21
`family` values follow those origins rather than system types. This module
places every row in a tree an engineer recognises —

    Category > System type > variants

— and derives the FACETS that tell variants apart, by equipment ROLE: what the
air handler does, what the zone terminals do, what the plant is
(docs/plans/HVAC_TAXONOMY_PLAN.md, Astra's review finding 7).

Facts come from what each row's BUILDER constructs (`systems/*.py`, with the
builder's own defaults for any field a row omits), verified family by family
against that source by an independent read (Fable, 2026-11-25). A config this
module cannot describe faithfully RAISES `TaxonomyUnsupported` rather than
returning a plausible wrong name.

Nothing here imports the OpenStudio SDK or `btap.codes`: discovery stays usable
without OpenStudio, and NECB APPLICABILITY ("which NECB System uses this row")
is the codes layer's to say — only the row's NECB *lineage* lives here.

`mint_id()` proposes a model-safe ID from the facets. IDs are minted ONCE and
then stored and frozen; changing this grammar never renames an existing system
(Astra finding 8). `display()` is the plain-English name people see; it never
reaches a model.
"""

from __future__ import annotations

import json
import pathlib
import re

from btap.modeling.hvac import catalog


class TaxonomyUnsupported(ValueError):
    """A build config the taxonomy cannot yet describe faithfully."""


# --- the tree --------------------------------------------------------------

#: Category key -> title. Practical browsing groups, not distribution-medium
#: claims: the medium is its own facet (`distribution`).
CATEGORIES = {
    "central": "Central ducted systems",
    "oa_plus_zone": "Zone terminals + outdoor-air unit",
    "zone_only": "Zone equipment only",
    "heating_only": "Heating only",
    "ventilation_only": "Ventilation only",
    "process": "Process and special",
}

#: System type key -> (category, title, abbreviation). The key is also the
#: leading token of an ID. Order is display order.
TYPES = {
    "psz": ("central", "Packaged single-zone rooftop unit", "PSZ"),
    "pvav": ("central", "Packaged VAV with reheat", "PVAV"),
    "vav": ("central", "VAV with reheat", "VAV"),
    "ddvav": ("central", "Dual-duct VAV", "DDVAV"),
    "cvrh": ("central", "Constant-volume reheat air handler", "CAV reheat"),
    "furnace": ("central", "Forced-air gas furnace", "Forced-air gas furnace"),
    "hv": ("central", "Heating and ventilating unit", "H&V"),
    "splitac": ("central", "Split-system air conditioner", "Split AC"),
    "evap": ("central", "Direct evaporative cooler", "DEC"),
    # Terminal FIRST: an engineer finds these by the zone terminal (phylroy,
    # 2026-11-26). The NECB System 2/5 fan-coil unit is a MIXED-air handler
    # (sizing.json `necb_mau`, all_outdoor_air false), so it is a "central air
    # handler", not a make-up air unit; only MAU + PTAC is 100% outdoor air.
    "mau-ptac": ("oa_plus_zone", "PTAC + make-up air unit", "PTAC + MAU"),
    "doas-ptac": ("oa_plus_zone", "PTAC + DOAS", "PTAC + DOAS"),
    "mau-fc4": ("oa_plus_zone", "Fan coils, four-pipe + central air handler", "FPFC + AHU"),
    "mau-fc2": ("oa_plus_zone", "Fan coils, two-pipe + central air handler", "TPFC + AHU"),
    "doas-fc4": ("oa_plus_zone", "Fan coils, four-pipe + DOAS", "FPFC + DOAS"),
    "doas-pthp": ("oa_plus_zone", "Heat pumps, packaged terminal + DOAS", "PTHP + DOAS"),
    "doas-wshp": ("oa_plus_zone", "Heat pumps, water-loop + DOAS", "WSHP + DOAS"),
    "doas-vrf": ("oa_plus_zone", "VRF heat recovery + DOAS", "VRF-HR + DOAS"),
    "doas-acb": ("oa_plus_zone", "Chilled beams, active + DOAS", "ACB + DOAS"),
    "doas-pcb": ("oa_plus_zone", "Chilled beams, passive + DOAS", "PCB + DOAS"),
    "ptac": ("zone_only", "Packaged terminal air conditioner", "PTAC"),
    "pthp": ("zone_only", "Packaged terminal heat pump", "PTHP"),
    "windowac": ("zone_only", "Window air conditioner", "Window AC"),
    "vrf": ("zone_only", "VRF heat recovery", "VRF-HR"),
    "wshp": ("zone_only", "Water-loop heat pumps", "WSHP"),
    "bb": ("heating_only", "Baseboard heating", "Baseboards"),
    "uh": ("heating_only", "Unit heaters", "Unit heaters"),
    "doas": ("ventilation_only", "Dedicated outdoor air system", "DOAS"),
    "zone-erv": ("ventilation_only", "Zone energy recovery ventilators", "Zone ERV"),
    "crah": ("process", "Computer-room air handler", "CRAH"),
}

# --- facets ----------------------------------------------------------------

#: Every facet and its CLOSED vocabulary. "none" is an explicit absence.
FACETS = {
    "category": tuple(CATEGORIES),
    "system_type": tuple(TYPES),
    # the air handler (central unit, MAU or DOAS); "none" when there is none
    "ahu_heating": ("gas", "electric", "hot_water", "ashp", "ccashp", "none"),
    "ahu_backup": ("gas", "electric", "none"),
    "ahu_cooling": ("dx", "chilled_water", "evaporative", "none"),
    "outdoor_air": ("mixed", "dedicated", "none"),
    "vent_heat_recovery": ("erv", "hrv", "none"),
    # the zone terminals
    "terminal": ("none", "diffuser", "vav_reheat", "cv_reheat", "dual_duct",
                 "ptac", "pthp", "window_ac", "fc4", "fc2", "vrf", "wshp",
                 "active_beam", "passive_beam", "unit_heater", "erv"),
    "terminal_heating": ("gas", "electric", "hot_water", "heat_pump", "none"),
    "terminal_cooling": ("dx", "chilled_water", "heat_pump", "none"),
    "terminal_outdoor_air": ("yes", "no"),
    "reheat": ("hot_water", "electric", "gas", "none"),
    "zone_heating": ("hw_baseboard", "elec_baseboard", "none"),
    # the plant
    "hw_plant": ("gas_boiler", "electric_boiler", "district", "gshp", "awhp"),
    "chw_plant": ("water_cooled_chiller", "air_cooled_chiller", "district", "awhp"),
    "chiller_kind": ("scroll", "centrifugal", "screw", "reciprocating", "none"),
    "heat_rejection": ("cooling_tower", "fluid_cooler", "ground", "none"),
    # the whole system
    "distribution": ("all_air", "air_and_water", "all_water", "unitary", "none"),
    "scope": ("per_zone", "shared", "multizone"),
    "humidity_control": ("yes", "no"),
    "changeover": ("simultaneous", "seasonal", "heating_only", "cooling_only",
                   "ventilation_only"),
    "refrigerant_heat_recovery": ("yes", "no"),
    # lineage (provenance, not applicability)
    "necb_lineage": ("1", "2", "3", "4", "5", "6", "none"),
    "ecm": ("hs08", "hs09", "hs11", "hs12", "hs13", "hs14", "hs15", "hs16", "none"),
    "origin": ("necb", "necb_reference_hp", "necb_ecm", "cbecs", "campus", "generic"),
}

#: Facets whose value is a LIST (a system may carry several; empty = none).
MULTI = frozenset({"hw_plant", "chw_plant"})

_FUEL = {"Gas": "gas", "NaturalGas": "gas", "Electric": "electric",
         "Electricity": "electric", "Hot Water": "hot_water",
         "HotWater": "hot_water", "Water": "hot_water", "None": "none", None: "none"}

_CHILLER = {"Scroll": "scroll", "Centrifugal": "centrifugal",
            "Rotary Screw": "screw", "Reciprocating": "reciprocating"}

_ERV_DATA = pathlib.Path(__file__).resolve().parent / "data" / "energy_recovery.json"


def _fuel(value):
    if value not in _FUEL:
        raise TaxonomyUnsupported(f"unknown fuel/medium value {value!r}")
    return _FUEL[value]


def _baseboard(config, default=None):
    return {"Hot Water": "hw_baseboard", "Electric": "elec_baseboard",
            "None": "none", None: "none"}[config.get("baseboard_type", default)]


def _hw_plant(config):
    """builder.py: a hot-water loop only when `needs_boiler`, on `boiler_fuel`
    (default natural gas), or district when `hw_source` says so."""
    if not config.get("needs_boiler"):
        return []
    if config.get("hw_source") == "district":
        return ["district"]
    if config.get("hw_source") == "awhp":
        # plant_loops: an air-to-water heat pump with ONE backup boiler
        return ["awhp", f"{_fuel(config.get('boiler_fuel', 'NaturalGas'))}_boiler"]
    return [f"{_fuel(config.get('boiler_fuel', 'NaturalGas'))}_boiler"]


def _chw(config):
    """builder.py + plant_loops.chilled_water: a chiller loop only when
    `needs_chiller` — water-cooled (WITH a cooling tower) unless `chw_source`
    says air-cooled or district. `chiller_type` (default scroll) is the kind
    the efficiency pass reads."""
    if not config.get("needs_chiller"):
        return [], "none", "none"
    source = config.get("chw_source", "water_cooled")
    if source == "district":
        return ["district"], "none", "none"
    kind = _CHILLER[config.get("chiller_type", "Scroll")]
    if source == "air_cooled":
        return ["air_cooled_chiller"], kind, "none"
    return ["water_cooled_chiller"], kind, "cooling_tower"


def _erv(config):
    """base_system.attach_oa_system: an exchanger on ANY family with outdoor
    air when `needs_erv`; ERV when it moves moisture, HRV when it does not."""
    if not config.get("needs_erv"):
        return "none"
    latent = config.get("erv_latent_effectiveness")
    if latent is None:
        data = json.loads(_ERV_DATA.read_text(encoding="utf-8"))
        profile = config.get("erv_profile") or data["default"]
        latent = data["profiles"][profile].get("erv_latent_effectiveness", 0.0)
    return "erv" if float(latent) > 0.0 else "hrv"


def _lineage(config):
    abbr = str(config.get("sys_abbr") or "")
    # Lineage, not applicability: ECM rows carry `sys_1` only for the pipe-name
    # convention, so only NECB-origin rows claim a System number.
    if config.get("origin") in (None, "necb_reference_hp") and re.fullmatch(r"sys_[1-6]", abbr):
        return abbr[-1]
    return "none"


def _ecm(config):
    match = re.match(r"(hs\d\d)_", str(config.get("legacy_name") or config.get("name") or ""))
    return match.group(1) if match else "none"


def _base(config, system_type, **values):
    """A facet dict with every facet present; `values` overrides the blanks."""
    chw, kind, rejection = _chw(config)
    facets = {
        "category": TYPES[system_type][0], "system_type": system_type,
        "ahu_heating": "none", "ahu_backup": "none", "ahu_cooling": "none",
        "outdoor_air": "none", "vent_heat_recovery": _erv(config),
        "terminal": "none", "terminal_heating": "none", "terminal_cooling": "none",
        "terminal_outdoor_air": "no", "reheat": "none",
        "zone_heating": _baseboard(config),
        "hw_plant": _hw_plant(config), "chw_plant": chw, "chiller_kind": kind,
        "heat_rejection": rejection, "distribution": "none", "scope": "per_zone",
        "humidity_control": "no", "changeover": "simultaneous",
        "refrigerant_heat_recovery": "no",
        "necb_lineage": _lineage(config), "ecm": _ecm(config),
        "origin": config.get("origin") or "necb",
    }
    facets.update(values)
    return facets


def _refuse(config, *keys):
    for key in keys:
        if config.get(key):
            raise TaxonomyUnsupported(
                f"{config.get('id')!r}: `{key}` is not described by the taxonomy yet")


# --- per family: what the builder builds -------------------------------------

def _psz(c):
    heat_type = c.get("heating_coil_type")
    ashp = c.get("heat_source") == "ashp" or heat_type == "DX"   # psz.py: 'DX' alias
    return _base(
        c, "psz",
        ahu_heating="ashp" if ashp else _fuel(heat_type),
        ahu_backup=_fuel(c.get("supp_htg_fuel", "Electric")) if ashp else "none",  # psz.py default
        ahu_cooling="dx", outdoor_air="mixed", terminal="diffuser",
        # psz.py: `per_zone` builds one unit per zone; otherwise ONE unit serves
        # every zone it is given, tracking one control zone.
        scope="per_zone" if c.get("per_zone") else "shared")


def _vav(c):
    heat = _fuel(c.get("heating_coil_type"))
    dx = c.get("cooling_type") == "dx"
    return _base(
        c, "pvav" if dx else "vav",
        # vav_reheat.py: ONE coil type for the central coil and every reheat coil
        ahu_heating=heat, reheat=heat, terminal_heating=heat,
        ahu_cooling="dx" if dx else "chilled_water", outdoor_air="mixed",
        terminal="vav_reheat", scope="multizone")


def _fan_coils(c, *, in_composite=False):
    two_pipe = c.get("fan_coil_type", "FPFC") == "TPFC"
    mau = c.get("mau", True)
    if not mau and not in_composite:
        raise TaxonomyUnsupported(
            f"{c.get('id')!r}: fan coils with no make-up air unit and no DOAS")
    cooling_only = str(c.get("heating")) == "none"      # D-39 System 5 variant
    facets = _base(
        c, ("mau-fc2" if two_pipe else "mau-fc4") if mau else "doas-fc4",
        terminal="fc2" if two_pipe else "fc4",
        terminal_heating="none" if cooling_only else "hot_water",
        terminal_cooling="chilled_water",
        # fan_coils.py never zeroes the fan coil's outdoor air
        terminal_outdoor_air="yes", scope="multizone",
        changeover=("cooling_only" if cooling_only
                    else "seasonal" if two_pipe else "simultaneous"))
    if mau:
        facets.update(
            ahu_heating="none" if cooling_only else _fuel(c.get("mau_heating_coil_type", "Gas")),
            ahu_cooling="dx" if c.get("mau_cooling_type", "DX") == "DX" else "chilled_water",
            # build_oa_system with `necb_mau` sizing (all_outdoor_air False):
            # a mixed-air unit, whatever NECB's "MAU" label suggests
            outdoor_air="mixed")
    return facets


def _mau_ptac(c):
    supp = _fuel(c.get("supp_htg_fuel", "Electric"))
    if c.get("reference_hp"):
        # mau_ptac.py, reference branch: a MIXED-air ASHP air handler with
        # constant-volume reheat terminals on `supp_htg_fuel` — no PTAC.
        return _base(
            c, "cvrh", ahu_heating="ashp", ahu_cooling="dx", outdoor_air="mixed",
            terminal="cv_reheat", reheat=supp, terminal_heating=supp,
            scope="multizone")
    ptac_heat = _fuel(c.get("ptac_heating_type")) if c.get("ptac_heating_type") else "none"
    return _base(
        c, "mau-ptac",
        # the MAU always carries a DX coil (mau_ptac.py, non-reference branch)
        ahu_heating=_fuel(c.get("mau_heating_coil_type", "Electric")),
        ahu_cooling="dx", outdoor_air="dedicated", terminal="ptac",
        terminal_heating=ptac_heat, terminal_cooling="dx", scope="multizone")


def _zone_terminal(c):
    unit = c["unit_type"]
    if unit == "pthp":
        return _base(c, "pthp", terminal="pthp", terminal_heating="heat_pump",
                     terminal_cooling="heat_pump", terminal_outdoor_air="yes")
    heat = _fuel(c.get("heating_type")) if unit == "ptac" else "none"
    return _base(c, "windowac" if unit == "window_ac" else "ptac",
                 terminal="window_ac" if unit == "window_ac" else "ptac",
                 terminal_heating=heat, terminal_cooling="dx",
                 terminal_outdoor_air="yes")


def _furnace(c):
    heats, cools = c.get("heating", True), c.get("cooling", False)
    heat = _fuel(c.get("heating_type", "Gas")) if heats else "none"
    oa = "mixed" if c.get("ventilation", True) else "none"
    cooling = "dx" if cools else "none"
    changeover = ("simultaneous" if heats and cools
                  else "heating_only" if heats else "cooling_only")
    if c.get("reheat"):
        return _base(c, "cvrh", ahu_heating=heat, ahu_cooling=cooling,
                     outdoor_air=oa, terminal="cv_reheat", reheat=_fuel(c["reheat"]),
                     terminal_heating=_fuel(c["reheat"]), scope="multizone",
                     changeover=changeover)
    if heats and heat == "gas":
        system_type = "furnace"
    elif cools:
        system_type = "splitac"
    else:
        system_type = "hv"
    return _base(c, system_type, ahu_heating=heat, ahu_cooling=cooling,
                 outdoor_air=oa, terminal="diffuser",
                 scope="per_zone" if c.get("per_zone", True) else "shared",
                 changeover=changeover)


def _ecm_air(c, default_eqpt):
    return c.get("air_eqpt", default_eqpt)


def _family_facets(c, *, in_composite=False):
    family = c["family"]
    _refuse(c, "needs_zone_erv")
    if family == "psz":
        return _psz(c)
    if family == "vav_reheat":
        return _vav(c)
    if family == "fan_coils":
        return _fan_coils(c, in_composite=in_composite)
    if family == "mau_ptac":
        return _mau_ptac(c)
    if family == "zone_terminal":
        return _zone_terminal(c)
    if family == "furnace":
        return _furnace(c)
    if family == "baseboards":
        return _base(c, "bb", changeover="heating_only")
    if family == "unit_heaters":
        return _base(c, "uh", terminal="unit_heater",
                     terminal_heating=_fuel(c.get("heating_type", "Gas")),
                     changeover="heating_only")
    if family == "evap_cooler":
        # evap_cooler.py: one air loop PER ZONE — fan, direct evaporative
        # cooler, outdoor-air system — the same shape as a per-zone furnace
        return _base(c, "evap", ahu_cooling="evaporative", outdoor_air="mixed",
                     terminal="diffuser", changeover="cooling_only")
    if family == "vrf":
        return _base(c, "vrf", terminal="vrf", terminal_heating="heat_pump",
                     terminal_cooling="heat_pump",
                     terminal_outdoor_air="yes" if c.get("zone_ventilation", True) else "no",
                     refrigerant_heat_recovery="yes")
    if family == "wshp":
        ground = c.get("heat_rejection") == "ground"
        facets = _base(
            c, "wshp", terminal="wshp", terminal_heating="heat_pump",
            terminal_cooling="heat_pump",
            terminal_outdoor_air="yes" if c.get("ventilation") else "no",
            heat_rejection=c.get("heat_rejection", "fluid_cooler"))
        # wshp.py: the condenser loop carries a boiler — except on the ground
        # loop — whatever `needs_boiler` says.
        facets["hw_plant"] = [] if ground else [
            f"{_fuel(c.get('boiler_fuel', 'NaturalGas'))}_boiler"]
        return facets
    if family == "doas":
        return _base(c, "doas", ahu_heating=_fuel(c.get("heating_type", "Electric")),
                     ahu_cooling="dx", outdoor_air="dedicated", terminal="diffuser",
                     scope="shared", changeover="ventilation_only")
    if family == "zone_ervs":
        return _base(c, "zone-erv", terminal="erv", terminal_outdoor_air="yes",
                     vent_heat_recovery="erv", changeover="ventilation_only")
    if family == "chilled_beams":
        active = c.get("beam_type") == "Active"
        # chilled_beams.py: a dehumidifying DOAS (DX + electric) feeds the beams
        return _base(c, "doas-acb" if active else "doas-pcb",
                     ahu_heating="electric", ahu_cooling="dx",
                     outdoor_air="dedicated",
                     terminal="active_beam" if active else "passive_beam",
                     terminal_cooling="chilled_water", humidity_control="yes",
                     scope="multizone")
    if family == "dual_duct":
        return _base(c, "ddvav", ahu_heating="hot_water", ahu_cooling="chilled_water",
                     outdoor_air="mixed", terminal="dual_duct", scope="multizone")
    if family == "crah":
        # crah.py: ONE air handler at a fixed supply temperature, a diffuser
        # per zone, no zone control
        return _base(c, "crah", ahu_cooling="chilled_water",
                     outdoor_air="mixed" if c.get("ventilation") else "none",
                     terminal="diffuser", humidity_control="yes", scope="shared",
                     changeover="cooling_only")
    if family == "doas_pthp":
        return _base(c, "doas-pthp", ahu_heating="ashp",
                     ahu_backup=_fuel(c.get("supp_htg_fuel", "Electric")),
                     ahu_cooling="dx", outdoor_air="dedicated", terminal="pthp",
                     terminal_heating="heat_pump", terminal_cooling="heat_pump",
                     scope="multizone")
    if family == "ecm_ashp_baseboard":
        if c.get("vent_type", "doas") != "doas":
            raise TaxonomyUnsupported(
                f"{c.get('id')!r}: ashp_baseboard with vent_type "
                f"{c.get('vent_type')!r} builds a VAV, not DOAS + PTAC")
        # ashp_baseboard.py ('doas'): the PTAC's heat section is always off
        return _base(c, "doas-ptac", ahu_heating=_ecm_air(c, "ashp"),
                     ahu_backup=_fuel(c.get("supp_htg_fuel", "Electric")),
                     ahu_cooling="dx", outdoor_air="dedicated", terminal="ptac",
                     terminal_cooling="dx", scope="multizone",
                     zone_heating=_baseboard(c, default="Electric"))
    if family == "ecm_doas_vrf":
        return _base(c, "doas-vrf", ahu_heating=_ecm_air(c, "ccashp"),
                     ahu_backup=_fuel(c.get("supp_htg_fuel", "Electric")),
                     ahu_cooling="dx", outdoor_air="dedicated", terminal="vrf",
                     terminal_heating="heat_pump", terminal_cooling="heat_pump",
                     refrigerant_heat_recovery="yes", scope="multizone")
    if family == "ecm_hp_fancoils":
        gshp = c.get("plant_type", "cawhp") == "gshp"
        hydronic = _ecm_air(c, "hydronic") == "hydronic"
        facets = _base(
            c, "doas-fc4",
            ahu_heating="hot_water" if hydronic else "ashp",
            ahu_backup="none" if hydronic else _fuel(c.get("supp_htg_fuel", "None")),
            ahu_cooling="chilled_water" if hydronic else "dx",
            outdoor_air="dedicated", terminal="fc4", terminal_heating="hot_water",
            terminal_cooling="chilled_water", scope="multizone",
            heat_rejection="ground" if gshp else "none")
        # hp_plant_fancoils.py: heat-pump-led plants with boiler backup on
        # `boiler_fuel` (default electricity)
        facets["hw_plant"] = ["gshp" if gshp else "awhp",
                              f"{_fuel(c.get('boiler_fuel', 'Electricity'))}_boiler"]
        facets["chw_plant"] = (["water_cooled_chiller", "air_cooled_chiller"] if gshp
                               else ["awhp"])
        facets["chiller_kind"] = "none"
        return facets
    if family == "composite":
        return _composite(c)
    raise TaxonomyUnsupported(f"no taxonomy rule for family {family!r}")


def _part_configs(c):
    out = []
    for part in c["parts"]:
        key = part.get("id") or part["name"]
        merged = dict(catalog.resolve(key))
        merged.update(part.get("config") or {})
        out.append(merged)
    return out


def _union_plants(target, facets_list):
    """Every part's plant reaches the composite's facets — a DOAS or a
    baseboard part that needs a boiler builds one (Fable 1G)."""
    for key in ("hw_plant", "chw_plant"):
        seen = []
        for f in facets_list:
            for value in f[key]:
                if value not in seen:
                    seen.append(value)
        target[key] = seen
    for key in ("chiller_kind", "heat_rejection"):
        values = [f[key] for f in facets_list if f[key] != "none"]
        target[key] = values[0] if values else "none"


def _composite(c):
    parts = _part_configs(c)
    families = [p["family"] for p in parts]
    part_facets = [_family_facets(p, in_composite=True) for p in parts]
    origin = c.get("origin") or "necb"
    if "doas" in families:
        doas = part_facets[families.index("doas")]
        zone_index = next(i for i, fam in enumerate(families) if fam != "doas")
        zone_type = {"wshp": "doas-wshp", "vrf": "doas-vrf", "fan_coils": "doas-fc4"}[
            families[zone_index]]
        merged = dict(part_facets[zone_index])
        for key in ("ahu_heating", "ahu_backup", "ahu_cooling", "outdoor_air",
                    "vent_heat_recovery"):
            merged[key] = doas[key]
        merged.update(category=TYPES[zone_type][0], system_type=zone_type,
                      scope="multizone")
    elif families == ["furnace", "baseboards"]:      # 'Residential AC with baseboard electric'
        merged = _furnace(parts[0])
        merged["changeover"] = "simultaneous"
    elif families == ["evap_cooler", "baseboards"]:  # 'Direct evap coolers with baseboard electric'
        merged = dict(part_facets[0])
        merged["changeover"] = "simultaneous"
    else:
        raise TaxonomyUnsupported(f"no taxonomy rule for composite parts {families}")
    for f in part_facets:
        if f["zone_heating"] != "none":
            merged["zone_heating"] = f["zone_heating"]
    _union_plants(merged, part_facets)
    merged.update(origin=origin, necb_lineage=_lineage(c), ecm=_ecm(c))
    return merged


_WATER_TERMINALS = {"fc4", "fc2", "active_beam", "passive_beam"}
_PACKAGED_TERMINALS = {"ptac", "pthp", "window_ac", "vrf", "wshp"}


def _distribution(f):
    """ASHRAE Handbook's split, read from what CONDITIONS the zones: zone
    refrigerant units make a system unitary whatever ventilates it; water
    terminals or hot-water baseboards add water to an air system."""
    water = (f["terminal"] in _WATER_TERMINALS or f["zone_heating"] == "hw_baseboard"
             or (f["terminal"] == "unit_heater" and f["terminal_heating"] == "hot_water"))
    if f["terminal"] in _PACKAGED_TERMINALS or (
            f["terminal"] == "unit_heater" and f["terminal_heating"] != "hot_water"):
        return "unitary"
    central = f["ahu_heating"] != "none" or f["ahu_cooling"] != "none"
    if central:
        return "air_and_water" if water else "all_air"
    if water:
        return "all_water"
    return "none"


def facets(config):
    """The facets of a catalogue row or a resolved build config (a row merged
    with any runtime overrides — the facets describe what is BUILT)."""
    out = _family_facets(dict(config))
    out["distribution"] = _distribution(out)
    for key, value in out.items():
        allowed = FACETS[key]
        values = value if key in MULTI else [value]
        bad = [v for v in values if v not in allowed]
        if bad:
            raise TaxonomyUnsupported(f"facet {key}={bad} not in its vocabulary {allowed}")
    return out


# --- names -----------------------------------------------------------------

_HEAT_TOKEN = {"gas": "gas", "electric": "elec", "hot_water": "hw", "ashp": "ashp",
               "ccashp": "ccashp", "none": None}
_PLANT_TOKEN = {"gas_boiler": "gasboiler", "electric_boiler": "elecboiler",
                "district": "district", "gshp": "gshp", "awhp": "awhp"}
_KIND_TOKEN = {"scroll": "scroll", "centrifugal": "centrif", "screw": "screw",
               "reciprocating": "recip"}

#: The cooling each type implies, so its ID need not repeat it. A heat-pump
#: air handler implies DX whatever its type.
_IMPLIED_COOLING = {"psz": "dx", "pvav": "dx", "vav": "chilled_water",
                    "mau-ptac": "dx", "doas-ptac": "dx", "mau-fc4": "dx",
                    "mau-fc2": "dx", "doas-pthp": "dx", "doas-vrf": "dx",
                    "doas-wshp": "dx", "doas-acb": "dx", "doas-pcb": "dx",
                    "doas": "dx", "ddvav": "chilled_water", "doas-fc4": "dx",
                    "evap": "evaporative", "crah": "chilled_water"}
_IMPLIED_SCOPE = {"psz": "shared", "furnace": "per_zone", "hv": "per_zone",
                  "splitac": "per_zone", "evap": "per_zone", "crah": "shared",
                  "doas": "shared"}


def mint_id(config):
    """Propose a model-safe ID for a row: lowercase, digits and hyphens.

    Used to MINT an ID once; the stored ID is then frozen. A segment is left
    out only when it is "none" or the value the type implies, so two different
    configurations never mint the same ID (the catalogue test checks that).
    """
    f = facets(config)
    t = f["system_type"]
    tokens = [t]
    heat = _HEAT_TOKEN[f["ahu_heating"]]
    if heat:
        tokens.append(heat)
    if f["ahu_backup"] != "none":
        tokens.append(f"{_HEAT_TOKEN[f['ahu_backup']]}supp")
    implied = "dx" if f["ahu_heating"] in ("ashp", "ccashp") else _IMPLIED_COOLING.get(t)
    if f["ahu_cooling"] not in ("none", implied):
        tokens.append({"chilled_water": "chw", "dx": "dx", "evaporative": "evapc"}[
            f["ahu_cooling"]])
    if f["reheat"] not in ("none", f["ahu_heating"]):
        tokens.append(f"{_HEAT_TOKEN[f['reheat']]}rh")
    if t in ("mau-ptac", "ptac") and f["terminal_heating"] != "none":
        tokens.append(f"{_HEAT_TOKEN[f['terminal_heating']]}ptac")
    if t == "uh":
        tokens.append(_HEAT_TOKEN[f["terminal_heating"]])
    if f["changeover"] == "cooling_only" and t in ("mau-fc4", "mau-fc2", "doas-fc4"):
        tokens.append("coolonly")
    if f["zone_heating"] != "none":
        tokens.append({"hw_baseboard": "hwbb", "elec_baseboard": "elecbb"}[
            f["zone_heating"]])
    if f["vent_heat_recovery"] != "none" and t != "zone-erv":
        tokens.append(f["vent_heat_recovery"])
    if t == "vrf" and f["terminal_outdoor_air"] == "no":
        tokens.append("nooa")
    if t in ("furnace", "splitac", "hv", "cvrh", "evap") and f["outdoor_air"] == "none":
        tokens.append("nooa")
    if t == "crah" and f["outdoor_air"] != "none":
        tokens.append("oa")
    if config.get("hw_source") == "awhp":
        # plant_loops' heat-pump plant: the boiler is a BACKUP, said in fewer
        # characters than a primary boiler's token (ids stay <= 40)
        tokens += ["gasbu" if p == "gas_boiler" else "elecbu" if p == "electric_boiler"
                   else _PLANT_TOKEN[p] for p in f["hw_plant"]]
    else:
        tokens += [_PLANT_TOKEN[p] for p in f["hw_plant"]]
    # A heat-pump PLANT from hp_plant_fancoils.py brings its own chilled-water
    # side and ground loop; a water-cooled chiller brings its cooling tower.
    # The `hw_source: awhp` plant heats only, so its chiller still counts.
    hp_plant = ({"gshp", "awhp"} & set(f["hw_plant"])) and config.get("hw_source") != "awhp"
    if not hp_plant:
        for plant in f["chw_plant"]:
            kind = _KIND_TOKEN.get(f["chiller_kind"], "")
            tokens.append({"water_cooled_chiller": f"{kind}chiller",
                           "air_cooled_chiller": f"ac{kind}chiller",
                           "district": "districtchw", "awhp": "awhpchw"}[plant])
        if f["heat_rejection"] not in ("none", "cooling_tower") and not (
                t == "wshp" and f["heat_rejection"] == "fluid_cooler"):
            tokens.append({"ground": "groundloop", "fluid_cooler": "fluidcooler"}[
                f["heat_rejection"]])
        if f["heat_rejection"] == "cooling_tower" and t in ("wshp", "doas-wshp"):
            tokens.append("tower")
    if f["scope"] != _IMPLIED_SCOPE.get(t, f["scope"]):
        tokens.append({"per_zone": "perzone", "shared": "shared",
                       "multizone": "multizone"}[f["scope"]])
    if config.get("hw_source") == "awhp" and config.get("hw_supply") == "boiler_lift":
        # the retrofit arrangement builds a different plant (82 C loop, the
        # heat pump preheating) from the default low-temperature one
        tokens.append("lift")
    # No lineage token: NECB Systems 3 and 4 build identical equipment
    # (psz.py), so their eight twin rows were RETIRED as duplicates (D-113)
    # rather than told apart. Lineage is a facet, never part of an id.
    return "-".join(tokens)


_HEAT_WORDS = {"gas": "gas heat", "electric": "electric heat",
               "hot_water": "hot water heat", "ashp": "air-source heat pump",
               "ccashp": "cold-climate air-source heat pump"}
_COOL_WORDS = {"dx": "DX cooling", "chilled_water": "chilled water cooling",
               "evaporative": "direct evaporative cooling"}
_TERMINAL_WORDS = {"ptac": "PTACs", "pthp": "packaged terminal heat pumps",
                   "window_ac": "window AC units", "fc4": "four-pipe fan coils",
                   "fc2": "two-pipe changeover fan coils",
                   "vrf": "VRF terminals", "wshp": "water-source heat pump units",
                   "active_beam": "active chilled beams",
                   "passive_beam": "passive chilled beams",
                   "unit_heater": "unit heaters", "erv": "one ERV per zone"}
_PLANT_WORDS = {"gas_boiler": "gas boiler", "electric_boiler": "electric boiler",
                "district": "district heating", "gshp": "ground-source heat pump",
                "awhp": "air-to-water heat pump"}


def _chw_words(f):
    words = []
    for plant in f["chw_plant"]:
        kind = f["chiller_kind"]
        words.append({
            "water_cooled_chiller": f"water-cooled {kind} chiller with cooling tower"
            if kind != "none" else "water-cooled chiller",
            "air_cooled_chiller": f"air-cooled {kind} chiller" if kind != "none"
            else "air-cooled chiller",
            "district": "district cooling",
            "awhp": "air-to-water heat pump chilled water"}[plant])
    return words


def display(config):
    """The plain-English name people see. ASCII; never written into a model."""
    head, body, plant = display_parts(config)
    text = head
    if body:
        text += f": {', '.join(body)}"
    if plant:
        text += f" - {', '.join(plant)}"
    return text


#: The unit that carries the air-handler phrases in the zone-terminal
#: category, so "DOAS (electric heat; DX cooling)" cannot be read as the
#: terminals' own heating and cooling (Fable, naming review).
_OA_UNIT = {"mau-ptac": "MAU", "mau-fc4": "AHU", "mau-fc2": "AHU"}

_HEAT_PUMP_HEAT = ("ashp", "ccashp")


def display_parts(config):
    """``(head, body phrases, plant phrases)`` — the pieces `display` joins.
    The catalogue tree labels a variant by the phrases its siblings do not
    share, so it needs them unjoined. No phrase contains ", "."""
    f = facets(config)
    t = f["system_type"]
    _, title, abbr = TYPES[t]
    if t == "psz":
        # ASHRAE 90.1 Appendix G names: PSZ-AC, or PSZ-HP for a heat pump.
        abbr = "PSZ-HP" if f["ahu_heating"] in _HEAT_PUMP_HEAT else "PSZ-AC"
    head = title if abbr == title else f"{title} ({abbr})"
    ahu = []
    heat_pump = f["ahu_heating"] in _HEAT_PUMP_HEAT and f["ahu_cooling"] == "dx"
    if f["ahu_heating"] != "none":
        word = _HEAT_WORDS[f["ahu_heating"]]
        if heat_pump:
            # the heat pump IS the DX cooling; saying both read as two units
            word += " (heats and cools)"
        if f["ahu_backup"] != "none":
            word += f" with {f['ahu_backup']} backup"
        ahu.append(word)
    if f["reheat"] != "none" and f["reheat"] == f["ahu_heating"] and ahu:
        # vav_reheat.py: one coil type serves the central coil AND the reheat
        ahu[0] = f"{f['reheat'].replace('_', ' ')} heat and reheat"
    elif f["reheat"] != "none":
        ahu.append(f"{f['reheat'].replace('_', ' ')} reheat")
    if f["ahu_cooling"] != "none" and not heat_pump:
        ahu.append(_COOL_WORDS[f["ahu_cooling"]])
    elif f["changeover"] == "heating_only" and f["category"] == "central":
        ahu.append("no cooling")
    if f["outdoor_air"] == "none" and f["category"] in ("central", "process"):
        ahu.append("no outdoor air")
    if f["vent_heat_recovery"] != "none" and t != "zone-erv":
        ahu.append(f["vent_heat_recovery"].upper())
    if f["category"] == "oa_plus_zone" and ahu:
        unit = _OA_UNIT.get(t, "DOAS")
        ahu = [f"{unit} ({'; '.join(ahu)})"]
    zone = []
    if f["terminal"] in _TERMINAL_WORDS:
        words = _TERMINAL_WORDS[f["terminal"]]
        if f["terminal"] == "ptac" and f["terminal_heating"] != "none":
            words = f"{words} with {f['terminal_heating'].replace('_', ' ')} coils"
        elif f["terminal"] == "ptac":
            words = f"cooling-only {words}"
        elif f["terminal"] in ("fc4", "fc2") and f["changeover"] == "cooling_only":
            words = f"cooling-only {words}"
        elif f["terminal"] == "unit_heater":
            words = f"{f['terminal_heating'].replace('_', ' ')} {words}"
        if f["terminal_outdoor_air"] == "yes" and f["terminal"] != "erv":
            words += " that ventilate"
        zone.append(words)
        if f["category"] == "zone_only" and f["terminal_outdoor_air"] == "no":
            # wshp.py zeroes the units' outdoor air; siblings say "that ventilate"
            zone.append("no outdoor air")
    if t in ("vrf", "doas-vrf") and f["refrigerant_heat_recovery"] != "yes":
        raise TaxonomyUnsupported(
            f"{config.get('id')!r}: the VRF type titles say 'heat recovery'; a VRF "
            "row without it needs its own type title first")
    if f["refrigerant_heat_recovery"] == "yes" and t not in ("vrf", "doas-vrf"):
        zone.append("refrigerant heat recovery")      # the VRF titles already say it
    if f["zone_heating"] != "none":
        zone.append({"hw_baseboard": "hot water baseboards",
                     "elec_baseboard": "electric baseboards"}[f["zone_heating"]])
    if f["humidity_control"] == "yes":
        # crah.py / doas.py: a maximum-humidity-ratio setpoint; no humidifier
        zone.append("dehumidification (humidity high limit)")
    if f["scope"] == "per_zone" and t == "psz":
        zone.append("one unit per zone")
    if f["scope"] == "shared":
        zone.append("serves several zones from one control zone")
    hw = [_PLANT_WORDS[p] for p in f["hw_plant"]]
    chw = _chw_words(f)
    if "awhp" in f["hw_plant"] and "awhp" in f["chw_plant"]:
        hw = [w if w != _PLANT_WORDS["awhp"] else "air-to-water heat pump (heating and cooling)"
              for w in hw]
        chw = [w for w in chw if w != "air-to-water heat pump chilled water"]
    if any(p in f["hw_plant"] for p in ("awhp", "gshp")):
        # heat-pump-led plants with boiler backup (hp_plant_fancoils.py and
        # plant_loops' `awhp` source)
        hw = [f"{w} backup" if w.endswith(" boiler") else w for w in hw]
    if config.get("hw_source") == "awhp":
        supply = config.get("hw_supply", "low_temperature")
        # the loop's design temperature: plant_loops.HEAT_PUMP_LOOP_RESET_DEFAULTS
        # unless `hw_controls` overrides it (Fable, review of #250)
        controls = config.get("hw_controls") or {}
        if not isinstance(controls, dict):
            raise ValueError(f"{config.get('id')}: hw_controls must be a mapping")
        reset = controls.get("loop_reset_c")
        if reset is None:
            loop_c = 60.0 if supply == "low_temperature" else 82.0
        elif (isinstance(reset, (list, tuple)) and len(reset) == 2
              and all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in reset)):
            loop_c = float(reset[0])
        else:
            raise ValueError(f"{config.get('id')}: hw_controls loop_reset_c must be "
                             f"a pair of numbers, not {reset!r}")
        hw = [w if w != _PLANT_WORDS["awhp"] else
              (f"air-to-water heat pump ({loop_c:g} C loop)" if supply == "low_temperature"
               else f"air-to-water heat pump preheat ({loop_c:g} C loop; boiler lifts)")
              for w in hw]
    plant = hw + chw
    if t in ("wshp", "doas-wshp"):
        plant = [p.replace("gas boiler", "condenser-loop gas boiler") for p in plant]
    if f["heat_rejection"] not in ("none", "cooling_tower"):
        if f["heat_rejection"] == "ground" and t == "doas-fc4":
            # hp_plant_fancoils.py `_build_glhx_loop`: district heating and
            # cooling in series stand in for the ground loop
            plant.append("ground loop (modelled as district heating and cooling)")
        else:
            plant.append({"fluid_cooler": "evaporative fluid cooler",
                          "ground": "ground loop"}[f["heat_rejection"]])
    elif f["heat_rejection"] == "cooling_tower" and not f["chw_plant"]:
        plant.append("cooling tower")
    return head, ahu + zone, plant


def tree(rows=None):
    """`{category: {system_type: [row, ...]}}` in display order."""
    rows = list(rows if rows is not None else catalog.rows())
    out = {key: {} for key in CATEGORIES}
    for row in rows:
        f = facets(row)
        out[f["category"]].setdefault(f["system_type"], []).append(row)
    return {
        cat: {t: types[t] for t in TYPES if t in types}
        for cat, types in out.items() if types
    }
