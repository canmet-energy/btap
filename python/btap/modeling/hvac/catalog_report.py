"""Self-contained HTML catalog of EVERY system this gem can build. For each
catalog row the system is actually BUILT on the bundled 5-zone fixture and
its real topology is extracted, so the diagrams cannot drift from what the
builders assemble ("build-and-extract", never hand-drawn schematics).

UX: a master-detail single page. A sticky, searchable left sidebar lists all
systems grouped by family; the right pane shows ONLY the selected system,
with one TAB per loop (plus a zone-equipment tab). Every system's full detail
is embedded but hidden — selection/tab switching is plain inline JS, so the
file stays one self-contained document.

Loops are drawn as a VERTICAL CASCADE matching the OpenStudio Application's
own GridItem.cpp layout: the SUPPLY equipment as a horizontal row on TOP, a
labelled center connector band ("Supply Equipment" / "Demand Equipment"),
then the DEMAND side on the BOTTOM as a splitter -> parallel branches stacked
vertically -> mixer, closed by left/right risers with flow arrows so it reads
as circulation. Every component + demand cell carries a native SVG <title>
for a hover tooltip.

The whole report is one self-contained document: inline CSS, inline SVG and
inline JS, no external requests of any kind (no CDN, no <link>, no remote
src/href/@import/url(), no web fonts) — a test asserts this. Inline <script>
and <style> make no network requests and are the mechanism here.

This file deliberately mirrors the approach of btap-necb's
report/{model_query,svg,diagrams,html}.rb but is REIMPLEMENTED self-contained
here: this gem sits BELOW btap-necb in the dependency graph and
must not depend on it.
"""

from __future__ import annotations

import math
import re
from importlib import resources
from pathlib import Path

import openstudio

from btap._compat import esc, ruby_round, sorted_by_name
from btap.modeling.hvac import builder, canonical, catalog
from btap.modeling.hvac.catalog_icons import ICON_DATA, ICON_FOR_IDD
from btap.modeling.hvac.components import coils

# The bundled 5-zone seed model. It is RUNTIME-owned (shipped inside the
# package, as the gem now ships it under lib/), not a test fixture reached by
# walking out of the install: the previous path resolved outside the package
# and simply did not exist in a built wheel, where it degraded into a report
# with 97 "diagram unavailable" cards instead of failing. Resolved through the
# package so it works identically from a source tree and from a wheel.
FIXTURE = str(resources.files('btap.modeling.hvac') / 'data' / '5ZoneNoHVAC.osm')

# ---- component classification (mirrors necb ModelQuery::COMPONENT_KINDS) ----
# Order matters: the FIRST matching regex wins, so specific rules precede
# broad ones. In particular 'heat_pump' (plant/water-source heat pumps) MUST
# precede 'pump' — every "HeatPump_*" idd contains the substring "Pump", so a
# bare /Pump/ rule would otherwise swallow the heat pump and hide it. The
# 'pump' rule is anchored to real pump classes (^OS_Pump / ^OS_HeaderedPumps)
# so it never catches a HeatPump.
COMPONENT_KINDS = [
    ('oa',           r'AirLoopHVAC_OutdoorAirSystem'),
    ('hx',           r'HeatExchanger'),
    ('cooling_coil', r'Coil_Cooling|CoilSystem_Cooling|EvaporativeCooler'),
    ('heating_coil', r'Coil_Heating|Humidifier'),
    ('fan',          r'^OS_Fan'),
    ('boiler',       r'Boiler'),
    ('water_heater', r'WaterHeater'),
    ('chiller',      r'Chiller'),
    ('tower',        r'CoolingTower|FluidCooler'),
    ('heat_pump',    r'HeatPump_WaterToWater|HeatPump_PlantLoop_EIR|HeatPump_WaterToAir'),
    ('district',     r'DistrictHeating|DistrictCooling'),
    ('pump',         r'^OS_Pump|^OS_HeaderedPumps'),
]

KIND_LABELS = {
    'oa': 'Outdoor air', 'hx': 'Heat recovery', 'cooling_coil': 'Cooling coil',
    'heating_coil': 'Heating coil', 'fan': 'Fan', 'boiler': 'Boiler',
    'water_heater': 'Water heater', 'chiller': 'Chiller', 'tower': 'Cooling tower',
    'pump': 'Pump', 'heat_pump': 'Heat pump', 'district': 'District energy',
    'zone': 'Thermal zone', 'other': 'Component',
    # Plant-demand load groups + air-loop zone-level rows.
    'baseboard': 'Baseboard (hydronic)', 'fan_coil': 'Fan-coil coil',
    'heat_pump_coil': 'Heat-pump coil', 'water_use': 'Water use',
    'terminal': 'Air terminal',
}

# Per-kind fill colors for component glyphs.
KIND_COLORS = {
    'oa': '#7fb3d5', 'hx': '#a569bd', 'cooling_coil': '#5dade2', 'heating_coil': '#e59866',
    'fan': '#82e0aa', 'boiler': '#e57373', 'water_heater': '#e59866', 'chiller': '#5dade2',
    'tower': '#76d7c4', 'pump': '#f7dc6f', 'heat_pump': '#48c9b0', 'district': '#bb8fce',
    'zone': '#d6dbdf', 'other': '#d5d8dc',
    'baseboard': '#e59866', 'fan_coil': '#82e0aa', 'heat_pump_coil': '#76d7c4',
    'water_use': '#7fb3d5', 'terminal': '#aeb6bf',
}

# Loop track accent colors, keyed by loop kind (spec-mandated hues).
LOOP_COLORS = {
    'air': '#2874a6', 'hot_water': '#c0392b', 'chilled_water': '#17a2b8',
    'condenser': '#16a085', 'shw': '#8e44ad',
}

LOOP_LABELS = {
    'air': 'Air loop', 'hot_water': 'Hot water loop', 'chilled_water': 'Chilled water loop',
    'condenser': 'Condenser loop', 'shw': 'Service water loop',
}

# Zone-equipment idd type -> human label. Ordered most-specific first so the
# first matching regex wins.
ZONE_EQUIPMENT = [
    (r'ZoneHVAC_Baseboard.*Water',                     'hot water baseboard'),
    (r'ZoneHVAC_Baseboard.*Electric',                  'electric baseboard'),
    (r'ZoneHVAC_Baseboard',                            'baseboard'),
    (r'ZoneHVAC_PackagedTerminalHeatPump',             'PTHP'),
    (r'ZoneHVAC_PackagedTerminalAirConditioner',       'PTAC'),
    (r'ZoneHVAC_TerminalUnit_VariableRefrigerantFlow', 'VRF terminal'),
    (r'ZoneHVAC_WaterToAirHeatPump',                   'water-source heat pump'),
    (r'ZoneHVAC_UnitHeater',                           'unit heater'),
    (r'ZoneHVAC_FourPipeFanCoil',                      'fan coil'),
    (r'ZoneHVAC_EnergyRecoveryVentilator',             'ERV'),
    (r'ZoneHVAC_LowTemp',                              'radiant panel'),
    (r'ZoneHVAC',                                      'zone unit'),
]

# Air-terminal idd type -> human label (most-specific first).
TERMINAL_KINDS = [
    (r'VAV_HeatAndCool_Reheat',           'VAV heat/cool reheat terminal'),
    (r'VAV_HeatAndCool_NoReheat',         'VAV heat/cool terminal'),
    (r'VAV_Reheat',                       'VAV reheat terminal'),
    (r'VAV_NoReheat',                     'VAV terminal'),
    (r'ConstantVolume_Reheat',            'CV reheat terminal'),
    (r'ConstantVolume_NoReheat',          'Diffuser (uncontrolled)'),
    (r'ConstantVolume_FourPipeInduction', 'Induction terminal'),
    (r'SeriesPIU',                        'Series PIU terminal'),
    (r'ParallelPIU',                      'Parallel PIU terminal'),
    (r'InletSideMixer',                   'Inlet-side mixer terminal'),
    (r'CooledBeam',                       'Cooled-beam terminal'),
    (r'Uncontrolled',                     'Diffuser (uncontrolled)'),
    (r'AirTerminal',                      'Air terminal'),
]

# Per-FAMILY description blurb (verbatim from spec). Shown as the card
# description; the canonical name is displayed separately (no duplication).
FAMILY_BLURB = {
    'baseboards': 'Perimeter baseboard heating only, no central air system.',
    'composite': 'A dedicated ventilation unit paired with separate zone conditioning (fan coils, water/ground-source heat pumps, or residential AC).',
    'doas': 'Dedicated outdoor air system providing ventilation only; zone conditioning is separate.',
    'doas_pthp': 'Dedicated outdoor air with packaged terminal heat pumps at each zone (NECB ECM hs11).',
    'ecm_ashp_baseboard': 'Air-source (or cold-climate) heat pump for primary heating and cooling with baseboard backup (NECB ECMs hs09/hs12).',
    'ecm_doas_vrf': 'Dedicated outdoor air with variable refrigerant flow zone terminals on an air-source heat pump (NECB ECMs hs08/hs13).',
    'ecm_hp_fancoils': 'Central heat-pump plant (ground-, water-, or air-source) serving hydronic fan coils (NECB ECMs hs14-16).',
    'evap_cooler': 'Direct evaporative cooling, with or without supplementary heat.',
    'fan_coils': 'Two-pipe (TPFC) or four-pipe (FPFC) fan coils per zone on a central chiller and boiler, with a make-up air unit for ventilation (NECB systems 2 and 5).',
    'furnace': 'Forced-air furnace providing central heating.',
    'mau_ptac': 'Make-up air unit for ventilation plus packaged terminal air conditioners at each zone (NECB system 1 variants).',
    'psz': 'Packaged single-zone rooftop unit — one air handler per zone with DX or heat-pump cooling and a gas/electric heating coil, optionally with perimeter baseboards (NECB systems 3 and 4, and PSZ-AC).',
    'unit_heaters': 'Standalone gas or electric unit heaters.',
    'vav_reheat': 'Multi-zone variable-air-volume — a central built-up air handler with chilled-water or DX cooling and zone reheat terminals, plus baseboards (NECB system 6 and packaged VAV).',
    'vrf': 'Variable refrigerant flow heat-recovery system serving zone terminals.',
    'wshp': 'Water-source heat pumps at each zone on a common condenser-water loop.',
    'zone_ervs': 'Zone-level energy recovery ventilators providing ventilation with heat recovery.',
    'zone_terminal': 'Zone terminal units — packaged terminal AC/heat pump or window AC — with baseboard heating.',
}

FAMILY_TITLES = {
    'baseboards': 'Baseboard heating', 'composite': 'Composite (DOAS + zone conditioning)',
    'doas': 'Dedicated outdoor air', 'doas_pthp': 'DOAS + PTHP (ECM hs11)',
    'ecm_ashp_baseboard': 'ASHP + baseboard (ECM hs09/hs12)',
    'ecm_doas_vrf': 'DOAS + VRF (ECM hs08/hs13)',
    'ecm_hp_fancoils': 'Heat-pump plant fan coils (ECM hs14-16)',
    'evap_cooler': 'Evaporative cooling', 'fan_coils': 'Fan coils (NECB sys 2 / 5)',
    'furnace': 'Furnace', 'mau_ptac': 'MAU + PTAC (NECB sys 1)',
    'psz': 'Packaged single-zone (NECB sys 3 / 4, PSZ-AC)',
    'unit_heaters': 'Unit heaters', 'vav_reheat': 'VAV with reheat (NECB sys 6, PVAV)',
    'vrf': 'Variable refrigerant flow', 'wshp': 'Water-source heat pumps',
    'zone_ervs': 'Zone ERVs', 'zone_terminal': 'Zone terminal units',
}

