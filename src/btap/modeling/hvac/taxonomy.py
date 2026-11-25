"""The HVAC catalogue TAXONOMY: what each system is, in terms an engineer browses.

The catalogue grew from six sources (NECB, CBECS, campus, NECB ECMs, the NECB
reference heat pumps, generic), each with its own naming style, and its 21
`family` values follow those origins rather than system types. This module
places every row in a tree an engineer recognises —

    Category > System type > variants

— and derives the FACETS that tell variants apart, by equipment ROLE: what the
air handler does, what the zone terminals do, what the plant is
(docs/plans/HVAC_TAXONOMY_PLAN.md, Astra's review finding 7).

Facts come from the row's own fields and from what its BUILDER does, read off
`btap/modeling/hvac/systems/*.py` and pinned by tests that re-read that source.
Nothing here imports the OpenStudio SDK or `btap.codes`: discovery stays usable
without OpenStudio, and NECB APPLICABILITY ("which NECB System uses this row")
is the codes layer's to say — only the row's NECB *lineage* lives here.

`mint_id()` proposes a model-safe ID from the facets. IDs are minted ONCE and
then stored and frozen; changing this grammar never renames an existing system
(Astra finding 8). `display()` is the plain-English name people see; it never
reaches a model.
"""

from __future__ import annotations

import re

from btap.modeling.hvac import catalog

# --- the tree --------------------------------------------------------------

#: Category key -> title. Practical browsing groups, not distribution-medium
#: claims: the medium is its own facet (`distribution`), because a central air
#: handler with hot-water baseboards is air-and-water however it is grouped.
CATEGORIES = {
    "central": "Central ducted systems",
    "oa_plus_zone": "Outdoor-air unit + zone terminals",
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
    "vav": ("central", "Built-up VAV with reheat", "VAV"),
    "ddvav": ("central", "Dual-duct VAV", "DDVAV"),
    "cvrh": ("central", "Constant-volume reheat air handler", "CV reheat"),
    "furnace": ("central", "Furnace", "Furnace"),
    "hv": ("central", "Heating and ventilating unit", "H&V"),
    "splitac": ("central", "Split-system air conditioner", "Split AC"),
    "mau-ptac": ("oa_plus_zone", "Make-up air unit + PTAC", "MAU + PTAC"),
    "doas-ptac": ("oa_plus_zone", "DOAS + PTAC", "DOAS + PTAC"),
    "mau-fc4": ("oa_plus_zone", "Make-up air unit + four-pipe fan coils", "MAU + FPFC"),
    "mau-fc2": ("oa_plus_zone", "Make-up air unit + two-pipe fan coils", "MAU + TPFC"),
    "doas-fc4": ("oa_plus_zone", "DOAS + four-pipe fan coils", "DOAS + FPFC"),
    "doas-pthp": ("oa_plus_zone", "DOAS + packaged terminal heat pumps", "DOAS + PTHP"),
    "doas-wshp": ("oa_plus_zone", "DOAS + water-source heat pumps", "DOAS + WSHP"),
    "doas-vrf": ("oa_plus_zone", "DOAS + variable refrigerant flow", "DOAS + VRF"),
    "doas-acb": ("oa_plus_zone", "DOAS + active chilled beams", "DOAS + ACB"),
    "doas-pcb": ("oa_plus_zone", "DOAS + passive chilled beams", "DOAS + PCB"),
    "ptac": ("zone_only", "Packaged terminal air conditioner", "PTAC"),
    "pthp": ("zone_only", "Packaged terminal heat pump", "PTHP"),
    "windowac": ("zone_only", "Window air conditioner", "Window AC"),
    "vrf": ("zone_only", "Variable refrigerant flow", "VRF"),
    "wshp": ("zone_only", "Water-source heat pumps", "WSHP"),
    "evap": ("zone_only", "Direct evaporative coolers", "Evap"),
    "bb": ("heating_only", "Baseboard heating", "Baseboards"),
    "uh": ("heating_only", "Unit heaters", "Unit heaters"),
    "doas": ("ventilation_only", "Dedicated outdoor air system", "DOAS"),
    "zone-erv": ("ventilation_only", "Zone energy recovery ventilators", "Zone ERV"),
    "crah": ("process", "Computer-room air handler", "CRAH"),
}