# ------------------------------------------------------------------ public

# Families whose systems are packaged/per-zone (one unit or air loop PER
# zone): building them across all fixture zones just replicates identical
# loops, so a single zone is the succinct, representative diagram. Every
# other family has a central air handler or plant genuinely serving many
# zones, so it keeps the full zone set to show that.
SINGLE_ZONE_FAMILIES = ['psz', 'zone_terminal', 'baseboards', 'unit_heaters',
                        'furnace', 'evap_cooler', 'vrf']


def to_html(path=None, fixture=FIXTURE):
    """Build every catalog system on the fixture, extract its topology, and
    render the whole catalog as one self-contained HTML string.

    :param path: if given, the HTML is also written here
    :param fixture: the seed .osm (default: bundled 5ZoneNoHVAC)
    :return: the self-contained HTML document (str)
    """
    rows = catalog.rows()
    # Load + thermostat the fixture ONCE, then clone it per system. Reloading
    # the .osm from disk costs ~2.4 s each (OSM deserialization); an in-memory
    # clone costs ~6 ms — the difference between a ~4 min and a ~6 s run.
    base = prepared_base(fixture)
    cards = [build_card(row, base) for row in rows]
    html = assemble(cards)
    if path:
        Path(path).write_text(html, encoding='utf-8')
    return html


# ------------------------------------------------- reusable diagram API
# A REUSABLE, host-agnostic diagram bundle for ANY model. A consuming report
# (e.g. btap-necb's AHJ compliance report) drives its own proposed and
# reference models through this to get the SAME OpenStudio-App-style loop
# diagrams the catalog draws, without depending on catalog internals. Returns
# PLAIN dicts (inline-SVG strings + labels) and NEVER raises — on any failure
# it returns an empty bundle carrying the error message, so a host render can
# degrade gracefully. To resolve the diagrams' <use href="#icon-…"> refs the
# host must embed `icon_defs` ONCE per document and add `DIAGRAM_CSS` to its
# stylesheet.

def model_diagrams(model):
    """:param model: openstudio.model.Model
    :return: dict { 'loops': [{ 'kind':, 'label':, 'svg': }...],
                    'zone_equipment_svg': <svg str or None>, 'empty': <bool>,
                    'error': <str, only on failure> }"""
    try:
        zones = sorted_by_name(model.getThermalZones())
        topo = extract(model, zones)
        loops = [{'kind': loop['kind'], 'label': loop_display_label(loop),
                  'svg': loop_diagram_svg(loop)}
                 for loop in topo['air_loops'] + topo['plant_loops']]
        zeq = topo['zone_equipment']
        return {'loops': loops,
                'zone_equipment_svg': zone_equipment_svg(zeq) if zeq else None,
                'empty': not loops and not zeq}
    except Exception as e:
        return {'loops': [], 'zone_equipment_svg': None, 'empty': True, 'error': str(e)}


def loop_display_label(loop):
    """A DESCRIPTIVE label for a loop, so a host's dropdown chooser can tell
    loops apart. Plant loops keep their kind label ("Hot water loop",
    "Chilled water loop", "Condenser loop"). An AIR loop instead names the
    zone(s) it serves — "Air loop — Thermal Zone 1" for a single-zone (PSZ)
    air handler, "Air loop (N zones)" for a multi-zone air handler — which
    resolves the ambiguous "Air loop / Air loop 2…" problem when several
    packaged single-zone units are listed together."""
    base = LOOP_LABELS.get(loop['kind'], 'Loop')
    if loop['kind'] != 'air':
        return base

    zones = [n for n in (d.get('zone_name') for d in (loop.get('demand') or []))
             if n is not None and str(n) != '']
    if len(zones) == 1:
        return f'{base} — {zones[0]}'
    if len(zones) == 0:
        return base
    return f'{base} ({len(zones)} zones)'


# The self-contained CSS subset a HOST document needs so the reused loop/zone
# diagrams render correctly outside the catalog page: the scroll container, the
# intrinsic-size svg override (so a host's own responsive `svg { width:100% }`
# rule does not stretch a diagram), and print break-avoidance. The catalog page
# keeps its own full CSS; this is only the diagram-relevant subset. Fully
# self-contained — no url()/@import/external references (a host's
# no-external-references test must still pass).
DIAGRAM_CSS = """.diagram { overflow-x: auto; break-inside: avoid; margin: .4rem 0 1rem; }
/* Render diagram SVGs at their intrinsic size (fixed box/gap constants) so a
   component box is the same physical size in every diagram and wide loops
   scroll horizontally instead of shrinking; this MUST win over any generic
   `svg { width: 100% }` rule in the host stylesheet. */
.diagram svg { width: auto; height: auto; max-width: none; display: block; }
.diagram .note { font-size: .82rem; color: #555; font-style: italic; margin: .3rem 0; }
"""

# -------------------------------------------------------- build & extract

def prepared_base(fixture):
    model = load_model(fixture)
    for z in model.getThermalZones():
        if z.thermostatSetpointDualSetpoint().is_initialized():
            continue

        z.setThermostatSetpointDualSetpoint(
            openstudio.model.ThermostatSetpointDualSetpoint(model))
    return model


def build_card(row, base):
    """:param base: the prepared fixture (openstudio.model.Model) to clone
    :return: card dict: row, canonical, description, topology or diagram_error"""
    canonical_name = canonical.name(row)
    # Description = the per-family blurb only; the canonical name is shown on
    # its own element, so appending it here would just duplicate it.
    description = FAMILY_BLURB.get(row['family'], '')
    card = {'row': row, 'canonical': canonical_name, 'description': description}
    try:
        model = base.clone(True).to_Model()
        zones = sorted_by_name(model.getThermalZones())
        # Packaged/per-zone families replicate identical loops per zone, so one
        # zone is the representative diagram. Every other family has a central
        # handler/plant genuinely serving many zones — TWO zones is enough to show
        # that (and to render two demand branches) without a busy 5-zone diagram.
        zones = zones[:1] if row['family'] in SINGLE_ZONE_FAMILIES else zones[:2]
        builder.build_system(model, row['name'], zones)
        card['topology'] = extract(model, zones)
    except Exception as e:
        # Never crash the whole report over one odd build — render the card
        # without a diagram plus a small "diagram unavailable" note.
        card['diagram_error'] = str(e)
    return card


def load_model(fixture):
    """Load the seed model, refusing an unreadable path LOUDLY.

    This must never call ``.get()`` on an unchecked Optional. In the Python
    bindings ``OptionalModel.get()`` on an EMPTY optional returns an empty
    Model rather than raising (Ruby raises), so the whole catalog rendered 97
    "diagram unavailable" cards and returned a 1 MB document that looked like
    a report. Worse, ``.get()`` on other empty Optionals raises SystemError
    and leaves the C-level error indicator set, which can segfault the
    interpreter on a later unrelated call. Check first, always.
    """
    loaded = openstudio.model.Model.load(openstudio.path(str(fixture)))
    if not loaded.is_initialized():
        raise ValueError(
            f"catalog seed model could not be read: {fixture} "
            "(pass fixture=<path to a .osm with thermal zones>)")
    return loaded.get()


def extract(model, zones):
    """Extract a plain-dict topology snapshot (mirrors necb ModelQuery, extended
    with supply/demand split, per-component tooltip attributes, and zone
    equipment). Never raises."""
    return {
        'air_loops': air_loops(model),
        'plant_loops': plant_loops(model),
        'zone_equipment': zone_equipment(zones),
    }


def air_loops(model):
    out = []
    for loop in sorted_by_name(model.getAirLoopHVACs()):
        # Air loops have a single supply air-handler path (typically no supply
        # splitter) — every real component becomes a series cell in flow order.
        out.append({'kind': 'air', 'name': loop.nameString(),
                    'supply': supply_columns(decompose_air_supply(loop)),
                    'demand': air_demand(loop)})
    return out


def plant_loops(model):
    out = []
    for loop in sorted_by_name(model.getPlantLoops()):
        supply = decompose_supply_plant(loop)
        out.append({'kind': plant_kind(supply), 'name': loop.nameString(),
                    'supply': supply_columns(supply),
                    'demand': demand_branch_lists(decompose_demand_plant(loop))})
    return out


def plant_kind(decomp):
    """Classify a plant loop by the equipment on its (decomposed) supply side."""
    kinds = [cell['kind'] for cell in decomp_cells(decomp)]
    if 'water_heater' in kinds:
        return 'shw'
    if 'tower' in kinds:
        return 'condenser'
    if 'chiller' in kinds:
        return 'chilled_water'
    if 'boiler' in kinds:
        return 'hot_water'

    return 'condenser'  # heat-pump / WSHP condenser loops have neither boiler nor chiller


def decomp_cells(decomp):
    """Every cell of a decomposed side (pre-series + parallel branches + post-series)."""
    return decomp['pre'] + [c for branch in decomp['branches'] for c in branch] + decomp['post']


def air_demand(loop):
    """An air loop serves thermal zones. Consistent with the "don't collapse"
    principle, its demand is drawn as ONE branch PER served zone (the diagram is
    built on 1 or 2 zones), each branch showing that zone's air terminal plus
    its ZoneHVAC* equipment. Returns one dict per zone:
    { 'kind': 'zone', 'zone_name':, 'terminal':, 'equipment': [...], 'tooltip': }."""
    try:
        zones = sorted_by_name(loop.thermalZones())
    except Exception:
        zones = []
    out = []
    for zone in zones:
        try:
            name = zone.nameString()
        except Exception:
            name = ''
        terminal = zone_terminal(zone)
        equipment = zone_hvac_equipment(zone)
        tip = ['Served thermal zone', f'Zone: {truncate(name, 40)}']
        if terminal:
            tip.append(f"Terminal: {terminal['label']}")
        for e in equipment:
            tip.append(f"Zone equipment: {e['label']}")
        out.append({'kind': 'zone', 'zone_name': name, 'terminal': terminal,
                    'equipment': equipment, 'tooltip': '\n'.join(tip)})
    return out


def zone_terminal(zone):
    """The air terminal serving a zone (from airLoopHVACTerminal, or the terminal
    object among the zone's equipment). Guarded — returns None if none."""
    try:
        obj = None
        if hasattr(zone, 'airLoopHVACTerminal'):
            o = zone.airLoopHVACTerminal()
            if hasattr(o, 'is_initialized') and o.is_initialized():
                obj = o.get()
        if obj is None:
            for e in zone.equipment():
                if re.search(r'AirTerminal', e.iddObjectType().valueName()):
                    obj = e
                    break
        if obj is None:
            return None

        idd = obj.iddObjectType().valueName()
        try:
            name = obj.nameString()
        except Exception:
            name = ''
        tip = [f'Air terminal: {terminal_label(idd)}', f'Type: {clean_idd(idd)}']
        if str(name) != '':
            tip.append(f'Name: {truncate(name, 48)}')
        return {'label': terminal_label(idd), 'idd': idd, 'name': name,
                'tooltip': '\n'.join(tip)}
    except Exception:
        return None


def terminal_label(idd_name):
    for regex, label in TERMINAL_KINDS:
        if re.search(regex, idd_name):
            return label
    return 'Air terminal'


def zone_hvac_equipment(zone):
    """Deduped labels + counts of the ZoneHVAC* units in one zone (its container rows)."""
    try:
        counts = {}
        order = []
        rep = {}
        for equip in zone.equipment():
            idd = equip.iddObjectType().valueName()
            label = zone_equipment_label(idd)
            if label is None:
                continue

            if label not in counts:
                order.append(label)
                counts[label] = 0
            counts[label] += 1
            rep.setdefault(label, idd)
        out = []
        for label in order:
            tip = '\n'.join([f'Zone equipment: {label}', f'Type: {clean_idd(rep[label])}',
                             f'{counts[label]} in this zone'])
            out.append({'label': label, 'count': counts[label], 'tooltip': tip,
                        'idd': rep[label]})
        return out
    except Exception:
        return []


def demand_cell(component):
    """Build one drawable DEMAND cell for a served component, or None for anything
    not drawn (nodes, connectors, pipes, unclassified — so a bypass branch of
    bare pipe yields no cell and its branch is dropped). On a DEMAND side a
    chiller means its CONDENSER is the load (a condenser-water loop cooling the
    chillers) and a water-to-water heat pump means its SOURCE side — so these
    surface as loads, suffixed "(condenser)"/"(source)". Zone-contained coils
    (four-pipe fan coil, water-source heat pump, hydronic baseboard) carry a
    "— <Zone>" suffix tracing where the coil lives. Same cell shape as a supply
    cell so the two sides share the renderer."""
    try:
        if not is_real(component):
            return None

        idd = component.iddObjectType().valueName()
        name = component_name(component)
        spec = demand_spec(component, idd, name)
        if spec is None:
            return classify_component(component)  # air-handler coils, HX, ... (None for pipes)

        tip = [f"{spec['label']} (served load)", f'Type: {clean_idd(idd)}']
        if name != '':
            tip.append(f'Served: {truncate(name, 48)}')
        return {'kind': spec['kind'], 'name': name, 'idd': idd, 'label': spec['label'],
                'tooltip': '\n'.join(tip)}
    except Exception:
        return None


def demand_spec(component, idd, name):
    """The kind + specific label for a served demand component, or None to defer to
    the generic supply classifier (air-handler water coils, heat exchangers)."""
    # A chiller on a demand side = its condenser being cooled by this loop;
    # reuse the supply-side compressor-type parse, suffixed "(condenser)".
    if re.search(r'Chiller', idd):
        return {'kind': 'chiller', 'label': f'{chiller_label(name)} (condenser)'}
    # A water-to-water / plant-loop heat pump on a demand side = its source side.
    if re.search(r'HeatPump_WaterToWater|HeatPump_PlantLoop_EIR', idd):
        return {'kind': 'heat_pump', 'label': 'Heat pump (source)'}

    if re.search(r'Coil_Heating_Water_Baseboard', idd):
        return zone_or_group(component, 'baseboard', 'Baseboard (hydronic)')
    if re.search(r'WaterUse_Connections', idd):
        return {'kind': 'water_use', 'label': 'Water use'}
    if re.search(r'WaterToAirHeatPump|WaterToWaterHeatPump', idd):
        return zone_or_group(component, 'heat_pump_coil', 'Heat-pump coil')

    if re.search(r'Coil_(Heating|Cooling)_Water', idd):
        z = zone_of(component)
        if z:
            return {'kind': 'fan_coil', 'label': f'Fan-coil coil — {z}'}
        if re.search(r'Cooling', idd):
            return {'kind': 'cooling_coil', 'label': 'Cooling coil (air handler)'}

        return {'kind': 'heating_coil', 'label': 'Heating coil (air handler)'}

    return None


def zone_or_group(component, kind, base):
    """A zone-contained coil is labelled with its zone ("Fan-coil coil — Thermal
    Zone 1"), so the diagram shows WHERE each coil is; a coil not in a zone
    keeps the bare label."""
    zone = zone_of(component)
    return {'kind': kind, 'label': f'{base} — {zone}' if zone else base}


def zone_of(component):
    """The thermal-zone name a demand coil lives in, traced through its container
    ZoneHVAC unit (four-pipe fan coil, water-source heat pump, baseboard), or
    None for an air-handler coil (whose container is an HVACComponent, not a
    zone). demandComponents yields bare ModelObjects, so cast up first. Guarded."""
    try:
        if not hasattr(component, 'to_HVACComponent'):
            return None

        hvac = component.to_HVACComponent()
        if not hvac.is_initialized():
            return None

        cz = hvac.get().containingZoneHVACComponent()
        if not cz.is_initialized():
            return None

        tz = cz.get().thermalZone()
        return tz.get().nameString() if tz.is_initialized() else None
    except Exception:
        return None


def component_name(component):
    try:
        return component.nameString()
    except Exception:
        return ''


# ---- loop decomposition (faithful to OpenStudio App GridItem.cpp) ----
# Each loop side is decomposed by walking its ACTUAL branch structure through
# the OpenStudio Model API (never by classifying a flat component list): a
# PRE-series run before the splitter, one PARALLEL branch per non-empty
# splitter outlet, and a POST-series run after the mixer. This mirrors the
# OpenStudio Application's SupplySideItem/DemandSideItem + HorizontalBranchGroup
# decomposition, so two boilers/chillers are two branches, a condenser demand's
# two chillers are two branches, and zone coils are one branch each — with NO
# counting, grouping, or collapse anywhere.

def is_real(component):
    """`is_real`: mirrors GridItem.cpp `isNotSplitterMixerNodesPred` — a component
    is part of the drawn topology iff its iddObjectType is NOT a Node, Splitter,
    Mixer, or Connector. (Pipes pass this test but yield no drawable CELL — the
    cell builders return None for them — so a bare-pipe bypass branch is empty
    and dropped.)"""
    try:
        return re.search(r'Node|Connector_Splitter|Connector_Mixer|ZoneSplitter|ZoneMixer',
                         component.iddObjectType().valueName()) is None
    except Exception:
        return False


def decompose_side(splitter, mixer, whole, pre, post, branch_walk, cell_fn):
    """Decompose one loop side into {'pre':, 'branches':, 'post':}. `branch_walk`
    walks the series of one branch (splitter outlet -> mixer); `whole`/`pre`/`post`
    are the ordered component lists for the single-path, before-splitter, and
    after-mixer runs; `cell_fn` maps a component to a drawable cell (None = not
    drawn). If the splitter/mixer yield <= 1 non-empty branch, the side is a
    single series path (pre = the whole side); otherwise it is genuinely
    parallel equipment."""
    branches = []
    for outlet in splitter.outletModelObjects():
        hvac = outlet.to_HVACComponent()
        if not hvac.is_initialized():
            continue

        cells = [cell for cell in (cell_fn(c) for c in branch_walk(hvac.get(), mixer)
                                   if is_real(c))
                 if cell is not None]
        if cells:
            branches.append(cells)
    if len(branches) <= 1:
        return {'pre': real_cells(whole, cell_fn), 'branches': [], 'post': []}

    return {'pre': real_cells(pre, cell_fn), 'branches': branches,
            'post': real_cells(post, cell_fn)}


def real_cells(components, cell_fn):
    """The drawable cells of an ordered component list (is_real components mapped
    through the cell builder, dropping nodes/connectors/pipes/unclassified)."""
    return [cell for cell in (cell_fn(c) for c in components if is_real(c))
            if cell is not None]


def decompose_supply_plant(loop):
    """A plant loop's SUPPLY side: pump(s) before the splitter, parallel equipment
    branches (two chillers/boilers, or a single heat pump / district source),
    equipment after the mixer."""
    try:
        splitter = loop.supplySplitter()
        mixer = loop.supplyMixer()
        return decompose_side(splitter, mixer,
                              loop.supplyComponents(),
                              loop.supplyComponents(loop.supplyInletNode(), splitter),
                              loop.supplyComponents(mixer, loop.supplyOutletNode()),
                              lambda start, mix: loop.supplyComponents(start, mix),
                              classify_component)
    except Exception:
        return {'pre': real_cells(loop.supplyComponents(), classify_component),
                'branches': [], 'post': []}


def decompose_demand_plant(loop):
    """A plant loop's DEMAND side: each served load (an air-handler coil, or a
    zone-level fan-coil / baseboard coil, or a cooled chiller condenser / heat
    pump source) is its OWN parallel branch — straight from the demand splitter's
    outlets, never counted or collapsed."""
    try:
        splitter = loop.demandSplitter()
        mixer = loop.demandMixer()
        return decompose_side(splitter, mixer,
                              loop.demandComponents(),
                              loop.demandComponents(loop.demandInletNode(), splitter),
                              loop.demandComponents(mixer, loop.demandOutletNode()),
                              lambda start, mix: loop.demandComponents(start, mix),
                              demand_cell)
    except Exception:
        return {'pre': real_cells(loop.demandComponents(), demand_cell),
                'branches': [], 'post': []}


def decompose_air_supply(loop):
    """An air loop's supply is a single air-handler path (no supply splitter): every
    real component is a series cell in flow order. AirLoopHVACUnitarySystem
    containers (staged NECB reference systems) are expanded to the fan and
    coils they hold — the container itself draws nothing."""
    return {'pre': real_cells(coils.supply_components(loop), classify_component),
            'branches': [], 'post': []}


def supply_columns(decomp):
    """Flatten a decomposition into ordered supply COLUMNS for the renderer: the
    pre-series cells and post-series cells are single-cell columns; the parallel
    branches (if any) are one stacked column of branch series."""
    cols = [{'cells': [cell]} for cell in decomp['pre']]
    if decomp['branches']:
        cols.append({'parallel': True, 'branches': decomp['branches']})
    cols.extend({'cells': [cell]} for cell in decomp['post'])
    return cols


def demand_branch_lists(decomp):
    """Flatten a demand decomposition into a list of demand BRANCHES (each a series
    of cells) for the demand stack: the parallel branches when present, else the
    single series path as one branch (empty => "No loads")."""
    if decomp['branches']:
        return decomp['branches']

    return [] if not decomp['pre'] else [decomp['pre']]


def classify_component(component):
    """Classify + label one supply component, or None for unclassified nodes/pipes."""
    idd = component.iddObjectType().valueName()
    kind = classify(idd)
    if kind is None:
        return None

    try:
        name = component.nameString()
    except Exception:
        name = ''
    return {'kind': kind, 'name': name, 'idd': idd, 'label': component_label(idd, name),
            'tooltip': component_tooltip(component, kind, idd, name)}


def classify(idd_name):
    for kind, regex in COMPONENT_KINDS:
        if re.search(regex, idd_name):
            return kind
    return None


def component_label(idd, name=''):
    """The SPECIFIC human label for a component, reflecting its exact type rather
    than the coarse kind — the whole point of the extraction fix. Coils split by
    DX/electric/gas/water/heat-pump; fans and pumps by control type; chillers by
    compressor type parsed from the object NAME (the fan-coil and VAV systems
    differ ONLY by chiller type); boilers by Primary/Secondary; heat pumps vs
    pumps; district heating vs cooling. Falls back to the coarse kind label."""
    if re.search(r'Coil_Heating_DX', idd):
        return 'DX heating coil'
    if re.search(r'Coil_Heating_WaterToAirHeatPump', idd):
        return 'Heat-pump heating coil'
    if re.search(r'Coil_Heating_Water', idd):
        return 'Hot-water heating coil'
    if re.search(r'Coil_Heating_Electric', idd):
        return 'Electric heating coil'
    if re.search(r'Coil_Heating_Gas', idd):
        return 'Gas heating coil'
    if re.search(r'Coil_Cooling_DX', idd):
        return 'DX cooling coil'
    if re.search(r'Coil_Cooling_WaterToAirHeatPump', idd):
        return 'Heat-pump cooling coil'
    if re.search(r'Coil_Cooling_Water', idd):
        return 'Chilled-water cooling coil'
    if re.search(r'HeatPump.*Cooling', idd):
        return 'Heat pump (cooling)'
    if re.search(r'HeatPump.*Heating', idd):
        return 'Heat pump (heating)'
    if re.search(r'HeatPump', idd):
        return 'Heat pump'
    if re.search(r'DistrictHeating', idd):
        return 'District heating'
    if re.search(r'DistrictCooling', idd):
        return 'District cooling'
    if re.search(r'Boiler', idd):
        return boiler_label(name)
    if re.search(r'Chiller', idd):
        return chiller_label(name)
    if re.search(r'Fan_ConstantVolume', idd):
        return 'Constant-volume fan'
    if re.search(r'Fan_VariableVolume', idd):
        return 'Variable-volume fan'
    if re.search(r'Fan_OnOff', idd):
        return 'On/off fan'
    if re.search(r'Fan_SystemModel', idd):
        return 'Fan (system model)'
    if re.search(r'HeaderedPumps', idd):
        return 'Headered pumps'
    if re.search(r'Pump_VariableSpeed', idd):
        return 'Variable-speed pump'
    if re.search(r'Pump_ConstantSpeed', idd):
        return 'Constant-speed pump'
    return KIND_LABELS.get(classify(idd), 'Component')