# --- facets ----------------------------------------------------------------

#: Every facet and its CLOSED vocabulary. "none" is an explicit absence;
#: nothing here is ever "unknown" — a row whose fact cannot be read raises
#: (`row_facts.CatalogFactError`) rather than being described by a guess.
FACETS = {
    "category": tuple(CATEGORIES),
    "system_type": tuple(TYPES),
    # the air handler (central AHU, MAU or DOAS); "none" when there is none
    "ahu_heating": ("gas", "electric", "hot_water", "ashp", "ccashp", "none"),
    "ahu_backup": ("gas", "electric", "none"),
    "ahu_cooling": ("dx", "chilled_water", "none"),
    "outdoor_air": ("mixed", "dedicated", "none"),
    "vent_heat_recovery": ("erv", "hrv", "none"),
    # the zone terminals
    "terminal": ("none", "diffuser", "vav_reheat", "cv_reheat", "dual_duct",
                 "ptac", "pthp", "window_ac", "fc4", "fc2", "vrf", "wshp",
                 "active_beam", "passive_beam", "unit_heater", "evap", "erv"),
    "terminal_heating": ("gas", "electric", "hot_water", "heat_pump", "none"),
    "terminal_cooling": ("dx", "chilled_water", "heat_pump", "evaporative", "none"),
    "terminal_outdoor_air": ("yes", "no"),
    "reheat": ("hot_water", "electric", "gas", "none"),
    "zone_heating": ("hw_baseboard", "elec_baseboard", "none"),
    # the plant
    "hw_plant": ("gas_boiler", "electric_boiler", "district", "gshp", "awhp"),
    "chw_plant": ("scroll_water_cooled", "centrifugal_water_cooled",
                  "screw_water_cooled", "reciprocating_water_cooled",
                  "scroll_air_cooled", "district", "water_cooled_chiller",
                  "air_cooled_chiller", "awhp"),
    "heat_rejection": ("fluid_cooler", "cooling_tower", "ground", "none"),
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


def _fuel(value):
    if value not in _FUEL:
        raise ValueError(f"unknown fuel/medium value {value!r}")
    return _FUEL[value]


def _baseboard(config):
    return {"Hot Water": "hw_baseboard", "Electric": "elec_baseboard",
            "None": "none", None: "none"}[config.get("baseboard_type")]


def _hw_plant(config):
    """The hot-water plant a row's builder makes (`plant_loops.hot_water`):
    a boiler on `boiler_fuel` (default natural gas), or district."""
    if not config.get("needs_boiler"):
        return []
    if config.get("hw_source") == "district":
        return ["district"]
    return [f"{_fuel(config.get('boiler_fuel', 'NaturalGas'))}_boiler"]


def _chw_plant(config):
    """The chilled-water plant (`plant_loops.chilled_water`): a chiller of
    `chiller_type` (default scroll), water-cooled unless `chw_source` says
    air-cooled, or district."""
    if not config.get("needs_chiller"):
        return []
    source = config.get("chw_source", "water_cooled")
    if source == "district":
        return ["district"]
    kind = _CHILLER[config.get("chiller_type", "Scroll")]
    return [f"{kind}_{'air' if source == 'air_cooled' else 'water'}_cooled"]


def _lineage(config):
    abbr = str(config.get("sys_abbr") or "")
    origin = config.get("origin")
    # Lineage, not applicability: ECM rows carry `sys_1` only for the pipe-name
    # convention, so only NECB-origin rows claim a System number.
    if origin in (None, "necb_reference_hp") and re.fullmatch(r"sys_[1-6]", abbr):
        return abbr[-1]
    return "none"


def _ecm(config):
    match = re.match(r"(hs\d\d)_", str(config.get("legacy_name") or config.get("name") or ""))
    return match.group(1) if match else "none"


def _base(config, system_type, **values):
    """A facet dict with every facet present; `values` overrides the blanks."""
    facets = {
        "category": TYPES[system_type][0], "system_type": system_type,
        "ahu_heating": "none", "ahu_backup": "none", "ahu_cooling": "none",
        "outdoor_air": "none", "vent_heat_recovery": "none",
        "terminal": "none", "terminal_heating": "none", "terminal_cooling": "none",
        "terminal_outdoor_air": "no", "reheat": "none",
        "zone_heating": _baseboard(config),
        "hw_plant": _hw_plant(config), "chw_plant": _chw_plant(config),
        "heat_rejection": "none", "distribution": "none", "scope": "per_zone",
        "humidity_control": "no", "changeover": "simultaneous",
        "refrigerant_heat_recovery": "no",
        "necb_lineage": _lineage(config), "ecm": _ecm(config),
        "origin": config.get("origin") or "necb",
    }
    facets.update(values)
    return facets


def _erv(config):
    if not config.get("needs_erv"):
        return "none"
    return "erv" if float(config.get("erv_latent_effectiveness", 0.0)) > 0.0 else "hrv"


# --- per family: the builder's facts -----------------------------------------

def _psz(c):
    ashp = c.get("heat_source") == "ashp"
    return _base(
        c, "psz",
        ahu_heating="ashp" if ashp else _fuel(c.get("heating_coil_type")),
        ahu_backup=_fuel(c.get("supp_htg_fuel")) if ashp else "none",
        ahu_cooling="dx", outdoor_air="mixed", terminal="diffuser",
        # psz.py: `per_zone` builds one unit per zone; otherwise ONE unit serves
        # every zone it is given, controlled from one zone.
        scope="per_zone" if c.get("per_zone") else "shared")


def _vav(c):
    heat = _fuel(c.get("heating_coil_type"))
    return _base(
        c, "pvav" if c.get("sys_abbr") == "pvav" else "vav",
        # vav_reheat.py: ONE coil type for the central coil and every reheat coil
        ahu_heating=heat, reheat=heat,
        ahu_cooling="dx" if c.get("cooling_type") == "dx" else "chilled_water",
        outdoor_air="mixed", vent_heat_recovery=_erv(c), terminal="vav_reheat",
        terminal_heating=heat, scope="multizone")


def _fan_coils(c):
    two_pipe = c.get("fan_coil_type") == "TPFC"
    mau = c.get("mau", True)
    facets = _base(
        c, ("mau-fc2" if two_pipe else "mau-fc4") if mau else "doas-fc4",
        terminal="fc2" if two_pipe else "fc4", terminal_heating="hot_water",
        terminal_cooling="chilled_water",
        # fan_coils.py: two-pipe coils heat OR cool on seasonal availability
        changeover="seasonal" if two_pipe else "simultaneous")
    if mau:
        facets.update(
            ahu_heating=_fuel(c.get("mau_heating_coil_type", "Gas")),
            ahu_cooling="dx" if c.get("mau_cooling_type") == "DX" else "chilled_water",
            outdoor_air="dedicated")
    return facets


def _mau_ptac(c):
    if c.get("reference_hp"):
        # mau_ptac.py, reference branch: a MIXED-air ASHP air handler with
        # constant-volume reheat terminals on `supp_htg_fuel` — no PTAC.
        return _base(
            c, "cvrh", ahu_heating="ashp", ahu_cooling="dx", outdoor_air="mixed",
            terminal="cv_reheat", reheat=_fuel(c.get("supp_htg_fuel", "Electric")),
            terminal_heating=_fuel(c.get("supp_htg_fuel", "Electric")),
            scope="multizone")
    ptac_heat = _fuel(c.get("ptac_heating_type")) if c.get("ptac_heating_type") else "none"
    return _base(
        c, "mau-ptac",
        # the MAU always carries a DX coil (mau_ptac.py, non-reference branch)
        ahu_heating=_fuel(c.get("mau_heating_coil_type", "Electric")),
        ahu_cooling="dx", outdoor_air="dedicated", terminal="ptac",
        terminal_heating=ptac_heat, terminal_cooling="dx")


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
    shared = c.get("per_zone", True) is False
    oa = "mixed" if c.get("ventilation", True) else "none"
    if c.get("reheat"):
        return _base(c, "cvrh", ahu_heating=heat, outdoor_air=oa,
                     terminal="cv_reheat", reheat=_fuel(c["reheat"]),
                     terminal_heating=_fuel(c["reheat"]), scope="multizone",
                     changeover="heating_only")
    system_type = ("furnace" if heat == "gas" else "hv") if heats else "splitac"
    return _base(c, system_type, ahu_heating=heat,
                 ahu_cooling="dx" if cools else "none", outdoor_air=oa,
                 terminal="diffuser", scope="shared" if shared else "per_zone",
                 changeover=("simultaneous" if heats and cools
                             else "heating_only" if heats else "cooling_only"))


def _single(c, system_type, **values):
    return _base(c, system_type, **values)


def _family_facets(c):
    family = c["family"]
    if family == "psz":
        return _psz(c)
    if family == "vav_reheat":
        return _vav(c)
    if family == "fan_coils":
        return _fan_coils(c)
    if family == "mau_ptac":
        return _mau_ptac(c)
    if family == "zone_terminal":
        return _zone_terminal(c)
    if family == "furnace":
        return _furnace(c)
    if family == "baseboards":
        return _single(c, "bb", changeover="heating_only")
    if family == "unit_heaters":
        return _single(c, "uh", terminal="unit_heater",
                       terminal_heating=_fuel(c.get("heating_type", "Gas")),
                       changeover="heating_only")
    if family == "evap_cooler":
        return _single(c, "evap", terminal="evap", terminal_cooling="evaporative",
                       terminal_outdoor_air="yes", changeover="cooling_only")
    if family == "vrf":
        return _single(c, "vrf", terminal="vrf", terminal_heating="heat_pump",
                       terminal_cooling="heat_pump",
                       terminal_outdoor_air="yes" if c.get("zone_ventilation", True) else "no",
                       refrigerant_heat_recovery="yes")
    if family == "wshp":
        ground = c.get("heat_rejection") == "ground"
        facets = _single(
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
        return _single(c, "doas", ahu_heating=_fuel(c.get("heating_type", "Electric")),
                       ahu_cooling="dx", outdoor_air="dedicated", terminal="diffuser",
                       changeover="ventilation_only")
    if family == "zone_ervs":
        return _single(c, "zone-erv", terminal="erv", terminal_outdoor_air="yes",
                       vent_heat_recovery="erv", changeover="ventilation_only")
    if family == "chilled_beams":
        active = c.get("beam_type") == "Active"
        # chilled_beams.py: a dehumidifying DOAS (DX + electric) feeds the beams
        return _single(c, "doas-acb" if active else "doas-pcb",
                       ahu_heating="electric", ahu_cooling="dx",
                       outdoor_air="dedicated",
                       terminal="active_beam" if active else "passive_beam",
                       terminal_cooling="chilled_water", humidity_control="yes")
    if family == "dual_duct":
        return _single(c, "ddvav", ahu_heating="hot_water", ahu_cooling="chilled_water",
                       outdoor_air="mixed", terminal="dual_duct", scope="multizone")
    if family == "crah":
        return _single(c, "crah", ahu_cooling="chilled_water",
                       outdoor_air="mixed" if c.get("ventilation") else "none",
                       terminal="diffuser", humidity_control="yes",
                       changeover="cooling_only")
    if family == "doas_pthp":
        return _single(c, "doas-pthp", ahu_heating="ashp",
                       ahu_backup=_fuel(c.get("supp_htg_fuel", "Electric")),
                       ahu_cooling="dx", outdoor_air="dedicated", terminal="pthp",
                       terminal_heating="heat_pump", terminal_cooling="heat_pump")
    if family == "ecm_ashp_baseboard":
        # ashp_baseboard.py ('doas'): the PTAC's heat section is always off
        return _single(c, "doas-ptac", ahu_heating=c["air_eqpt"],
                       ahu_backup=_fuel(c.get("supp_htg_fuel", "Electric")),
                       ahu_cooling="dx", outdoor_air="dedicated", terminal="ptac",
                       terminal_cooling="dx")
    if family == "ecm_doas_vrf":
        return _single(c, "doas-vrf", ahu_heating=c["air_eqpt"],
                       ahu_backup=_fuel(c.get("supp_htg_fuel", "Electric")),
                       ahu_cooling="dx", outdoor_air="dedicated", terminal="vrf",
                       terminal_heating="heat_pump", terminal_cooling="heat_pump",
                       refrigerant_heat_recovery="yes")
    if family == "ecm_hp_fancoils":
        gshp = c.get("plant_type") == "gshp"
        hydronic = c.get("air_eqpt") == "hydronic"
        facets = _single(
            c, "doas-fc4",
            ahu_heating="hot_water" if hydronic else "ashp",
            ahu_backup="none" if hydronic else _fuel(c.get("supp_htg_fuel", "Electric")),
            ahu_cooling="chilled_water" if hydronic else "dx",
            outdoor_air="dedicated", terminal="fc4", terminal_heating="hot_water",
            terminal_cooling="chilled_water",
            heat_rejection="ground" if gshp else "none")
        # hp_plant_fancoils.py: heat-pump-led plants with electric boiler backup
        facets["hw_plant"] = ["gshp" if gshp else "awhp", "electric_boiler"]
        facets["chw_plant"] = (["water_cooled_chiller", "air_cooled_chiller"] if gshp
                               else ["awhp"])
        return facets
    if family == "composite":
        return _composite(c)
    raise ValueError(f"no taxonomy rule for family {family!r}")


def _part_configs(c):
    out = []
    for part in c["parts"]:
        key = part.get("id") or part["name"]
        merged = dict(catalog.resolve(key))
        merged.update(part.get("config") or {})
        out.append(merged)
    return out


def _composite(c):
    parts = _part_configs(c)
    by_family = {p["family"]: p for p in parts}
    facets = [_family_facets(p) for p in parts]
    if "doas" in by_family:
        doas = next(f for f, p in zip(facets, parts) if p["family"] == "doas")
        zone = next(f for f, p in zip(facets, parts) if p["family"] != "doas")
        zone_type = {"wshp": "doas-wshp", "vrf": "doas-vrf", "fan_coils": "doas-fc4"}[
            next(p["family"] for p in parts if p["family"] != "doas")]
        merged = dict(zone)
        for key in ("ahu_heating", "ahu_backup", "ahu_cooling", "outdoor_air",
                    "vent_heat_recovery"):
            merged[key] = doas[key]
        merged.update(category=TYPES[zone_type][0], system_type=zone_type,
                      origin=c.get("origin") or "necb",
                      necb_lineage=_lineage(c), ecm=_ecm(c))
        return merged
    if "furnace" in by_family:          # 'Residential AC with baseboard electric'
        base = _furnace(by_family["furnace"])
        bb = by_family["baseboards"]
        base.update(zone_heating=_baseboard(bb), system_type="splitac",
                    category=TYPES["splitac"][0], changeover="simultaneous",
                    origin=c.get("origin") or "necb")
        return base
    if "evap_cooler" in by_family:      # 'Direct evap coolers with baseboard electric'
        base = _family_facets(by_family["evap_cooler"])
        base.update(zone_heating=_baseboard(by_family["baseboards"]),
                    changeover="simultaneous", origin=c.get("origin") or "necb")
        return base
    raise ValueError(f"no taxonomy rule for composite {c.get('name')!r}")


def _distribution(f):
    central = f["ahu_heating"] != "none" or f["ahu_cooling"] != "none"
    water = (f["terminal"] in ("fc4", "fc2", "active_beam", "passive_beam")
             or f["zone_heating"] == "hw_baseboard"
             or f["terminal_heating"] == "hot_water")
    packaged = f["terminal"] in ("ptac", "pthp", "window_ac", "vrf", "wshp", "evap",
                                 "unit_heater")
    if central:
        return "air_and_water" if water else "all_air"
    if water:
        return "all_water"
    if packaged:
        return "unitary"
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
            raise ValueError(f"facet {key}={bad} not in its vocabulary {allowed}")
    return out


# --- names -----------------------------------------------------------------

_HEAT_TOKEN = {"gas": "gas", "electric": "elec", "hot_water": "hw", "ashp": "ashp",
               "ccashp": "ccashp", "none": None}
_PLANT_TOKEN = {"gas_boiler": "gasboiler", "electric_boiler": "elecboiler",
                "district": "district", "gshp": "gshp", "awhp": "awhp"}


def _chw_token(value):
    if value == "district":
        return "districtchw"
    if value in ("water_cooled_chiller", "air_cooled_chiller", "awhp"):
        return {"water_cooled_chiller": "wcchiller", "air_cooled_chiller": "acchiller",
                "awhp": "awhpchw"}[value]
    kind, cooled = value.split("_", 1)
    short = {"centrifugal": "centrif", "reciprocating": "recip"}.get(kind, kind)
    return f"{'ac' if cooled == 'air_cooled' else ''}{short}chiller"


#: What each type implies, so its ID need not repeat it.
_IMPLIED_COOLING = {"psz": "dx", "pvav": "dx", "vav": "chilled_water",
                    "mau-ptac": "dx", "doas-ptac": "dx", "mau-fc4": "dx",
                    "mau-fc2": "dx", "doas-pthp": "dx", "doas-vrf": "dx",
                    "doas-wshp": "dx", "doas-acb": "dx", "doas-pcb": "dx",
                    "doas": "dx", "ddvav": "chilled_water", "cvrh": "dx",
                    "doas-fc4": "dx"}
_IMPLIED_SCOPE = {"psz": "shared", "furnace": "per_zone", "hv": "per_zone",
                  "splitac": "per_zone"}


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
    implied = _IMPLIED_COOLING.get(t)
    if f["ahu_cooling"] not in ("none", implied):
        tokens.append({"chilled_water": "chw", "dx": "dx"}[
            f["ahu_cooling"]])
    if f["reheat"] not in ("none", f["ahu_heating"]):
        tokens.append(f"{_HEAT_TOKEN[f['reheat']]}rh")
    if t in ("mau-ptac", "ptac") and f["terminal_heating"] not in ("none",):
        tokens.append(f"{_HEAT_TOKEN[f['terminal_heating']]}ptac")
    if t == "uh":
        tokens.append(_HEAT_TOKEN[f["terminal_heating"]])
    if f["zone_heating"] != "none":
        tokens.append({"hw_baseboard": "hwbb", "elec_baseboard": "elecbb"}[
            f["zone_heating"]])
    if f["vent_heat_recovery"] != "none" and t != "zone-erv":
        tokens.append(f["vent_heat_recovery"])
    if t == "vrf" and f["terminal_outdoor_air"] == "no":
        tokens.append("nooa")
    if t in ("furnace", "splitac", "hv") and f["outdoor_air"] == "none":
        tokens.append("nooa")
    tokens += [_PLANT_TOKEN[p] for p in f["hw_plant"]]
    # A heat-pump PLANT (hp_plant_fancoils.py) brings its own chilled-water
    # side and, for the ground-source plant, its ground loop: naming them again
    # only lengthens the ID.
    hp_plant = {"gshp", "awhp"} & set(f["hw_plant"])
    if not hp_plant:
        tokens += [_chw_token(p) for p in f["chw_plant"]]
    if hp_plant:
        pass
    elif f["heat_rejection"] not in ("none", "fluid_cooler") or (
            t != "wshp" and f["heat_rejection"] == "fluid_cooler"):
        tokens.append({"cooling_tower": "tower", "ground": "groundloop",
                       "fluid_cooler": "fluidcooler"}[f["heat_rejection"]])
    if f["scope"] != _IMPLIED_SCOPE.get(t, f["scope"]):
        tokens.append({"per_zone": "perzone", "shared": "shared",
                       "multizone": "multizone"}[f["scope"]])
    if f["necb_lineage"] == "4":
        # NECB Systems 3 and 4 build identical equipment (psz.py); the System 4
        # rows are told apart by PROVENANCE, not by an invented component.
        tokens.append("necbs4")
    return "-".join(tokens)


_HEAT_WORDS = {"gas": "gas heat", "electric": "electric heat",
               "hot_water": "hot water heat", "ashp": "air-source heat pump",
               "ccashp": "cold-climate air-source heat pump"}
_COOL_WORDS = {"dx": "DX cooling", "chilled_water": "chilled water cooling"}
_TERMINAL_WORDS = {"ptac": "PTACs", "pthp": "packaged terminal heat pumps",
                   "window_ac": "window AC units", "fc4": "four-pipe fan coils",
                   "fc2": "two-pipe fan coils (seasonal changeover)",
                   "vrf": "VRF terminals", "wshp": "water-to-air heat pumps",
                   "active_beam": "active chilled beams",
                   "passive_beam": "passive chilled beams",
                   "unit_heater": "unit heaters", "evap": "direct evaporative coolers",
                   "erv": "zone energy recovery ventilators",
                   "vav_reheat": "VAV reheat terminals",
                   "cv_reheat": "constant-volume reheat terminals",
                   "dual_duct": "dual-duct terminals"}
_PLANT_WORDS = {"gas_boiler": "gas boiler", "electric_boiler": "electric boiler",
                "district": "district hot water", "gshp": "ground-source heat pump",
                "awhp": "air-to-water heat pump"}


def _chw_words(value):
    if value == "district":
        return "district chilled water"
    if value in ("water_cooled_chiller", "air_cooled_chiller"):
        return value.replace("_", " ").replace("cooled chiller", "cooled chiller")
    if value == "awhp":
        return "air-to-water heat pump chilled water"
    kind, cooled = value.split("_", 1)
    return f"{cooled.replace('_', '-')} {kind} chiller"


def display(config):
    """The plain-English name people see. ASCII; never written into a model."""
    f = facets(config)
    _, title, abbr = TYPES[f["system_type"]]
    head = title if abbr == title else f"{title} ({abbr})"
    ahu = []
    if f["ahu_heating"] != "none":
        word = _HEAT_WORDS[f["ahu_heating"]]
        if f["ahu_backup"] != "none":
            word += f" with {f['ahu_backup']} backup"
        ahu.append(word)
    if f["ahu_cooling"] != "none":
        ahu.append(_COOL_WORDS[f["ahu_cooling"]])
    if f["reheat"] != "none" and f["reheat"] == f["ahu_heating"] and ahu:
        # vav_reheat.py: one coil type serves the central coil AND the reheat
        ahu[0] = f"{f['reheat'].replace('_', ' ')} heat and reheat"
    elif f["reheat"] != "none":
        ahu.append(f"{f['reheat'].replace('_', ' ')} reheat")
    if f["outdoor_air"] == "none" and f["system_type"] in ("furnace", "splitac", "hv", "crah"):
        ahu.append("no outdoor air")
    if f["vent_heat_recovery"] != "none":
        ahu.append(f["vent_heat_recovery"].upper())
    zone = []
    if f["terminal"] not in ("none", "diffuser", "vav_reheat", "cv_reheat", "dual_duct"):
        words = _TERMINAL_WORDS[f["terminal"]]
        if f["terminal"] == "ptac" and f["terminal_heating"] != "none":
            words = f"{f['terminal_heating'].replace('_', ' ')}-heated {words}"
        elif f["terminal"] == "ptac":
            words += " (cooling only)"
        elif f["terminal"] == "unit_heater":
            words = f"{f['terminal_heating'].replace('_', ' ')} {words}"
        zone.append(words)
    if f["terminal"] == "vrf" and f["terminal_outdoor_air"] == "no":
        zone.append("terminals not ventilating")
    if f["zone_heating"] != "none":
        zone.append({"hw_baseboard": "hot water baseboards",
                     "elec_baseboard": "electric baseboards"}[f["zone_heating"]])
    if f["humidity_control"] == "yes":
        zone.append("humidity control")
    if f["scope"] == "per_zone" and f["system_type"] in ("psz",):
        zone.append("one unit per zone")
    if f["scope"] == "shared" and f["system_type"] not in ("psz",):
        zone.append("one unit for several zones")
    plant = [_PLANT_WORDS[p] for p in f["hw_plant"]] + [_chw_words(p) for p in f["chw_plant"]]
    if f["heat_rejection"] != "none":
        plant.append({"fluid_cooler": "fluid cooler", "cooling_tower": "cooling tower",
                      "ground": "ground loop"}[f["heat_rejection"]])
    text = head
    body = ", ".join(ahu + zone)
    if body:
        text += f": {body}"
    if plant:
        text += f" - {', '.join(plant)}"
    if f["necb_lineage"] == "4":
        text += " (NECB System 4 form, same equipment as System 3)"
    return text


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