def boiler_label(name):
    """Boiler label from the object name: NECB builds a lead/lag pair named
    "Primary Boiler" / "Secondary Boiler"."""
    if re.search(r'primary', name, re.I):
        return 'Primary boiler'
    if re.search(r'secondary', name, re.I):
        return 'Secondary boiler'

    return 'Boiler'


def chiller_label(name):
    """Chiller label from the compressor type encoded in the object name — the only
    thing that distinguishes the 16 fan-coil and 18 VAV chiller variants."""
    if re.search(r'centrifugal', name, re.I):
        return 'Centrifugal chiller'
    if re.search(r'reciprocat', name, re.I):
        return 'Reciprocating chiller'
    if re.search(r'screw', name, re.I):
        return 'Rotary-screw chiller'
    if re.search(r'scroll', name, re.I):
        return 'Scroll chiller'

    return 'Chiller'


# --------------------------------------------------------- tooltip attrs
# Cheap, sizing-free attribute reads for the hover tooltip. Every getter is
# guarded — extraction must never raise.

def clean_idd(idd):
    return re.sub(r'\AOS[_:]', '', str(idd)).replace('_', ' ').strip()


def component_tooltip(component, kind, idd, name=None):
    if name is None:
        try:
            name = component.nameString()
        except Exception:
            name = ''
    # First line = the SPECIFIC label; the full iddObjectType + object name are
    # kept below so the hover tooltip always carries the raw truth.
    lines = [component_label(idd, name), f'Type: {clean_idd(idd)}']
    if str(name) != '':
        lines.append(f'Name: {truncate(name, 48)}')
    for k, v in component_attrs(component, kind, name).items():
        lines.append(f'{k}: {v}')
    return '\n'.join(lines)


def component_attrs(component, kind, name):
    attrs = {}
    add_opt_attr(attrs, 'Fuel', component, 'to_BoilerHotWater', 'fuelType')
    add_opt_attr(attrs, 'Fuel', component, 'to_CoilHeatingGas', 'fuelType')
    add_opt_attr(attrs, 'Fuel', component, 'to_WaterHeaterMixed', 'heaterFuelType')
    add_flag_attr(attrs, 'Fuel', 'Electricity', component, 'to_CoilHeatingElectric')
    if kind == 'fan':
        type_ = fan_type(component)
        if type_:
            attrs['Control'] = type_
    if kind == 'chiller':
        if re.search(r'air.?cool', name, re.I):
            attrs['Condenser'] = 'air-cooled'
        if re.search(r'water.?cool', name, re.I):
            attrs['Condenser'] = 'water-cooled'
    return attrs


def add_opt_attr(attrs, key, component, caster, getter):
    try:
        if key in attrs:
            return
        if not hasattr(component, caster):
            return

        o = getattr(component, caster)()
        if not (hasattr(o, 'is_initialized') and o.is_initialized()):
            return

        obj = o.get()
        if not hasattr(obj, getter):
            return

        val = str(getattr(obj, getter)())
        if val != '':
            attrs[key] = val
    except Exception:
        pass


def add_flag_attr(attrs, key, value, component, caster):
    try:
        if key in attrs:
            return
        if not hasattr(component, caster):
            return

        o = getattr(component, caster)()
        if hasattr(o, 'is_initialized') and o.is_initialized():
            attrs[key] = value
    except Exception:
        pass


def fan_type(component):
    try:
        for type_ in ['VariableVolume', 'ConstantVolume', 'OnOff', 'SystemModel']:
            caster = f'to_Fan{type_}'
            if not hasattr(component, caster):
                continue

            o = getattr(component, caster)()
            if hasattr(o, 'is_initialized') and o.is_initialized():
                return re.sub(r'([a-z])([A-Z])', r'\1 \2', type_)
        return None
    except Exception:
        return None


def zone_equipment(zones):
    """Per-zone equipment — NOT collapsed across zones. Each built zone keeps its
    own ZoneHVAC* units (same shape as an air-demand zone), so the Zone
    equipment tab shows one container per zone instead of one aggregated count.
    :return: [{ 'zone_name':, 'equipment':, 'tooltip': }] ordered as encountered"""
    out = []
    for zone in zones:
        try:
            name = zone.nameString()
        except Exception:
            name = ''
        equipment = zone_hvac_equipment(zone)
        if not equipment:
            continue

        tip = [f'Zone: {truncate(name, 40)}']
        for e in equipment:
            tip.append(f"Zone equipment: {e['label']}")
        out.append({'zone_name': name, 'equipment': equipment, 'tooltip': '\n'.join(tip)})
    return out


def zone_equipment_label(idd_name):
    for regex, label in ZONE_EQUIPMENT:
        if re.search(regex, idd_name):
            return label
    return None


# -------------------------------------------------------------- SVG utils
# Minimal inline-SVG primitives (mirrors necb Report::SVG). No external assets.
# `esc` (HTML-escape of &, <, > and ") is imported from btap._compat — exactly
# the Ruby module's four gsubs.

def open_svg(width, height, label):
    """Emit the svg at its NATURAL pixel size: explicit width/height ATTRIBUTES
    equal to the viewBox dimensions so it renders 1:1 (no stretch-to-fit). Box
    size and spacing are fixed constants (see CELL_W/CELL_H/CELL_HGAP), so a
    component box is the same physical size in every diagram; wide loops scroll."""
    return (f'<svg width="{r(width)}" height="{r(height)}" viewBox="0 0 {r(width)} {r(height)}" '
            f'role="img" aria-label="{esc(label)}" '
            'xmlns="http://www.w3.org/2000/svg" font-family="sans-serif" font-size="11">')


def svg_attrs(opts):
    return ''.join(' {}="{}"'.format(k.replace('_', '-'), esc(v)) for k, v in opts.items())


def svg_rect(x, y, w, h, fill, **opts):
    extra = svg_attrs(opts)
    return (f'<rect x="{r(x)}" y="{r(y)}" width="{r(max(w, 0))}" height="{r(h)}" '
            f'fill="{fill}"{extra}/>')


def svg_line(x1, y1, x2, y2, stroke, **opts):
    extra = svg_attrs(opts)
    return (f'<line x1="{r(x1)}" y1="{r(y1)}" x2="{r(x2)}" y2="{r(y2)}" '
            f'stroke="{stroke}"{extra}/>')


def svg_text(x, y, string, **opts):
    extra = svg_attrs(opts)
    return f'<text x="{r(x)}" y="{r(y)}"{extra}>{esc(string)}</text>'


def r(value):
    return ruby_round(value, 1)


# ------------------------------------------------------------- OS icons
# Real OpenStudio Application component icons (BSD-3-Clause), extracted into
# ICON_DATA/ICON_FOR_IDD by scripts/build_icons.rb. Each icon's base64 PNG is
# embedded EXACTLY ONCE in a hidden master <svg><defs> as a <symbol>; every
# component cell references it by id via <use href="#icon-…">, so ~1000 cells
# add ~40 tiny <use> tags, not ~40 fat data-URIs. See THIRD_PARTY_NOTICES.md.

def icon_defs():
    """The hidden master defs: one <symbol> per icon, the data-URI embedded once.
    :return: a zero-size inline <svg> defs block (str) to embed once per page"""
    syms = ''.join(
        '<symbol id="icon-{}" viewBox="0 0 {} {}" '.format(stem, info['w'], info['h'])
        + 'preserveAspectRatio="xMidYMid meet">'
        + '<image width="{}" height="{}" href="{}"/></symbol>'.format(
            info['w'], info['h'], info['data'])
        for stem, info in ICON_DATA.items())
    return ('<svg xmlns="http://www.w3.org/2000/svg" width="0" height="0" aria-hidden="true" '
            f'style="position:absolute;width:0;height:0;overflow:hidden"><defs>{syms}</defs></svg>')


def icon_use(idd, x, y, size):
    """A <use> reference to the embedded icon for this idd, or None if none is
    mapped (caller then falls back to the hand-drawn glyph)."""
    stem = ICON_FOR_IDD.get(idd)
    if not (stem and stem in ICON_DATA):
        return None

    return f'<use href="#icon-{stem}" x="{r(x)}" y="{r(y)}" width="{r(size)}" height="{r(size)}"/>'


def component_mark(kind, idd, x, cy, size):
    """The mark drawn on the left of a component cell: the real OS App icon when
    one is mapped for the idd, else the hand-drawn glyph fallback. Centered in a
    `size`-wide box whose left edge is at `x`, vertically centered on `cy`."""
    return icon_use(idd, x, cy - size / 2.0, size) or glyph(kind, x + size / 2.0, cy)


# ---------------------------------------------------------------- glyphs

def glyph(kind, cx, cy):
    """Tiny hand-drawn component glyphs, centered in a box of the given width.
    Pure inline SVG paths/shapes — no icon fonts, no external images. Kept as the
    FALLBACK for any idd without an OS App icon (and used by the legend)."""
    if kind == 'oa':  # arrow pointing in
        return (f'<path d="M{r(cx - 8)} {r(cy)} H{r(cx + 5)} M{r(cx + 1)} {r(cy - 4)} '
                f'L{r(cx + 6)} {r(cy)} L{r(cx + 1)} {r(cy + 4)}" '
                'fill="none" stroke="#1b4f72" stroke-width="1.6"/>')
    if kind in ('cooling_coil', 'heating_coil'):  # zigzag coil
        pts = ' '.join(f'{r(cx - 9 + i * 3)},{r(cy + (-4 if i % 2 == 0 else 4))}'
                       for i in range(7))
        stroke = '#a04000' if kind == 'heating_coil' else '#1b4f72'
        return f'<polyline points="{pts}" fill="none" stroke="{stroke}" stroke-width="1.6"/>'
    if kind in ('fan', 'pump'):  # circle with a blade tick
        return (f'<circle cx="{r(cx)}" cy="{r(cy)}" r="7" fill="none" stroke="#145a32" stroke-width="1.6"/>'
                f'<line x1="{r(cx)}" y1="{r(cy)}" x2="{r(cx + 5)}" y2="{r(cy - 3)}" '
                'stroke="#145a32" stroke-width="1.6"/>')
    if kind == 'boiler':  # flame / up-triangle
        return (f'<path d="M{r(cx)} {r(cy - 7)} L{r(cx + 6)} {r(cy + 6)} '
                f'L{r(cx - 6)} {r(cy + 6)} Z" fill="#922b21"/>')
    if kind == 'chiller':  # snowflake
        s = 7
        return ('<g stroke="#154360" stroke-width="1.5">'
                f'<line x1="{r(cx - s)}" y1="{r(cy)}" x2="{r(cx + s)}" y2="{r(cy)}"/>'
                f'<line x1="{r(cx)}" y1="{r(cy - s)}" x2="{r(cx)}" y2="{r(cy + s)}"/>'
                f'<line x1="{r(cx - 5)}" y1="{r(cy - 5)}" x2="{r(cx + 5)}" y2="{r(cy + 5)}"/>'
                f'<line x1="{r(cx - 5)}" y1="{r(cy + 5)}" x2="{r(cx + 5)}" y2="{r(cy - 5)}"/></g>')
    if kind == 'tower':  # down chevrons (heat rejection)
        return (f'<path d="M{r(cx - 7)} {r(cy - 4)} L{r(cx)} {r(cy + 1)} L{r(cx + 7)} {r(cy - 4)} '
                f'M{r(cx - 7)} {r(cy + 1)} L{r(cx)} {r(cy + 6)} L{r(cx + 7)} {r(cy + 1)}" '
                'fill="none" stroke="#0e6251" stroke-width="1.6"/>')
    if kind == 'heat_pump':  # circle with up + down arrows (bidirectional heat transfer)
        return (f'<circle cx="{r(cx)}" cy="{r(cy)}" r="7.5" fill="none" stroke="#0b5345" stroke-width="1.5"/>'
                f'<path d="M{r(cx - 3)} {r(cy + 4)} V{r(cy - 4)} M{r(cx - 5)} {r(cy - 1)} '
                f'L{r(cx - 3)} {r(cy - 4)} L{r(cx - 1)} {r(cy - 1)}" '
                'fill="none" stroke="#0b5345" stroke-width="1.3"/>'
                f'<path d="M{r(cx + 3)} {r(cy - 4)} V{r(cy + 4)} M{r(cx + 1)} {r(cy + 1)} '
                f'L{r(cx + 3)} {r(cy + 4)} L{r(cx + 5)} {r(cy + 1)}" '
                'fill="none" stroke="#0b5345" stroke-width="1.3"/>')
    if kind == 'district':  # external plant: little building with a roof
        return (f'<rect x="{r(cx - 7)}" y="{r(cy - 1)}" width="14" height="7" '
                'fill="none" stroke="#6c3483" stroke-width="1.4"/>'
                f'<path d="M{r(cx - 8)} {r(cy - 1)} L{r(cx)} {r(cy - 7)} L{r(cx + 8)} {r(cy - 1)}" '
                'fill="none" stroke="#6c3483" stroke-width="1.4"/>')
    if kind == 'hx':  # diamond
        return (f'<path d="M{r(cx)} {r(cy - 7)} L{r(cx + 7)} {r(cy)} L{r(cx)} {r(cy + 7)} '
                f'L{r(cx - 7)} {r(cy)} Z" fill="none" stroke="#6c3483" stroke-width="1.6"/>')
    if kind == 'water_heater':
        return (f'<circle cx="{r(cx)}" cy="{r(cy)}" r="7" fill="none" stroke="#6c3483" stroke-width="1.6"/>'
                f'<line x1="{r(cx)}" y1="{r(cy - 4)}" x2="{r(cx)}" y2="{r(cy + 4)}" '
                'stroke="#6c3483" stroke-width="1.6"/>')
    if kind == 'zone':  # served-zone box with a divider
        return (f'<rect x="{r(cx - 7)}" y="{r(cy - 6)}" width="14" height="12" '
                'fill="none" stroke="#566573" stroke-width="1.4"/>'
                f'<line x1="{r(cx)}" y1="{r(cy - 6)}" x2="{r(cx)}" y2="{r(cy + 6)}" '
                'stroke="#566573" stroke-width="1"/>')
    if kind in ('terminal', 'fan_coil'):  # diffuser / terminal: down-pointing wedge
        return (f'<path d="M{r(cx - 7)} {r(cy - 5)} H{r(cx + 7)} L{r(cx)} {r(cy + 6)} Z" '
                'fill="none" stroke="#5d6d7e" stroke-width="1.5"/>')
    if kind == 'baseboard':  # low finned box
        return (f'<rect x="{r(cx - 8)}" y="{r(cy - 2)}" width="16" height="7" '
                'fill="none" stroke="#a04000" stroke-width="1.4"/>'
                f'<path d="M{r(cx - 6)} {r(cy - 2)} V{r(cy - 6)} M{r(cx)} {r(cy - 2)} '
                f'V{r(cy - 6)} M{r(cx + 6)} {r(cy - 2)} V{r(cy - 6)}" '
                'stroke="#a04000" stroke-width="1.2"/>')
    if kind == 'water_use':  # tap / droplet
        return (f'<path d="M{r(cx)} {r(cy - 7)} C{r(cx + 6)} {r(cy)} {r(cx + 4)} {r(cy + 6)} '
                f'{r(cx)} {r(cy + 6)} C{r(cx - 4)} {r(cy + 6)} {r(cx - 6)} {r(cy)} '
                f'{r(cx)} {r(cy - 7)} Z" fill="none" stroke="#1b4f72" stroke-width="1.4"/>')
    return f'<circle cx="{r(cx)}" cy="{r(cy)}" r="5" fill="none" stroke="#555" stroke-width="1.4"/>'


# ------------------------------------------------------------- diagrams
# Each loop is drawn as a VERTICAL CASCADE matching the OpenStudio App's
# GridItem.cpp layout: the SUPPLY equipment as a horizontal row on TOP, a
# labelled center connector band, then the DEMAND side on the BOTTOM as a
# splitter -> parallel branches (stacked vertically) -> mixer, closed by
# left/right risers with flow arrows so it reads as circulation.

# Fixed pixel geometry mirroring the OS App's ~90px GridItem grid. Every
# constant is FIXED (never derived from component count or container width) so
# a cell is the same physical size in every diagram and wide/tall loops SCROLL
# in .diagram (overflow-x:auto) instead of rescaling.
GRID      = 90    # OS App grid cell (setGridPos*100 there; scaled here)
CELL_W    = 130   # component cell width
CELL_H    = 44    # component cell height
CELL_HGAP = 30    # gap between series cells (left -> right)
CELL_VGAP = 16    # gap between vertically-stacked parallel branches
NODE_R    = 6     # splitter / mixer / connection node radius (~15px in OS App)
BUS_TAP   = 24    # splitter/mixer bus stand-off from the branch content
BAND_H    = 58    # center connector band height (Supply/Demand labels + nodes)
ZONE_W    = 156   # air-demand zone cell width
ZHEAD_H   = 24    # zone cell header height
ZROW_H    = 18    # one zone-level row (equipment) inside the zone cell
ZONE_PAD  = 10    # zone cell bottom padding
PBR_W     = 202   # plant-demand branch cell width (fits zone-labelled coils on two lines)
EDGE      = 24    # closing-riser inset from the svg edge
EDGE_GAP  = 22    # gap between a closing riser and the content
PAD_TOP   = 14    # top padding above the supply row
PAD_BOT   = 16    # bottom padding below the demand block


def loop_diagram_svg(loop):
    """Dispatch: air loops draw a zone branch on demand; plant loops draw the
    served loads as parallel demand branches. Both share the vertical cascade."""
    return air_loop_diagram(loop) if loop['kind'] == 'air' else plant_loop_diagram(loop)


def air_loop_diagram(loop):
    """AIR loop cascade: SUPPLY row on top (OA + coils/fan/hx), then ONE demand
    branch PER served zone (splitter -> stacked zone branches -> mixer); each
    zone branch = [air terminal cell] -> [zone cell listing the zone's ZoneHVAC*
    equipment]. Single-zone systems show 1 branch, multi-zone show 2."""
    accent = LOOP_COLORS.get('air', '#555')
    supply = loop['supply'] if loop['supply'] else None
    return render_cascade('Air loop diagram', accent, supply,
                          air_demand_branches(loop['demand'], accent))


def plant_loop_diagram(loop):
    """PLANT loop cascade: SUPPLY row on top (pump -> boiler/chiller/tower/...,
    setpoint tick at the outlet), DEMAND on the bottom as splitter -> PARALLEL
    branch cells (one per served-load group, incl. zone-level baseboard /
    fan-coil coils) stacked vertically -> mixer."""
    accent = LOOP_COLORS.get(loop['kind'], '#555')
    supply = loop['supply'] if loop['supply'] else None
    label = f"{LOOP_LABELS.get(loop['kind'], 'Loop')} diagram"
    return render_cascade(label, accent, supply,
                          plant_demand_branches(loop['demand'], accent), setpoint=True)


def render_cascade(title, accent, supply, demand_specs, setpoint=False):
    """Assemble a full cascade: measure the supply row and the demand stack, place
    supply on TOP and demand on the BOTTOM (padded to a shared content width and
    centered), then draw the center band and the closing risers between them."""
    sup = measure_supply(supply)
    dem = measure_demand(demand_specs)
    content_w = max(sup['w'], dem['w'])

    content_x0 = EDGE + EDGE_GAP
    left_riser_x = EDGE
    right_riser_x = content_x0 + content_w + EDGE_GAP
    svg_w = right_riser_x + EDGE
    center_x = content_x0 + content_w / 2.0

    supply_top = PAD_TOP
    supply_cy = supply_top + sup['h'] / 2.0
    band_top = supply_top + sup['h']
    demand_top = band_top + BAND_H
    svg_h = demand_top + dem['h'] + PAD_BOT

    supply_x0 = content_x0 + (content_w - sup['w']) / 2.0
    demand_x0 = content_x0 + (content_w - dem['w']) / 2.0

    s = draw_supply(sup, accent, supply_x0, supply_cy, setpoint=setpoint)
    d = draw_demand(dem, accent, demand_x0, demand_top)

    out = [open_svg(svg_w, svg_h, title)]
    out.extend(closing_risers(accent, left_riser_x, right_riser_x, s, d))
    out.extend(center_band(accent, center_x, band_top, demand_top))
    out.extend(s['parts'])
    out.extend(d['parts'])
    out.append('</svg>')
    return ''.join(out)


# ---- supply row (TOP) ----

def measure_supply(cols):
    """Measure the supply row: a mix of single-cell SERIES columns and a stacked
    PARALLEL column (genuinely parallel equipment, each branch itself a short
    left->right series). Columns may differ in width, so widths are summed; row
    height grows to fit the tallest parallel column."""
    if cols is None or not cols:
        cols = [{'cells': [None]}]
    dims = [supply_col_dims(col) for col in cols]
    return {'cols': cols, 'dims': dims,
            'w': sum(d[0] for d in dims) + (len(cols) - 1) * CELL_HGAP,
            'h': max(d[1] for d in dims)}


def supply_col_dims(col):
    """[width, height] of one supply column: a series cell is one CELL_W box; a
    parallel column is as wide as its longest branch series and as tall as its
    stacked branches."""
    if not col.get('parallel'):
        return [CELL_W, CELL_H]

    n = len(col['branches'])
    max_len = max(len(b) for b in col['branches'])
    return [max_len * CELL_W + (max_len - 1) * CELL_HGAP,
            n * CELL_H + (n - 1) * CELL_VGAP]


def draw_supply(sup, accent, x0, cy, setpoint=False):
    """Draw the supply row left->right in flow order. Series columns (one cell) are
    joined by horizontal pipes with flow arrows; a parallel column is drawn as
    its branch series stacked vertically between a splitter (left) and mixer
    (right) node — straight from the loop's real splitter, never from a count.
    Returns the row's inlet/outlet points for the closing risers."""
    parts = []
    inlet = None
    outlet = None
    prev_right = None
    col_x = x0
    for i, col in enumerate(sup['cols']):
        col_w = sup['dims'][i][0]
        if col.get('parallel'):
            left_pt, right_pt = draw_supply_parallel(parts, col, accent, col_x, col_w, cy)
        else:
            parts.append(supply_cell(col_x, cy - CELL_H / 2.0, col['cells'][0], accent))
            left_pt = [col_x, cy]
            right_pt = [col_x + CELL_W, cy]
        if prev_right:
            parts.append(svg_line(prev_right[0], cy, left_pt[0], cy, accent, stroke_width=2))
            parts.append(flow_arrow((prev_right[0] + left_pt[0]) / 2.0, cy, 'right', accent))
        if inlet is None:
            inlet = left_pt
        outlet = right_pt
        prev_right = right_pt
        col_x += col_w + CELL_HGAP
    if setpoint and outlet:
        parts.append(setpoint_tick(outlet[0] + 9, cy, accent))
    return {'parts': parts, 'inlet': inlet, 'outlet': outlet}


def draw_supply_parallel(parts, col, accent, col_x, col_w, cy):
    """Draw a parallel supply column: N branches (each a left->right series of
    cells) stacked vertically between a splitter dot (left) and mixer dot
    (right). Returns the column's [left, right] connection points."""
    branches = col['branches']
    n = len(branches)
    col_h = n * CELL_H + (n - 1) * CELL_VGAP
    top = cy - col_h / 2.0
    sx = col_x - CELL_HGAP * 0.45
    mx = col_x + col_w + CELL_HGAP * 0.45
    for j, cells in enumerate(branches):
        cyj = top + j * (CELL_H + CELL_VGAP) + CELL_H / 2.0
        bx = col_x
        for k, branch_cell in enumerate(cells):
            if k > 0:
                parts.append(svg_line(bx - CELL_HGAP, cyj, bx, cyj, accent, stroke_width=1.4))
                parts.append(flow_arrow(bx - CELL_HGAP / 2.0, cyj, 'right', accent))
            parts.append(supply_cell(bx, cyj - CELL_H / 2.0, branch_cell, accent))
            bx += CELL_W + CELL_HGAP
        branch_right = col_x + len(cells) * CELL_W + (len(cells) - 1) * CELL_HGAP
        parts.append(svg_line(sx, cy, col_x, cyj, accent, stroke_width=1.2))
        parts.append(svg_line(branch_right, cyj, mx, cy, accent, stroke_width=1.2))
    parts.append(node_dot(sx, cy, accent, 'Supply splitter (parallel equipment)'))
    parts.append(node_dot(mx, cy, accent, 'Supply mixer (parallel equipment)'))
    return [sx, cy], [mx, cy]


def supply_cell(x, y, data, accent):
    """One supply cell for a classified component. The visible line is the SPECIFIC
    label (e.g. "DX heating coil" vs "Electric heating coil", "Centrifugal
    chiller", "Constant-volume fan"), truncated to the fixed cell width; the
    full label + raw iddObjectType + object name live in the <title> tooltip."""
    if data is None:
        return cell(x, y, CELL_W, CELL_H, 'other', 'No components', '',
                    'No classified supply components on this loop', accent)

    return cell(x, y, CELL_W, CELL_H, data['kind'], data['label'], None,
                data['tooltip'], accent, idd=data['idd'])


def cell(x, y, w, h, kind, line1, _line2, tooltip, accent, idd=None):
    """A single component cell: the real OS App icon (or the hand-drawn glyph
    fallback) on the left, one or two text lines, and a native <title> tooltip.
    Fixed geometry; used by supply and plant demand. The loop-kind color remains
    the box fill/border.
    The type label is word-wrapped to fit the cell so specific types are never
    truncated; the object name is intentionally omitted (it is noise here and
    already lives in the <title> tooltip). `_line2` is retained for signature
    compatibility but ignored."""
    fill = KIND_COLORS.get(kind, '#d5d8dc')
    tx = x + 32
    budget = max(math.floor((w - 40) / 5.7), 8)
    lines = wrap_label(line1, budget, 2)
    parts = ['<g class="cell">', f'<title>{esc(tooltip)}</title>']
    parts.append(svg_rect(x, y, w, h, fill, stroke=accent, rx=6, stroke_width=1.4))
    parts.append(component_mark(kind, idd, x + 4, y + h / 2.0, 24))
    if len(lines) <= 1:
        parts.append(svg_text(tx, y + h / 2.0 + 3.5, str(lines[0]),
                              font_weight='bold', font_size=10))
    else:
        parts.append(svg_text(tx, y + h / 2.0 - 2.5, lines[0],
                              font_weight='bold', font_size=10))
        parts.append(svg_text(tx, y + h / 2.0 + 9.5, lines[1],
                              font_weight='bold', font_size=10))
    parts.append('</g>')
    return ''.join(parts)


# ---- demand stack (BOTTOM) ----

def measure_demand(branch_specs):
    """Measure the demand block: a shared content width (branches padded to match)
    and the total stacked height. Width includes the splitter/mixer bus taps."""
    content_w = max(b['content_w'] for b in branch_specs)
    stack_h = sum(b['content_h'] for b in branch_specs) + (len(branch_specs) - 1) * CELL_VGAP
    return {'branches': branch_specs, 'content_w': content_w,
            'w': 2 * NODE_R + 2 * BUS_TAP + content_w, 'h': stack_h}


def draw_demand(dem, accent, x0, top):
    """Draw the demand block: a splitter node + vertical bus on the LEFT, N branches
    stacked vertically (each its own horizontal row rendered by its spec), and a
    mixer node + vertical bus on the RIGHT. Small tap dots where branches meet
    the buses. Returns the splitter/mixer points for the closing risers."""
    split_x = x0 + NODE_R
    content_x = split_x + BUS_TAP
    mixer_x = content_x + dem['content_w'] + BUS_TAP
    dcy = top + dem['h'] / 2.0

    centers = []
    y = top
    for b in dem['branches']:
        centers.append(y + b['content_h'] / 2.0)
        y += b['content_h'] + CELL_VGAP

    parts = []
    parts.append(svg_line(split_x, centers[0], split_x, centers[-1], accent, stroke_width=2))
    parts.append(svg_line(mixer_x, centers[0], mixer_x, centers[-1], accent, stroke_width=2))
    for i, b in enumerate(dem['branches']):
        bcy = centers[i]
        parts.append(svg_line(split_x, bcy, content_x, bcy, accent, stroke_width=1.4))
        parts.append(svg_line(content_x + b['content_w'], bcy, mixer_x, bcy, accent,
                              stroke_width=1.4))
        parts.append(flow_arrow(content_x - 8, bcy, 'right', accent))
        parts.append(tap_dot(split_x, bcy, accent))
        parts.append(tap_dot(mixer_x, bcy, accent))
        parts.append('<g class="demand-branch">{}</g>'.format(b['render'](content_x, bcy)))
    parts.append(node_dot(split_x, dcy, accent, 'Demand splitter (inlet)', css='demand-splitter'))
    parts.append(node_dot(mixer_x, dcy, accent, 'Demand mixer (outlet)', css='demand-mixer'))
    return {'parts': parts, 'splitter': [split_x, dcy], 'mixer': [mixer_x, dcy]}


def air_demand_branches(zones, accent):
    """The air-loop demand: one branch PER served zone = [air terminal cell] ->
    [zone cell listing that zone's ZoneHVAC* equipment], stacked vertically
    between the demand splitter and mixer. One branch for single-zone systems,
    two for multi-zone (the diagram is built on at most 2 zones)."""
    zone_list = [None] if zones is None or not zones else zones
    specs = []
    for zone in zone_list:
        rows = zone_container_rows(zone)
        zone_h = ZHEAD_H + len(rows) * ZROW_H + ZONE_PAD
        content_h = max(CELL_H, zone_h)

        def render(cx, cy, zone=zone, rows=rows, zone_h=zone_h):
            term = zone['terminal'] if zone else None
            tk = 'terminal' if term else 'other'
            t_label = term['label'] if term else 'No terminal'
            t_tip = term['tooltip'] if term else 'No air terminal on this zone'
            t_idd = term['idd'] if term else None
            zx = cx + CELL_W + CELL_HGAP
            parts = [cell(cx, cy - CELL_H / 2.0, CELL_W, CELL_H, tk, t_label, None,
                          t_tip, accent, idd=t_idd)]
            parts.append(svg_line(cx + CELL_W, cy, zx, cy, accent, stroke_width=1.4))
            parts.append(flow_arrow((cx + CELL_W + zx) / 2.0, cy, 'right', accent))
            parts.append(zone_cell(zx, cy - zone_h / 2.0, zone_h, zone, rows, accent))
            return ''.join(parts)

        specs.append({'content_w': CELL_W + CELL_HGAP + ZONE_W,
                      'content_h': content_h, 'render': render})
    return specs


def plant_demand_branches(branch_lists, accent):
    """The plant-loop demand: one stacked branch per PARALLEL demand branch, drawn
    straight from the demand splitter's outlets (never a count). Each branch is a
    left->right series of served-load cells (a fan-coil / baseboard coil, an
    air-handler coil, a cooled chiller condenser, a heat-pump source, water use);
    in practice a served branch is a single cell, but a multi-cell series draws
    faithfully. An empty demand shows a single "No loads" note."""
    branch_list = [None] if branch_lists is None or not branch_lists else branch_lists
    specs = []
    for cells in branch_list:
        n = 1 if cells is None else len(cells)
        content_w = n * PBR_W + (n - 1) * CELL_HGAP

        def render(cx, cy, cells=cells):
            if cells is None:
                return plant_branch_cell(cx, cy - CELL_H / 2.0, None, accent)

            bx = cx
            parts = []
            for k, c in enumerate(cells):
                if k > 0:
                    parts.append(svg_line(bx - CELL_HGAP, cy, bx, cy, accent, stroke_width=1.4))
                    parts.append(flow_arrow(bx - CELL_HGAP / 2.0, cy, 'right', accent))
                parts.append(plant_branch_cell(bx, cy - CELL_H / 2.0, c, accent))
                bx += PBR_W + CELL_HGAP
            return ''.join(parts)

        specs.append({'content_w': content_w, 'content_h': CELL_H, 'render': render})
    return specs


def plant_branch_cell(x, y, branch, accent):
    if branch is None:
        branch = {'kind': 'other', 'label': 'No loads',
                  'tooltip': 'No demand-side loads on this loop'}
    return cell(x, y, PBR_W, CELL_H, branch.get('kind') or 'other', str(branch['label']), None,
                branch['tooltip'], accent, idd=branch.get('idd'))


def zone_container_rows(zone):
    """The zone-equipment rows listed inside an air-loop zone cell: each ZoneHVAC*
    unit (baseboard, PTAC, fan coil, unit heater). The air TERMINAL is drawn as
    its own upstream cell, so it is NOT repeated here. Never empty."""
    rows = []
    for eq in (zone['equipment'] if zone else None) or []:
        kind = 'baseboard' if re.search(r'baseboard', eq['label'], re.I) else 'other'
        rows.append({'kind': kind, 'text': eq['label'], 'count': eq['count'],
                     'tooltip': eq['tooltip'], 'idd': eq['idd']})
    if not rows:
        rows.append({'kind': 'zone', 'text': 'no zone equipment', 'count': None})
    return rows


def zone_cell(x, y, h, zone, rows, accent):
    """The air-loop demand zone cell: header = the served zone's name, with the
    zone-equipment rows stacked inside it. One cell per served zone."""
    name = str(zone['zone_name']) if zone else ''
    head = 'Served zone' if name == '' else f'Zone: {truncate(name, 18)}'
    tip = zone['tooltip'] if zone else 'Served zone'
    parts = ['<g class="cell zone-cell">', f'<title>{esc(tip)}</title>']
    parts.append(svg_rect(x, y, ZONE_W, h, '#eef2f5', stroke=accent, rx=6, stroke_width=1.6))
    parts.append(icon_use('OS_ThermalZone', x + 5, y + 4, 16) or glyph('zone', x + 14, y + 13))
    parts.append(svg_text(x + 26, y + 16, head, font_weight='bold', font_size=9, fill=accent))
    parts.append(svg_line(x + 6, y + ZHEAD_H - 3, x + ZONE_W - 6, y + ZHEAD_H - 3,
                          '#c9d3da', stroke_width=1))
    for i, row in enumerate(rows):
        ry = y + ZHEAD_H + i * ZROW_H + ZROW_H / 2.0
        parts.append('<g>')
        if row.get('tooltip'):
            parts.append('<title>{}</title>'.format(esc(row['tooltip'])))
        parts.append(icon_use(row.get('idd'), x + 7, ry - 8, 16)
                     or row_glyph(row['kind'], x + 15, ry))
        count = row['count'] if row['count'] is not None else 0
        text = '{} ×{}'.format(row['text'], row['count']) if count > 1 else row['text']
        parts.append(svg_text(x + 28, ry + 3.5, truncate(text, 22), font_size=9))
        parts.append('</g>')
    parts.append('</g>')
    return ''.join(parts)


# ---- center band + closing risers ----

def center_band(accent, center_x, band_top, band_bot):
    """The center connector band between supply and demand: the "Supply Equipment"
    / "Demand Equipment" labels, the supply-outlet and demand-inlet nodes, and a
    central feed pipe carrying flow down from the supply block into the demand."""
    mid = (band_top + band_bot) / 2.0
    return [
        svg_line(center_x, band_top, center_x, band_bot, accent,
                 stroke_width=1.6, stroke_dasharray='4 3'),
        flow_arrow(center_x, mid + 4, 'down', accent),
        band_label('Supply Equipment', center_x, band_top + 18, accent),
        band_label('Demand Equipment', center_x, band_bot - 7, accent),
        node_dot(center_x, band_top, accent, 'Supply outlet node'),
        node_dot(center_x, band_bot, accent, 'Demand inlet node'),
    ]


def band_label(text, cx, y, accent):
    """A band label with a white halo so the central feed pipe does not strike
    through the text."""
    w = len(text) * 5.7 + 8
    return (svg_rect(cx - w / 2.0, y - 10, w, 14, '#ffffff')
            + svg_text(cx, y, text, text_anchor='middle', font_weight='bold',
                       font_size=10, fill=accent))


def closing_risers(accent, lx, rx, s, d):
    """The closing risers that make it read as a closed loop: the supply OUTLET
    runs out to the right edge and DOWN to the demand mixer (arrow down); the
    demand splitter runs to the left edge and UP to the supply INLET (arrow up)."""
    w = 2
    s_in = s['inlet']
    s_out = s['outlet']
    d_split = d['splitter']
    d_mix = d['mixer']
    return [
        svg_line(lx, s_in[1], s_in[0], s_in[1], accent, stroke_width=w),
        svg_line(lx, d_split[1], d_split[0], d_split[1], accent, stroke_width=w),
        svg_line(lx, s_in[1], lx, d_split[1], accent, stroke_width=w),
        flow_arrow(lx, (s_in[1] + d_split[1]) / 2.0, 'up', accent),
        svg_line(s_out[0], s_out[1], rx, s_out[1], accent, stroke_width=w),
        svg_line(d_mix[0], d_mix[1], rx, d_mix[1], accent, stroke_width=w),
        svg_line(rx, s_out[1], rx, d_mix[1], accent, stroke_width=w),
        flow_arrow(rx, (s_out[1] + d_mix[1]) / 2.0, 'down', accent),
    ]


def tap_dot(x, y, accent):
    """A small filled node where a branch taps a splitter/mixer bus."""
    return f'<circle cx="{r(x)}" cy="{r(y)}" r="2.6" fill="{accent}"/>'


def row_glyph(kind, cx, cy):
    """Small in-container row glyph (terminal wedge, baseboard fins, or generic dot)."""
    if kind == 'terminal':
        return (f'<path d="M{r(cx - 6)} {r(cy - 4)} H{r(cx + 6)} L{r(cx)} {r(cy + 5)} Z" '
                'fill="none" stroke="#1a5276" stroke-width="1.3"/>')
    if kind == 'baseboard':
        return (f'<rect x="{r(cx - 6)}" y="{r(cy - 2)}" width="12" height="5" '
                'fill="none" stroke="#a04000" stroke-width="1.2"/>')
    return f'<circle cx="{r(cx)}" cy="{r(cy)}" r="3.4" fill="none" stroke="#555" stroke-width="1.3"/>'


def node_dot(x, y, accent, label, css=None):
    """A loop node (splitter / mixer / connection point) — a hollow dot with a
    tooltip and an optional CSS class for the demand splitter/mixer markers."""
    cls = f' class="{css}"' if css else ''
    return (f'<g{cls}><title>{esc(label)}</title>'
            f'<circle cx="{r(x)}" cy="{r(y)}" r="{NODE_R}" fill="#fff" '
            f'stroke="{accent}" stroke-width="1.8"/></g>')


def setpoint_tick(x, y, accent):
    """A setpoint-manager tick at a supply outlet node."""
    return ('<g><title>Setpoint node (supply outlet)</title>'
            f'<line x1="{r(x)}" y1="{r(y - 7)}" x2="{r(x)}" y2="{r(y + 7)}" '
            f'stroke="{accent}" stroke-width="1.6"/>'
            f'<circle cx="{r(x)}" cy="{r(y - 9)}" r="2.4" fill="{accent}"/></g>')


def flow_arrow(x, y, direction, color):
    if direction == 'down':
        return (f'<path d="M{r(x - 5)} {r(y - 4)} L{r(x + 5)} {r(y - 4)} '
                f'L{r(x)} {r(y + 5)} Z" fill="{color}"/>')
    if direction == 'up':
        return (f'<path d="M{r(x - 5)} {r(y + 4)} L{r(x + 5)} {r(y + 4)} '
                f'L{r(x)} {r(y - 5)} Z" fill="{color}"/>')
    if direction == 'right':
        return (f'<path d="M{r(x - 4)} {r(y - 5)} L{r(x - 4)} {r(y + 5)} '
                f'L{r(x + 5)} {r(y)} Z" fill="{color}"/>')
    if direction == 'left':
        return (f'<path d="M{r(x + 4)} {r(y - 5)} L{r(x + 4)} {r(y + 5)} '
                f'L{r(x - 5)} {r(y)} Z" fill="{color}"/>')
    return None


def zone_equipment_svg(zones_data):
    """The Zone equipment tab: one zone container per built zone (reusing the
    air-demand zone_cell), stacked vertically — NOT collapsed into counts."""
    if not zones_data:
        return '<p class="note">No zone equipment on this system.</p>'

    accent = '#5d6d7e'
    gap = 14
    metrics = []
    for z in zones_data:
        rows = zone_container_rows(z)
        metrics.append([z, rows, ZHEAD_H + len(rows) * ZROW_H + 8])
    total_h = sum(m[2] for m in metrics) + (len(metrics) - 1) * gap + 16
    parts = [open_svg(ZONE_W + 20, total_h, 'Zone equipment')]
    y = 8
    for z, rows, h in metrics:
        parts.append(zone_cell(10, y, h, z, rows, accent))
        y += h + gap
    parts.append('</svg>')
    return ''.join(parts)


def truncate(string, max_len):
    s = '' if string is None else str(string)
    return f'{s[:max_len - 1]}…' if len(s) > max_len else s


def wrap_label(string, max_chars, max_lines=2):
    """Word-wrap a label into at most `max_lines` lines of ~`max_chars` each so the
    full specific type (e.g. "Chilled-water cooling coil") shows instead of
    being truncated. Overflowing words hard-truncate as a last resort."""
    lines = ['']
    for word in re.split(r'\s+', '' if string is None else str(string)):
        if not lines[-1]:
            lines[-1] = word
        elif len(lines[-1]) + 1 + len(word) <= max_chars:
            lines[-1] = f'{lines[-1]} {word}'
        elif len(lines) < max_lines:
            lines.append(word)
        else:
            lines[-1] = f'{lines[-1]} {word}'
    return [f'{line[:max_chars - 1]}…' if len(line) > max_chars else line for line in lines]


# ---------------------------------------------------------------- HTML

def assemble(cards):
    by_family = {}
    for c in cards:
        by_family.setdefault(c['row']['family'], []).append(c)
    families = sorted(by_family.keys(), key=lambda f: FAMILY_TITLES.get(f, f).lower())

    idx = 0
    ordered = {}
    for family in families:
        ordered[family] = sorted(by_family[family], key=lambda c: c['row']['name'])
        for c in ordered[family]:
            c['id'] = f'sys-{idx}'
            idx += 1
    total = len(cards)
    display_cards = [c for f in families for c in ordered[f]]

    out = ['<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">']
    out.append('<meta name="viewport" content="width=device-width, initial-scale=1">')
    out.append('<title>OpenStudio-HVAC System Catalog</title>')
    out.append(f'<style>{CSS}</style></head><body>')
    # The embedded OS App icons: every data-URI lives ONCE in this hidden master
    # defs; component cells reference them by id via <use>.
    out.append(icon_defs())
    out.append(topbar(total, len(families)))
    out.append('<div class="app">')
    out.append(sidebar(families, ordered, total))
    out.append('<main class="detail-pane">')
    out.append(''.join(detail_html(c, i == 0) for i, c in enumerate(display_cards)))
    out.append('</main></div>')
    out.append(footer())
    out.append(f'<script>{script(total)}</script>')
    out.append('</body></html>')
    return ''.join(out)


def topbar(total, family_count):
    return (f'<header class="topbar"><h1>OpenStudio-HVAC System Catalog</h1>'
            f'<p class="meta">{total} buildable HVAC systems across {family_count} families. '
            'Every diagram is extracted from a system actually built on the bundled 5-zone fixture — '
            'the topology cannot drift from what the gem assembles. Select a system on the left; hover '
            f'any component for details.</p>{legend()}</header>')


def legend():
    """Only the loop-colour key is shown: component symbols are the real
    OpenStudio App icons (self-labelled, with tooltips), so a glyph legend
    would just list marks the diagram no longer draws."""
    loop_keys = ''.join(
        f'<span class="lk"><span class="sw" style="background:{color}"></span>{esc(LOOP_LABELS[kind])}</span>'
        for kind, color in LOOP_COLORS.items())
    return (f'<div class="legend"><strong>Loops</strong>{loop_keys}'
            '<span class="lk-note">Component symbols are OpenStudio Application icons; '
            'hover any for details.</span></div>')


def sidebar(families, ordered, total):
    groups = []
    for family in families:
        items = []
        for card in ordered[family]:
            row = card['row']
            search = ' '.join(
                p for p in [row['name'], card['canonical'], family, row.get('sys_abbr')]
                if p is not None).lower()
            active = ' active' if card['id'] == 'sys-0' else ''
            # Always show the canonical (human-readable) name in the nav for
            # consistency; the exact argument name stays searchable + as a tooltip.
            items.append(
                '<button type="button" class="nav-item{}" data-target="{}" '.format(active, card['id'])
                + 'data-search="{}" title="{}">{}</button>'.format(
                    esc(search), esc(row['name']), esc(card['canonical'])))
        groups.append(
            '<div class="nav-family collapsed"><button type="button" class="nav-family-title">'
            '<span class="caret">&#9656;</span>{}</button>{}</div>'.format(
                esc(FAMILY_TITLES.get(family, family)), ''.join(items)))
    return ('<aside class="sidebar">'
            '<div class="search-wrap"><input type="search" id="system-search" placeholder="Search systems…" '
            f'autocomplete="off" aria-label="Search systems"><span id="search-count">{total} of {total}</span></div>'
            '<nav class="nav-list">{}</nav></aside>'.format(''.join(groups)))


def detail_html(card, first):
    row = card['row']
    badges = ['<span class="badge badge-family">{}</span>'.format(esc(row['family']))]
    if row.get('sys_abbr') is not None:
        badges.append('<span class="badge badge-sys">{}</span>'.format(esc(row['sys_abbr'])))
    active = ' active' if first else ''
    return ('<article class="system-detail{}" id="{}">'.format(active, card['id'])
            + '<div class="detail-head"><code>{}</code>{}</div>'.format(
                esc(row['name']), ''.join(badges))
            + '<div class="canonical">{}</div>'.format(esc(card['canonical']))
            + '<p class="desc">{}</p>'.format(esc(card['description']))
            + f'{tabs_html(card)}</article>')


def tabs_html(card):
    """Render the system's loops as TABS (one per loop present), plus a
    zone-equipment tab if there is any. Tab switching is scoped per system by
    the inline JS, so switching tabs on the shown system can't affect others."""
    if card.get('topology') is None:
        note = ': {}'.format(esc(card['diagram_error'])) if card.get('diagram_error') else ''
        return ('<p class="note note-err">Diagram unavailable — this system did not build '
                f'on the fixture{note}.</p>')

    topology = card['topology']
    loops = topology['air_loops'] + topology['plant_loops']
    tabs = []
    seen = {}
    for loop in loops:
        base = LOOP_LABELS.get(loop['kind'], 'Loop')
        seen[base] = seen.get(base, 0) + 1
        label = f'{base} {seen[base]}' if seen[base] > 1 else base
        tabs.append({'label': label, 'body': loop_diagram_svg(loop)})
    if topology['zone_equipment']:
        tabs.append({'label': 'Zone equipment',
                     'body': zone_equipment_svg(topology['zone_equipment'])})

    if not tabs:
        return '<p class="note">No central loops or zone equipment were assembled for this system.</p>'

    sys_id = card['id']
    bar = ''.join(
        '<button type="button" class="tab{}" data-tab="{}-t{}">{}</button>'.format(
            ' active' if i == 0 else '', sys_id, i, esc(t['label']))
        for i, t in enumerate(tabs))
    panels = ''.join(
        '<div class="tab-panel{}" id="{}-t{}"><div class="diagram">{}</div></div>'.format(
            ' active' if i == 0 else '', sys_id, i, t['body'])
        for i, t in enumerate(tabs))
    return f'<div class="tabs"><div class="tab-bar">{bar}</div>{panels}</div>'


def footer():
    try:
        version = openstudio.openStudioVersion()
    except Exception:
        version = '?'
    return ('<footer><p>Generated by BtapModeling::CatalogReport — self-contained, '
            f'no external requests. OpenStudio {version}.</p>'
            '<p>Component icons &copy; the OpenStudio Coalition, from the OpenStudio Application '
            '(BSD-3-Clause). See THIRD_PARTY_NOTICES.md.</p></footer>')


def script(total):
    """Plain inline JS — no libraries. Handles search filtering, master-detail
    selection, and per-system tab switching via one delegated click handler."""
    return SCRIPT_JS.replace('#{total}', str(total))


# The inline JS, verbatim from the Ruby heredoc; `#{total}` is substituted by
# `script(total)` exactly where Ruby interpolated it.
SCRIPT_JS = """(function(){
  var TOTAL = #{total};
  function selectSystem(id){
    var d = document.querySelectorAll('.system-detail');
    for (var i = 0; i < d.length; i++){ d[i].classList.remove('active'); }
    var el = document.getElementById(id);
    if (el){ el.classList.add('active'); }
    var n = document.querySelectorAll('.nav-item');
    for (var j = 0; j < n.length; j++){
      n[j].classList.toggle('active', n[j].getAttribute('data-target') === id);
    }
    window.scrollTo(0, 0);
  }
  document.addEventListener('click', function(e){
    var tab = e.target.closest ? e.target.closest('.tab') : null;
    if (tab){
      var bar = tab.parentNode, box = bar.parentNode;
      var tabs = bar.querySelectorAll('.tab');
      for (var i = 0; i < tabs.length; i++){ tabs[i].classList.remove('active'); }
      tab.classList.add('active');
      var panels = box.querySelectorAll('.tab-panel');
      for (var k = 0; k < panels.length; k++){ panels[k].classList.remove('active'); }
      var target = document.getElementById(tab.getAttribute('data-tab'));
      if (target){ target.classList.add('active'); }
      return;
    }
    var famTitle = e.target.closest ? e.target.closest('.nav-family-title') : null;
    if (famTitle){ famTitle.parentNode.classList.toggle('collapsed'); return; }
    var nav = e.target.closest ? e.target.closest('.nav-item') : null;
    if (nav){ selectSystem(nav.getAttribute('data-target')); }
  });
  var search = document.getElementById('system-search');
  if (search){
    search.addEventListener('input', function(){
      var q = this.value.trim().toLowerCase(), visible = 0;
      var fams = document.querySelectorAll('.nav-family');
      for (var f = 0; f < fams.length; f++){
        var any = false, items = fams[f].querySelectorAll('.nav-item');
        for (var i = 0; i < items.length; i++){
          var match = items[i].getAttribute('data-search').indexOf(q) >= 0;
          // Clearing the inline style (match/empty-query) lets the
          // .collapsed CSS rule hide items again when search is empty.
          items[i].style.display = match ? '' : 'none';
          if (match){ any = true; visible++; }
        }
        fams[f].style.display = any ? '' : 'none';
        // While searching, auto-expand families with a match and collapse
        // those without; when the box is cleared, re-collapse everything.
        if (q){ fams[f].classList.toggle('collapsed', !any); }
        else { fams[f].classList.add('collapsed'); }
      }
      var c = document.getElementById('search-count');
      if (c){ c.textContent = visible + ' of ' + TOTAL; }
    });
  }
})();
"""

CSS = """* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: -apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
       color: #111; background: #f4f6f8; line-height: 1.45; font-size: 14px; }
.topbar { background: #fff; border-bottom: 1px solid #d0d7de; padding: 1rem 1.5rem; }
h1 { font-size: 1.45rem; margin-bottom: .2rem; }
p.meta { color: #444; font-size: .85rem; max-width: 60rem; margin-bottom: .5rem; }
.legend { font-size: .78rem; margin: .25rem 0; display: flex; flex-wrap: wrap; gap: .7rem; align-items: center; }
.legend strong { margin-right: .2rem; }
.lk-note { color: #667; font-style: italic; }
.lk, .gk { display: inline-flex; align-items: center; gap: .3rem; white-space: nowrap; }
.sw { display: inline-block; width: .9rem; height: .9rem; border-radius: .2rem; }
.gk-svg { width: 20px; height: 20px; }

.app { display: flex; align-items: flex-start; gap: 1rem; padding: 1rem 1.5rem; }
.sidebar { flex: 0 0 300px; width: 300px; position: sticky; top: 1rem;
           max-height: calc(100vh - 2rem); overflow-y: auto; background: #fff;
           border: 1px solid #d0d7de; border-radius: .5rem; padding: .6rem; }
.search-wrap { position: sticky; top: 0; background: #fff; padding-bottom: .5rem;
               display: flex; flex-direction: column; gap: .25rem; }
#system-search { width: 100%; padding: .45rem .6rem; font-size: .9rem; border: 1px solid #b8c0c8;
                 border-radius: .4rem; }
#search-count { font-size: .72rem; color: #667; padding-left: .1rem; }
.nav-family { margin-top: .5rem; }
.nav-family-title { display: flex; align-items: center; gap: .3rem; width: 100%; border: none;
                    background: none; font: inherit; font-size: .68rem; text-transform: uppercase;
                    letter-spacing: .04em; color: #667; font-weight: 700; cursor: pointer;
                    text-align: left; padding: .3rem .3rem .15rem; }
.nav-family-title:hover { color: #1a5276; }
.caret { display: inline-block; font-size: .8em; transition: transform .12s ease; }
.nav-family:not(.collapsed) .caret { transform: rotate(90deg); }
.nav-family.collapsed .nav-item { display: none; }
.nav-item { display: block; width: 100%; text-align: left; border: none; background: none;
            font: inherit; font-size: .8rem; color: #24313c; padding: .3rem .5rem; border-radius: .35rem;
            cursor: pointer; word-break: break-word; }
.nav-item:hover { background: #eef2f5; }
.nav-item.active { background: #1a5276; color: #fff; font-weight: 600; }

.detail-pane { flex: 1; min-width: 0; background: #fff; border: 1px solid #d0d7de;
               border-radius: .5rem; padding: 1rem 1.2rem; }
.system-detail { display: none; }
.system-detail.active { display: block; }
.detail-head { display: flex; flex-wrap: wrap; gap: .5rem; align-items: center; }
.detail-head code { font-size: 1rem; font-weight: 700; background: #eef2f5; padding: .2rem .5rem;
                    border-radius: .3rem; word-break: break-word; }
.badge { display: inline-block; padding: .1rem .5rem; border-radius: .3rem; font-weight: 700;
         font-size: .72rem; color: #fff; }
.badge-family { background: #34495e; } .badge-sys { background: #1a5276; }
.canonical { font-size: 1rem; font-weight: 600; color: #1a5276; margin: .5rem 0 .15rem; }
.desc { font-size: .85rem; color: #444; margin-bottom: .8rem; }

.tabs { margin-top: .4rem; }
.tab-bar { display: flex; flex-wrap: wrap; gap: .2rem; border-bottom: 2px solid #d0d7de; margin-bottom: .6rem; }
.tab { border: none; background: none; font: inherit; font-size: .82rem; font-weight: 600; color: #555;
       padding: .4rem .8rem; cursor: pointer; border-bottom: 2px solid transparent; margin-bottom: -2px; }
.tab:hover { color: #1a5276; }
.tab.active { color: #1a5276; border-bottom-color: #1a5276; }
.tab-panel { display: none; }
.tab-panel.active { display: block; }
.diagram { overflow-x: auto; }
/* Render SVGs at their intrinsic size (fixed box/gap constants) so a
   component box is the same physical size in every system; wide loops
   scroll horizontally in .diagram instead of shrinking to fit. */
.diagram svg { width: auto; height: auto; max-width: none; display: block; }

.chips { display: flex; flex-wrap: wrap; gap: .4rem; }
.chip-eq { display: inline-block; background: #e8f0f3; border: 1px solid #aebfc9; border-radius: 1rem;
           padding: .15rem .7rem; font-size: .8rem; font-weight: 600; color: #21618c; }
.note { font-size: .82rem; color: #555; font-style: italic; margin: .3rem 0; }
.note-err { color: #9a6700; font-style: normal; font-weight: 600; }
footer { margin: 1.5rem; font-size: .75rem; color: #555; }

@media (max-width: 760px) {
  .app { flex-direction: column; }
  .sidebar { position: static; width: 100%; flex-basis: auto; max-height: 40vh; }
}
@media print {
  .sidebar, .topbar .legend { display: none; }
  .system-detail { display: block; break-inside: avoid; }
  .tab-panel { display: block; }
  * { print-color-adjust: exact; -webkit-print-color-adjust: exact; }
}
"""
