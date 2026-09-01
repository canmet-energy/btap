"""NECB performance-path helpers: reference HVAC selection (Table 8.4.4.7.-A/-B) and
the proposed->reference transform (port of btap-necb's hvac/reference.rb).

All rule content lives in data/reference_rules_<vintage>.json (vendored, with
article-level provenance); this code is a rules interpreter, not a rules store.

Port notes (D-79): Ruby's symbol keys collapse to str throughout — the
characterization facts dict, the building info dict and the assignment actions
('build' / 'copy_proposed' / 'through_the_wall') are all str-keyed/str-valued.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

import openstudio

from btap._compat import NullAudit, opt, ruby_round, sorted_by_name
from btap.audit import emit_coverage
from btap.costing.hvac import geometry as _costing_geometry
from btap.modeling.hvac import classify as _classify
from btap.modeling.hvac.components import coils as _coils
from btap.modeling.hvac.components import schedules as _schedules

RULES_DIR = Path(__file__).parent / "data"

_RULES: dict[str, dict] = {}


def rules(vintage):
    """Load (and memoize) the vendored NECB reference ruleset for a vintage.

    :param vintage: NECB vintage ('2020' or '2025')
    :return: dict — parsed data/reference_rules_<vintage>.json
    """
    key = str(vintage)
    if key not in _RULES:
        path = RULES_DIR / f"reference_rules_{key}.json"
        if not path.exists():
            raise ValueError(
                f"no NECB reference rules for vintage '{key}' (expected {path})")
        with open(path, encoding="utf-8") as f:
            _RULES[key] = json.load(f)
    return _RULES[key]


@dataclass
class Assignment:
    """One reference-system assignment for a group of zones."""

    zones: list = field(default_factory=list)
    category: str | None = None
    reference_system: object = None
    catalog_name: str | None = None
    config: dict | None = None
    energy_type: str | None = None
    action: str | None = None
    articles: list = field(default_factory=list)


def select_reference_systems(*, facts, building, vintage='2020', audit=None,
                             proposed_annual=None):
    """Select the NECB reference HVAC system for every zone group of a characterized
    model. Pure logic: no model access — everything comes from the facts dict (see
    btap.modeling.characterize) and the building info.

    :param facts: dict — btap.modeling.characterize output
    :param building: dict — 'storeys' (above-ground count), 'zone_types'
        ({zone name => space-type description string}), optional 'kitchen_hood_zones',
        'refrigerated_zones' (lists of zone names for conditions the model cannot express)
    :param vintage: str, e.g. '2020'
    :param audit: AuditLog or None
    :return: list[Assignment]
    """
    audit = audit if audit is not None else NullAudit()
    ruleset = rules(vintage)
    selection = ruleset['selection']
    definitions = ruleset['system_definitions']
    hp_rules = ruleset['heat_pump_reference']

    assignments = []
    for group in facts['zone_groups']:
        if not (group['heated'] or group['cooled']):
            continue  # unconditioned: no reference system

        category = _category_for(group, building, selection, audit)
        assignment = _assign(group, category, building, selection, audit)
        result = _finalize(assignment, group, definitions, selection, facts, audit,
                           hp_rules=hp_rules, proposed_annual=proposed_annual)
        if result is not None:
            assignments.append(result)
    return assignments


# ---- category election: majority space-type keyword match over the group's zones ----

def _category_for(group, building, selection, audit):
    votes: dict = {}
    for zone_name in group['zones']:
        type_ = str((building.get('zone_types') or {}).get(zone_name) or '').lower()
        row = None
        for cat in selection['categories']:
            if any(kw.lower() in type_ for kw in cat['keywords']):
                row = cat
                break
        key = row['category'] if row else None
        votes[key] = votes.get(key, 0) + 1
    category = max(votes.items(),
                   key=lambda kv: (kv[1], 0 if kv[0] is None else 1))[0]
    named = [k for k in votes if k is not None]
    if len(named) > 1:
        audit.warn('selection',
                   '8.4.4.7.(1) assigns systems PER THERMAL BLOCK, but this zone group mixes '
                   f"categories {' / '.join(named)} — majority ({category}) applied "
                   'to the whole group',
                   target=group['air_loop'] or group['zones'][0],
                   article='8.4.4.7.(1)', ruling='D-22')
    if category is None:
        category = selection['default_category']
        seen = []
        for z in group['zones']:
            t = (building.get('zone_types') or {}).get(z)
            if t is not None and t not in seen:
                seen.append(t)
        audit.warn('selection',
                   'space type not listed in Table 8.4.4.7.-A — closest-corresponding category assumed',
                   target=group['air_loop'] or group['zones'][0],
                   inputs={'zone_types': seen},
                   value=category, article='8.4.4.7.(3)')
    _audit_museum_row(group, building, category, audit)
    return category


def _audit_museum_row(group, building, category, audit):
    """D-45: a museum space can read as two Table 8.4.4.7.-A rows — Assembly Area
    lists "exhibit space", Historical Collections Area lists "archival library,
    museum and gallery archives". The ruling reads the latter as the ARCHIVES of
    museums and galleries (the row is a COLLECTIONS row, and System 2's close
    control suits stored collections), so a museum's public exhibition gallery is
    an exhibit space -> Assembly Area, while its archives and
    restoration/conservation rooms -> Historical Collections. Recorded whenever a
    museum space is elected so the reader sees which row was taken and why, rather
    than having to infer it from the system number."""
    types = []
    for z in group['zones']:
        t = (building.get('zone_types') or {}).get(z)
        if t is None:
            continue
        if 'museum' in str(t).lower() and t not in types:
            types.append(t)
    if not types:
        return

    audit.info('selection',
               f'museum space classified as {category} — the Table 8.4.4.7.-A collections row '
               'covers museum and gallery ARCHIVES; a public exhibition gallery is an exhibit '
               'space and takes the assembly row',
               target=group['air_loop'] or group['zones'][0],
               inputs={'space_types': types, 'category': category},
               article='8.4.4.7.(1)', ruling='D-45')


# ---- rule application per category ----

def _assign(group, category, building, selection, audit):
    cat = next(c for c in selection['categories'] if c['category'] == category)
    articles = [selection['article']]
    storeys = int(building.get('storeys') or 0)

    for rule in cat['rules']:
        if rule.get('special') == 'residential':
            return _residential_assignment(group, category, selection, articles, audit)
        if rule.get('max_storeys') and storeys > rule['max_storeys']:
            continue
        if rule.get('min_storeys') and storeys < rule['min_storeys']:
            continue
        if not _condition_met(rule, group, building, audit):
            continue

        if rule.get('min_cooling_kw_exclusive'):
            kw = group['design_cooling_kw']
            if kw is None:
                audit.warn('selection',
                           'cooling-capacity threshold rule needs a sized model — smaller-system branch assumed',
                           target=group['air_loop'] or group['zones'][0], article=rule['article'])
                continue
            if not kw > rule['min_cooling_kw_exclusive']:
                continue

        if rule.get('article'):
            articles.append(rule['article'])
        return Assignment(zones=group['zones'], category=category,
                          reference_system=rule['reference_system'],
                          action='build', articles=[a for a in articles if a is not None])

    # no rule matched (e.g. storey band gap) — fall back to the last, most general rule
    fallback = [r for r in cat['rules'] if not r.get('special')][-1]
    return Assignment(zones=group['zones'], category=category,
                      reference_system=fallback['reference_system'],
                      action='build', articles=[a for a in articles if a is not None])


def _condition_met(rule, group, building, audit):
    condition = rule.get('condition')
    if condition == 'kitchen_hood':
        # A hood is a condition the MODEL cannot express — only the
        # building['kitchen_hood_zones'] override can assert it. Electing the
        # unhooded row without the override ever being provided is an ASSUMPTION
        # the audit must state, not a silent default: the hooded row selects
        # System 4 instead of 3 (Table -A Supermarket/Food row).
        if 'kitchen_hood_zones' not in building:
            audit.warn('selection',
                       'no kitchen_hood_zones override provided — food-preparation spaces in this '
                       'block are ASSUMED to have no kitchen hood or vented appliance (the hooded '
                       'row would select System 4); pass building: {kitchen_hood_zones: [...]} if '
                       'any space has one',
                       target=','.join(group['zones']),
                       article='Table 8.4.4.7.-A (Supermarket/Food Service)')
        zones = set(group['zones'])
        return any(z in zones for z in (building.get('kitchen_hood_zones') or []))
    if condition == 'refrigerated':
        if 'refrigerated_zones' not in building:
            audit.warn('selection',
                       'no refrigerated_zones override provided — warehouse spaces in this block '
                       'are ASSUMED non-refrigerated (a refrigerated space would select System 5 '
                       'instead of 4); pass building: {refrigerated_zones: [...]} if any space is',
                       target=','.join(group['zones']),
                       article='Table 8.4.4.7.-A (Warehouse Area)')
        zones = set(group['zones'])
        return any(z in zones for z in (building.get('refrigerated_zones') or []))
    return True


def _residential_assignment(group, category, selection, articles, audit):
    res = selection['special_rules']['residential']
    articles = articles + [res['article']]
    # D-34 (A1, phylroy 2026-07-27): follow legacy — a residential block whose
    # proposed system includes a heat pump takes the 8.4.4.7.(4) ASHP redirect,
    # NOT the Table -A "(or heat pumps)" identical-to-proposed parenthetical.
    # (Legacy's necb_reference_hp flag builds the reference-hp variant for every
    # family, residential included; it has no copy branch at all — L-11.) The
    # System-1 assignment below is flipped to 'hp' by finalize's override.
    # D-37 narrows this to REDIRECTING heat pumps: a residential water-loop HP
    # stays on the Table -A residential rules (8.4.4.13.(1)) — its 'wshp'
    # family lands in the compatible-cooling copy branch.
    if _heat_pump_redirects(group):
        audit.decision('selection',
                       'residential with heat pump -> ASHP reference redirect (A1/D-34: follow legacy)',
                       target=','.join(group['zones']), article='8.4.4.7.(4)', ruling='D-34')
        return Assignment(zones=group['zones'], category=category, reference_system=1,
                          action='build', articles=articles + ['8.4.4.7.(4)'])
    if group['heated'] and not group['cooled']:
        audit.decision('selection', 'residential heated-only -> System 1',
                       target=','.join(group['zones']), article=res['article'])
        return Assignment(zones=group['zones'], category=category, reference_system=1,
                          action='build', articles=articles)
    if group['cooled'] and _residential_compatible_cooling(group):
        audit.decision('selection', 'residential with compatible cooling -> reference identical to proposed',
                       target=','.join(group['zones']),
                       inputs={'zonal_units': group.get('zonal_units'),
                               'loop_dx_cooling': group.get('loop_dx_cooling'),
                               'family': group.get('family') or group.get('family_guess')},
                       article=res['article'], ruling='D-58')
        return Assignment(zones=group['zones'], category=category, reference_system=None,
                          action='copy_proposed', articles=articles)
    audit.decision('selection', 'residential otherwise -> through-the-wall systems',
                   target=','.join(group['zones']),
                   inputs={'zonal_units': group.get('zonal_units'),
                           'loop_dx_cooling': group.get('loop_dx_cooling'),
                           'family': group.get('family') or group.get('family_guess')},
                   article=res['article'], ruling='D-58')
    return Assignment(zones=group['zones'], category=category, reference_system=1,
                      action='through_the_wall', articles=articles)


def _heat_pump_redirects(group):
    """D-37 (A2 ruled, phylroy 2026-07-28): the printed 8.4.4.13 split, with the
    boundary from Note A-8.4.4.13 — a water-LOOP heat pump (internal loop; aux
    boiler and/or cooling tower explicitly allowed) KEEPS its Table -A selection
    per sentence (1); air-, water- and ground-SOURCE heat pumps redirect to the
    ASHP reference per sentence (2). A detected heat pump with no source evidence
    keeps the redirect (pre-D-37 behavior — the conservative reading when the
    source loop is unclassifiable)."""
    if not group.get('heat_pump'):
        return False

    sources = group.get('heat_pump_sources') or []
    if not sources:
        return True

    return any(s != 'water_loop' for s in sources)


# 'air-cooled unitary, packaged terminal or room air conditioner, or fan coils'
# (the "(or heat pumps)" parenthetical is superseded by the 8.4.4.7.(4)
# redirect per D-34 — REDIRECTING heat-pump groups never reach this check;
# water-loop HPs do per D-37 and 'wshp' is in the allowlist).
#
# D-58: the test is FACT-based, not name-based. The 97-system matrix showed
# three ways the old family-string allowlist got Table -A wrong:
#  * legacy pipe names put family STRINGS into 'family_guess', which the old
#    symbol test never matched — the fleet hotels' 53-zone MAU+PTAC guest
#    blocks (zc>ptac, verbatim "packaged terminal air conditioner" in the
#    parenthetical) were getting through-the-wall instead of the copy the
#    printed table requires;
#  * a scrubbed-name (foreign) MAU + fan-coil/PTAC building lost the copy
#    because the structural guess reads the AIR LOOP only;
#  * DOAS + fan-coil composites cool their zones with fan coils but carry a
#    'doas'/'composite' family.
# The facts: zones cooled by packaged-terminal/room units or fan coils
# ('zonal_units'), or by the loop's own DX on a no-reheat constant-volume
# single-package shape ('loop_dx_cooling').
COMPATIBLE_RESIDENTIAL_FAMILIES = ('psz', 'mau_ptac', 'zone_terminal', 'fan_coils',
                                   'wshp', 'vrf')
COMPATIBLE_ZONAL_UNITS = ('ptac', 'pthp', 'fan_coil', 'vrf_terminal', 'wshp')


def _residential_compatible_cooling(group):
    if group.get('family_guess') in ('zonal_heat_cool', 'packaged_single_zone'):
        return True
    if (str(group.get('family')) in COMPATIBLE_RESIDENTIAL_FAMILIES
            or str(group.get('family_guess')) in COMPATIBLE_RESIDENTIAL_FAMILIES):
        return True
    if any(u in COMPATIBLE_ZONAL_UNITS for u in (group.get('zonal_units') or [])):
        return True

    return (group.get('air_loop') is not None and group.get('loop_dx_cooling') is True
            and group.get('terminal_type') in ('none', 'cv'))


# ---- finalize: heat-pump override, energy type, catalog name ----

def _finalize(assignment, group, definitions, selection, facts, audit,
              hp_rules=None, proposed_annual=None):
    if assignment.action == 'copy_proposed':
        return assignment

    hp_rule = selection['special_rules']['heat_pump']
    hp_article = heat_pump_article_base(selection)
    if _heat_pump_redirects(group) and assignment.reference_system in hp_rule['applies_to_systems']:
        audit.decision('selection',
                       'proposed heat pump -> reference is an air-source heat pump (Table 8.4.4.13)',
                       target=','.join(group['zones']),
                       inputs={'selected_system': assignment.reference_system,
                               'heat_pump_sources': group.get('heat_pump_sources')},
                       value='hp', article=hp_rule['article'], ruling='D-37')
        assignment.reference_system = 'hp'
        assignment.articles.append(hp_rule['article'])
    elif group.get('heat_pump') and not _heat_pump_redirects(group):
        audit.decision('selection',
                       'water-loop heat pump — Table 8.4.4.7.-A selection retained (no ASHP redirect)',
                       target=','.join(group['zones']),
                       inputs={'selected_system': assignment.reference_system},
                       article=f'{hp_article}.(1); Note A-{hp_article}', ruling='D-37')

    assignment.energy_type = None
    if assignment.reference_system == 'hp':
        assignment.energy_type = heat_pump_aux_energy_type(
            group, facts, hp_rules, proposed_annual, audit, article_base=hp_article)
    if assignment.energy_type is None:
        assignment.energy_type = _reference_energy_type(group, selection, facts, audit)
    definition = definitions[str(assignment.reference_system)]
    variant = definition[assignment.energy_type]
    assignment.catalog_name = variant['name']
    assignment.config = variant.get('config')

    # D-39 (A4 ruled conditional, phylroy 2026-07-28): Table 8.4.4.7.-B lists
    # System 5's heating as "None", but 8.4.4.1.(5) requires the presence or
    # absence of heating per thermal block to be IDENTICAL to the proposed.
    # Reconciliation: the table's "None" governs the default composition
    # (cooling-only TPFC when the proposed block is unheated); sentence (5)
    # overrides presence when the proposed block IS heated (the existing
    # two-pipe changeover heating is kept — no system invented).
    if assignment.reference_system == 5:
        if group['heated']:
            audit.decision('selection',
                           'System 5 reference keeps its heating — proposed block is heated, '
                           '8.4.4.1.(5) presence override of the Table -B "None" heating column',
                           target=','.join(group['zones']),
                           article='8.4.4.1.(5); Table 8.4.4.7.-B', ruling='D-39')
        else:
            merged = dict(assignment.config or {})
            merged.update({'heating': 'none', 'needs_boiler': False,
                           'mau_heating_coil_type': 'None'})
            assignment.config = merged
            audit.decision('selection',
                           'System 5 reference built COOLING-ONLY — Table 8.4.4.7.-B heating "None" '
                           'honoured (proposed block is unheated)',
                           target=','.join(group['zones']),
                           article='Table 8.4.4.7.-B; 8.4.4.1.(5)', ruling='D-39')

    # 8.4.4.6.(2)/8.4.5.6.(2): purchased cooling is represented by an air-cooled
    # electric chiller.
    if ((facts.get('purchased_energy') or {}).get('cooling')
            or 'Purchased' in group['cooling_energy_types']):
        pc = selection['special_rules']['purchased_cooling']
        merged = dict(assignment.config or {})
        merged['chw_source'] = pc['chiller_source']
        merged['purchased_cooling_reference_cop'] = pc['reference_cop']
        assignment.config = merged
        assignment.articles.append(pc['article'])
        audit.decision('selection', 'purchased cooling energy -> represented by air-cooled electric chiller',
                       target=','.join(group['zones']), article=pc['article'])

    audit.decision('selection', 'reference system selected',
                   target=group['air_loop'] or ','.join(group['zones']),
                   inputs={'category': assignment.category, 'energy_type': assignment.energy_type,
                           'heated': group['heated'], 'cooled': group['cooled'],
                           'cooling_kw': group['design_cooling_kw']},
                   value=f"System {assignment.reference_system} -> '{assignment.catalog_name}'",
                   article='; '.join(_uniq([a for a in assignment.articles if a is not None])))
    return assignment


def _uniq(items):
    """Ruby Array#uniq — order-preserving."""
    seen = []
    for item in items:
        if item not in seen:
            seen.append(item)
    return seen


# ==================== the proposed -> reference HVAC transform ====================

@dataclass
class ReferenceResult:
    model: object = None
    assignments: list = field(default_factory=list)
    audit: object = None


def reference_hvac(model, vintage='2020', building=None, audit=None, proposed_annual=None):
    """Generate the NECB reference HVAC for a proposed model (any OSM). The proposed
    model is untouched: the reference is built on a clone.

    Pipeline (all article-tagged in the audit): characterize the proposed HVAC ->
    select reference systems per Table 8.4.4.7.-A -> replace each zone group's HVAC
    with the mapped catalog system (energy type follows proposed) -> apply the
    reference modeling rules (8.4.4.8 oversizing caps, 8.4.4.18 fan specs, 8.4.4.13
    heat-pump operating limits) -> apply vintage minimum efficiencies.

    Sizing: the package never runs simulations. Capacity-threshold selection rules and
    the proposed-oversizing comparison use sized values when present and warn when
    not; run your sizing pass on the proposed model first for full fidelity, and on
    the returned reference model before applying downstream (efficiencies re-apply
    cleanly via apply_efficiencies after sizing).

    :param model: the proposed openstudio.model.Model
    :param vintage: str
    :param building: dict or None — overrides for 'storeys', 'zone_types',
        'kitchen_hood_zones', 'refrigerated_zones' (defaults derived from the model)
    :param audit: AuditLog or None
    :return: ReferenceResult — model (clone), assignments, audit
    """
    import btap.modeling as modeling
    from btap.audit import AuditLog
    from btap.necb.hvac import efficiency as _efficiency

    audit = audit if audit is not None else AuditLog()
    reference = _clone_model(model)

    facts = _classify.characterize(reference, audit=audit)
    info = _building_info(reference, building, audit)
    assignments = select_reference_systems(facts=facts, building=info,
                                           vintage=vintage, audit=audit,
                                           proposed_annual=proposed_annual)

    ruleset = rules(vintage)
    zones_by_name = {z.nameString(): z for z in reference.getThermalZones()}
    # 8.4.3.2.(1): operating schedules identical in both buildings — capture
    # each zone's PROPOSED air-system availability schedule now, while the
    # clone still carries the proposed HVAC (D-14; feeds the reference fan
    # operation AND the 5.2.10.1 continuous/non-continuous classification).
    proposed_availability = {}
    for loop_ in reference.getAirLoopHVACs():
        for z in loop_.thermalZones():
            proposed_availability[z.nameString()] = loop_.availabilitySchedule()
    # 8.4.4.15.(2) (D-54): the proposed's demand-control-ventilation strategy must be
    # reproduced in the reference, but the loops that carry it are about to be torn
    # down. Index it per zone off the characterization, which ran while the clone
    # still held the proposed HVAC.
    proposed_dcv = {}
    for group in facts['zone_groups']:
        if group['air_loop'] is None:
            continue

        for zone_name in group['zones']:
            proposed_dcv[zone_name] = {'dcv': group['dcv'],
                                       'method': group['system_outdoor_air_method'],
                                       'air_loop': group['air_loop']}
    # T7 (8.4.4.15.(1)): OA identity rests on cloned DesignSpecification:OutdoorAir;
    # a hard-set proposed minimum-OA controller value would silently diverge.
    for c in reference.getControllerOutdoorAirs():
        if not c.minimumOutdoorAirFlowRate().is_initialized():
            continue

        audit.warn('build',
                   f"proposed OA controller '{c.nameString()}' carries a HARD-SET minimum OA "
                   f"({ruby_round(c.minimumOutdoorAirFlowRate().get() * 1000, 0)} L/s) — the rebuilt reference "
                   'autosizes OA from the space DSOA; verify 8.4.4.15.(1) identity',
                   article='8.4.4.15.(1)', ruling='D-22')
    # Table 8.4.4.7.-B note (1) (D-55): record every proposed thermal block's
    # humidification and its energy source BEFORE the teardown destroys the loops
    # that carry it — the rebuild happens once the reference loops exist.
    proposed_humidification = _capture_humidification(reference, audit)
    # D-28 (LargeOffice end-use isolation): Note (3) to Table 8.4.4.7.-B
    # scopes a MULTIZONE reference system to the thermal blocks of ALL
    # storeys — one system at <=4 above-ground storeys, per-facade splits
    # (inside the builder's zone_groups) above. The proposed archetypes
    # partition their zones per STOREY, and building one reference system
    # per selection group leaked that partition into the reference: the
    # 12-storey LargeOffice got 3 storey-groups x (4 facades + internal)
    # = 17 systems instead of ~6, multiplying fans and dodging the
    # per-loop 5.2.10.1/5.2.2.7 flow thresholds. Merge same-catalog
    # multizone (sys 2/5/6) build assignments; single-zone families
    # (1/3/4/hp) keep their selection grouping.
    merged = []
    for a in assignments:
        key = ([a.catalog_name, a.config]
               if a.action == 'build' and a.reference_system in (2, 5, 6) else None)
        existing = None
        if key is not None:
            existing = next((m for m in merged if m[0] == key), None)
        if existing is not None:
            existing[1].zones.extend([z for z in a.zones if z not in existing[1].zones])
            existing[1].articles.extend(a.articles)
        else:
            merged.append([key, a])
    if len(merged) < len(assignments):
        audit.decision('build', 'multizone selection groups merged into whole-building systems',
                       inputs={'selection_groups': len(assignments), 'merged_groups': len(merged)},
                       value='one multizone system spans the thermal blocks of all storeys; '
                             'facade/internal/underground split applied inside the builder',
                       article='Table 8.4.4.7.-B Note (3)', ruling='D-28')
    assignments = [m[1] for m in merged]

    purchased_cooling_chillers = []
    for assignment in assignments:
        if assignment.action == 'copy_proposed':
            audit.info('build', 'proposed system retained in reference (residential rule)',
                       target=','.join(assignment.zones),
                       article='; '.join(a for a in assignment.articles if a is not None))
            continue

        zones = [zones_by_name[n] for n in assignment.zones]
        existing_chillers = {str(chiller.handle())
                             for chiller in reference.getChillerElectricEIRs()}
        result = modeling.replace_system(reference, assignment.catalog_name, zones,
                                         config=assignment.config)
        purchased_cooling_cop = (assignment.config or {}).get(
            'purchased_cooling_reference_cop')
        if purchased_cooling_cop is not None:
            purchased_cooling_chillers.extend(
                (chiller, purchased_cooling_cop)
                for chiller in reference.getChillerElectricEIRs()
                if str(chiller.handle()) not in existing_chillers
            )
        audit.decision('build', 'reference system built', target=','.join(assignment.zones),
                       inputs={'system': assignment.reference_system, 'action': assignment.action},
                       value=assignment.catalog_name,
                       article='; '.join(_uniq([a for a in assignment.articles if a is not None])))
        _apply_fan_rules(result.air_loops, assignment.reference_system, ruleset, audit)
        _apply_zone_fan_rules(zones, assignment.reference_system, ruleset, audit)
        if assignment.reference_system == 'hp':
            _apply_heat_pump_limits(result.air_loops, ruleset, audit)
        _apply_economizers(reference, result.air_loops, assignment.reference_system,
                           vintage, ruleset, audit)
        _apply_dcv(result.air_loops, zones, proposed_dcv, vintage, audit)
        _apply_operating_schedules(result.air_loops, proposed_availability, audit)
        _audit_terminal_secondary_split(zones, assignment.reference_system, vintage, audit)

    _rebuild_humidification(reference, proposed_humidification, ruleset, vintage, audit)
    _purge_orphaned_ems(reference, audit)
    _apply_oversizing_caps(model, reference, ruleset, audit)
    _efficiency.apply(reference, vintage=vintage, audit=audit)
    for chiller, cop in purchased_cooling_chillers:
        chiller.setReferenceCOP(cop)
        audit.decision('efficiency', 'purchased-cooling reference chiller COP applied',
                       target=chiller.nameString(), value=f'COP {cop}',
                       article='Table 8.4.3.5')
    _emit_article_coverage(ruleset, audit)

    return ReferenceResult(model=reference, assignments=assignments, audit=audit)


def _audit_terminal_secondary_split(zones, reference_system, vintage, audit):
    """8.4.4.9.(3) / 8.4.4.10.(7) (2025: 8.4.5.9.(3)/8.4.5.10.(7)) — the
    terminal/secondary capacity split, D-50. Reference systems 1, 2 and 5 put
    heating and/or cooling in BOTH a zone terminal (PTAC / four- or two-pipe
    fan coil) and a make-up-air secondary system, so the sentences bind. The
    builder realizes them through Sizing:Zone dedicated-outdoor-air accounting
    with a neutral supply-air strategy: the terminal's design load excludes the
    ventilation air, and the combined pair still meets the design-day peak
    because both are sized on the same design day. Systems 3, 4 and 6 mix
    outdoor air into the supply stream instead of feeding it to the zone
    separately, so EnergyPlus has no equivalent accounting for them — declared,
    not silently assumed."""
    prefix = '8.4.5' if str(vintage) == '2025' else '8.4.4'
    article = f'{prefix}.9.(3); {prefix}.10.(7)'
    accounted = sum(1 for z in zones if z.sizingZone().accountforDedicatedOutdoorAirSystem())
    if accounted > 0:
        audit.decision('rules', 'terminal/secondary capacity split accounted at zone sizing',
                       target=','.join(z.nameString() for z in zones),
                       inputs={'zones': accounted, 'reference_system': reference_system,
                               'strategy': 'NeutralSupplyAir'},
                       value='terminal sized on the space load alone; the make-up-air unit carries the '
                             'ventilation load at system level',
                       article=article, ruling='D-50')
        return
    if reference_system not in (3, 4, 6, 'hp'):
        return

    audit.info('rules', f'system {reference_system} mixes outdoor air into the supply stream, so the '
                        'terminal/secondary split is approximated by ordinary mixed-air zone sizing '
                        '(baseboards take the residual space load the air system does not meet)',
               target=','.join(z.nameString() for z in zones),
               inputs={'zones': len(zones), 'reference_system': reference_system},
               article=article, ruling='D-50')


def _apply_zone_fan_rules(zones, reference_system, ruleset, audit):
    """T10 (audit 2026-07-25): 8.4.4.18.(3) fan spec (640 Pa / 40% combined)
    covers HVAC systems 1-5 — including their ZONE-equipment supply fans
    (fan coils, PTAC/PTHP OnOff fans), which previously kept SDK defaults."""
    if reference_system == 6:
        return

    spec = (ruleset.get('fans') or {}).get('systems_1_3_4_5', {}).get('supply') or {}
    pressure = spec.get('pressure_rise_pa') or 640.0
    eff = spec.get('total_efficiency') or 0.40
    touched = 0
    for zone in zones:
        for eq in zone.equipment():
            for opt_ in (eq.to_ZoneHVACFourPipeFanCoil(),
                         eq.to_ZoneHVACPackagedTerminalAirConditioner(),
                         eq.to_ZoneHVACPackagedTerminalHeatPump()):
                if opt_.empty():
                    continue

                fan = opt_.get().supplyAirFan()
                for f in (fan.to_FanOnOff(), fan.to_FanConstantVolume(),
                          fan.to_FanVariableVolume()):
                    if f.empty():
                        continue

                    f.get().setPressureRise(pressure)
                    f.get().setFanTotalEfficiency(eff)
                    touched += 1
    if touched == 0:
        return

    audit.decision('build', 'zone-equipment supply fans set to the systems 1-5 spec',
                   inputs={'fans': touched, 'pressure_pa': pressure, 'total_efficiency': eff},
                   value=f'{touched} zone fan(s) at {pressure} Pa / {ruby_round(eff * 100)}%',
                   article='8.4.4.18.(3)', ruling='D-22')


def apply_economizer_thresholds(model, audit=None):
    """T3 (audit 2026-07-25): 8.4.4.12 economizers apply only where Article
    5.2.2.7 applies to the proposed system — mechanical cooling AND (sized
    supply > 1500 L/s OR cooling capacity > 20 kW); dwelling-only/hotel
    systems exempt (approximated: System 1 already exempt per D-20; zone
    types are not re-derivable here). POST-SIZING pass, umbrella-called
    alongside apply_energy_recovery: strips economizers from loops below the
    trigger, loudly.

    :param model: sized reference openstudio.model.Model (modified in place)
    :param audit: AuditLog or None (a new one is created if None)
    :return: AuditLog — the audit carrying every keep/strip decision
    """
    from btap.audit import AuditLog

    audit = audit if audit is not None else AuditLog()
    for air_loop in sorted_by_name(model.getAirLoopHVACs()):
        oa = air_loop.airLoopHVACOutdoorAirSystem()
        if oa.empty():
            continue

        ctrl = oa.get().getControllerOutdoorAir()
        if ctrl.getEconomizerControlType() == 'NoEconomizer':
            continue

        supply = (optional_flow(air_loop.designSupplyAirFlowRate())
                  or optional_flow(air_loop.autosizedDesignSupplyAirFlowRate()))
        # coils.supply_components descends into AirLoopHVACUnitarySystem containers:
        # a staged reference system's DX capacity lives on the TOP stage inside the
        # unitary, invisible to a plain supplyComponents scan.
        components = _coils.supply_components(air_loop)
        cooling_w = 0.0
        for c in components:
            single = c.to_CoilCoolingDXSingleSpeed()
            if not single.empty():
                cooling_w += (optional_flow(single.get().ratedTotalCoolingCapacity())
                              or optional_flow(single.get().autosizedRatedTotalCoolingCapacity())
                              or 0.0)
                continue
            staged = c.to_CoilCoolingDXMultiSpeed()
            if staged.empty():
                continue

            stages = staged.get().stages()
            top = stages[-1] if len(stages) else None
            if top is None:
                continue

            cooling_w += (optional_flow(top.grossRatedTotalCoolingCapacity())
                          or optional_flow(top.autosizedGrossRatedTotalCoolingCapacity())
                          or 0.0)
        chw = any(c.to_CoilCoolingWater().is_initialized() for c in components)
        if supply is None:
            audit.warn('rules', f'{air_loop.nameString()}: supply flow not sized — 5.2.2.7 economizer trigger '
                                'not evaluated (economizer retained)',
                       article='5.2.2.7.(1)', ruling='D-22')
            continue
        # chilled-water systems (sys 2/5/6) are large by construction; the kW
        # branch is only decidable for DX. Trigger: >1500 L/s or >20 kW.
        triggered = (supply * 1000.0 > 1500.0 or cooling_w > 20_000.0
                     or (chw and supply * 1000.0 > 1500.0))
        if triggered:
            audit.decision('rules', 'economizer retained (5.2.2.7 trigger met)',
                           target=air_loop.nameString(),
                           inputs={'supply_l_s': ruby_round(supply * 1000, 0),
                                   'cooling_kw': ruby_round(cooling_w / 1000.0, 1)},
                           value=ctrl.getEconomizerControlType(),
                           article='8.4.4.12.; 5.2.2.7.(1)', ruling='D-22')
        else:
            ctrl.setEconomizerControlType('NoEconomizer')
            audit.decision('rules', 'economizer REMOVED — below the 5.2.2.7 trigger (<=1500 L/s and <=20 kW)',
                           target=air_loop.nameString(),
                           inputs={'supply_l_s': ruby_round(supply * 1000, 0),
                                   'cooling_kw': ruby_round(cooling_w / 1000.0, 1)},
                           value='NoEconomizer', article='8.4.4.12.; 5.2.2.7.(1)', ruling='D-22')
    return audit


_UUID_RE = re.compile(r'\{[0-9A-Fa-f]{8}-[0-9A-Fa-f-]{27}\}')


def _purge_orphaned_ems(model, audit):
    """D-16: proposed-model EMS artifacts (optimum-start programs etc.) whose
    referenced objects were removed with the proposed HVAC would reach
    EnergyPlus as unresolvable {UUID} tokens and FATAL the reference sizing
    run (found by the archetype breadth sweep: legacy sys_4 archetypes).
    Programs with dangling handle references are removed along with their
    calling managers; actuators whose targets are gone likewise. Every
    removal is audited — the reference's controls come from the reference
    ruleset, never from proposed EMS overrides."""
    def dangling(text):
        return any(model.getModelObject(openstudio.toUUID(u)).empty()
                   for u in _UUID_RE.findall(str(text)))

    removed = []
    for prog in list(model.getEnergyManagementSystemPrograms()):
        if not any(dangling(ln) for ln in prog.lines()):
            continue

        removed.append(f'program {prog.nameString()}')
        for mgr in list(model.getEnergyManagementSystemProgramCallingManagers()):
            for i, p in enumerate(mgr.programs()):
                if p.handle() == prog.handle():
                    mgr.eraseProgram(i)
            if len(mgr.programs()):
                continue

            removed.append(f'calling manager {mgr.nameString()}')
            mgr.remove()
        prog.remove()
    for act in list(model.getEnergyManagementSystemActuators()):
        if not act.actuatedComponent().empty():
            continue

        removed.append(f'actuator {act.nameString()}')
        act.remove()
    if not removed:
        return

    ellipsis = ' …' if len(removed) > 6 else ''
    audit.warn('build', 'proposed EMS artifacts with DANGLING references removed from the reference '
                        f"({len(removed)}): {'; '.join(removed[:6])}{ellipsis} — "
                        'reference controls come from the reference ruleset, not proposed EMS overrides',
               article='8.4.4.1.', ruling='D-16')


def _apply_unitary_operating_schedule(loop_, chosen):
    """A staged system's fan lives INSIDE its AirLoopHVACUnitarySystem, where the
    loop's availability schedule does not reach it — the unitary carries its own.
    Left at the always-on default, a staged reference fan runs 8760 h no matter
    what 8.4.3.2.(1) says the system's hours are: measured at 2.7x the proposed's
    fan energy on the Warehouse, against 0.98x for the same building before
    staging. So the unitary inherits the SAME schedule the loop just got. (Only
    the availability: the fan OPERATING MODE stays continuous, as a
    constant-volume system's does, and EnergyPlus rejects a mode schedule
    containing zeros for that field outright.)"""
    for comp in loop_.supplyComponents():
        unitary = comp.to_AirLoopHVACUnitarySystem()
        if unitary.empty():
            continue

        unitary.get().setAvailabilitySchedule(chosen)


def _apply_operating_schedules(air_loops, proposed_availability, audit):
    """D-14: reference air systems inherit the proposed's operating schedule
    (8.4.3.2.(1) — operating schedules identical in both buildings). One
    schedule among the loop's zones -> applied; none (proposed had no air
    system there, e.g. baseboards) -> builder default retained with an info
    note; several -> the schedule serving the most zones wins, with a loud
    warning. Schedules survive replace_system (removing a loop never deletes
    shared schedules)."""
    for loop_ in air_loops:
        schedules = [proposed_availability[z.nameString()] for z in loop_.thermalZones()
                     if proposed_availability.get(z.nameString()) is not None]
        if not schedules:
            # T5: harmless with Always On, correct once scheduled
            loop_.setNightCycleControlType('CycleOnAny')
            audit.info('build', 'no proposed air-system operating schedule to inherit — builder default retained',
                       target=loop_.nameString(), article='8.4.3.2.(1)', ruling='D-14')
            continue
        tally: dict = {}
        for s in schedules:
            tally.setdefault(s.nameString(), []).append(s)
        chosen = max(tally.items(), key=lambda kv: len(kv[1]))[1][0]
        loop_.setAvailabilitySchedule(chosen)
        # T5 (audit 2026-07-25, legacy parity): night-cycle pickup during the
        # off-schedule hours, and the motorized-OA-damper behaviour — minimum
        # OA follows the operating schedule so the reference does not
        # ventilate 24/7 through a scheduled-off system.
        loop_.setNightCycleControlType('CycleOnAny')
        oa = loop_.airLoopHVACOutdoorAirSystem()
        if oa.is_initialized():
            oa.get().getControllerOutdoorAir().setMinimumOutdoorAirSchedule(chosen)
        _apply_unitary_operating_schedule(loop_, chosen)
        if len(tally) > 1:
            audit.warn('build', f'zones carried {len(tally)} DIFFERENT proposed operating schedules — '
                                f"'{chosen.nameString()}' (most zones) applied to the whole reference loop",
                       target=loop_.nameString(), article='8.4.3.2.(1)', ruling='D-14')
        else:
            audit.decision('build', 'reference system operates on the proposed operating schedule',
                           target=loop_.nameString(), inputs={'schedule': chosen.nameString()},
                           value=chosen.nameString(), article='8.4.3.2.(1)', ruling='D-14')


def _emit_article_coverage(ruleset, audit):
    """Completeness accounting: every article of the reference subsection is written
    to the audit with its handling status and how many decisions cited it this run —
    unimplemented or partially-implemented articles surface as warnings, so a missed
    requirement is visible in every log rather than discovered by review."""
    emit_coverage(ruleset['article_coverage'], audit)


def _clone_model(model):
    clone = model.clone()
    return clone.to_Model() if hasattr(clone, 'to_Model') else clone


def _building_info(model, overrides, audit):
    """Building info defaults derived from the model, overridable by the caller."""
    info = {'storeys': _costing_geometry.above_ground_storeys(model),
            'zone_types': _zone_space_types(model)}
    if overrides:
        info.update(overrides)
    audit.info('characterize', 'building info for selection',
               inputs={'storeys': info['storeys'],
                       'typed_zones': sum(1 for v in info['zone_types'].values()
                                          if str(v or '') != '')})
    return info


_SPACE_FUNCTION_RE = re.compile(r'\ASpace Function\s*', re.IGNORECASE)


def _zone_space_types(model):
    """NECB standardsSpaceType per thermal zone (majority space type of the zone).

    :return: dict {zone name => NECB space type ('' when untagged)}"""
    out = {}
    for zone in model.getThermalZones():
        found = []
        for space in zone.spaces():
            st = space.spaceType()
            if not st.is_initialized():
                continue

            found.append(st.get().standardsSpaceType().get()
                         if st.get().standardsSpaceType().is_initialized()
                         else st.get().nameString())
        first = found[0] if found else None
        type_ = _SPACE_FUNCTION_RE.sub('', '' if first is None else str(first), count=1)
        out[zone.nameString()] = type_
    return out


def _apply_economizers(model, air_loops, reference_system, vintage, ruleset, audit):
    """8.4.4.12 (2025: 8.4.5.12): reference cooling-with-outside-air. Table -12
    routes systems 1/3/4/6 and all heat-pump systems to 5.2.2.8 (air economizer:
    up to 100% outdoor air, differential reversion) and systems 2/5 to 5.2.2.9
    (WATER-side economizer, built since D-56)."""
    prefix = '8.4.5' if str(vintage) == '2025' else '8.4.4'
    if reference_system in (2, 5):
        _apply_water_economizer(model, reference_system, vintage, ruleset, audit)
        return
    # D-20: NO economizer on System 1 (100%-outdoor-air makeup air). An air
    # economizer cannot increase OA above a system that is already all
    # outdoor air, and its winter signal (outdoor enthalpy < return) LOCKS
    # OUT the 5.2.10.1 energy-recovery wheel through the HX economizer
    # lockout — disabling mandated heat recovery for the entire heating
    # season (found by the MURB fixed-point audit: the reference MAU heated
    # -20 C air unassisted all January; legacy correctly uses NoEconomizer).
    if reference_system == 1:
        audit.info('build', 'System 1 (100% OA makeup air): economizer not applicable — an all-outdoor-air '
                            'system cannot economize, and the economizer signal would lock out the 5.2.10.1 '
                            'energy-recovery wheel all winter',
                   article=f'{prefix}.12.', ruling='D-20')
        return

    for air_loop in _array(air_loops):
        oa_system = air_loop.airLoopHVACOutdoorAirSystem()
        if oa_system.empty():
            continue

        has_cooling = any(re.search(r'Coil_Cooling|CoilSystem_Cooling',
                                    component.iddObjectType().valueName())
                          for component in _coils.supply_components(air_loop))
        if not has_cooling:
            continue

        controller = oa_system.get().getControllerOutdoorAir()
        controller.setEconomizerControlType('DifferentialEnthalpy')
        audit.decision('build',
                       'air economizer applied (5.2.2.8: up to 100% outdoor air, differential-enthalpy reversion)',
                       target=air_loop.nameString(),
                       article=f'{prefix}.12. (Table -12 -> 5.2.2.8)', ruling='D-20')


def _array(x):
    """Ruby Array(): Array(nil) == [], Array(x) == [x]."""
    if x is None:
        return []
    return list(x) if isinstance(x, (list, tuple)) else [x]


# ============ 5.2.2.9 water-side economizer, reference systems 2/5 (D-56) ============
#
# Table -12 sends reference systems 2 and 5 — the fan-coil systems, whose Table
# 8.4.4.7.-B row prescribes a WATER-COOLED water chiller — to 5.2.2.9 rather than
# to the air economizer of 5.2.2.8. 5.2.2.9 has two sentences, and WHICH ONE binds
# follows from the heat-rejection equipment:
#
#   (1) chilling the distribution fluid by direct or indirect EVAPORATION ->
#       capable of 100% of the cooling load at outdoor WET-BULB <= 7 C;
#   (2) chilling it by SENSIBLE heat transfer -> at outdoor DRY-BULB <= 10 C.
#
# The reference plant rejects heat through a CoolingTowerSingleSpeed, which is an
# evaporative device, so the economizer chills the chilled water by INDIRECT
# evaporation and sentence (1) governs. Sentence (2) would bind a dry-cooler
# arrangement, which the reference never builds — declared, not silently ignored.
#
# Realized as a plate heat exchanger between the condenser loop (source) and the
# chilled-water loop (load), plus the tower setpoint reset WITHOUT WHICH the
# economizer is inert: the builder pins the condenser loop at its 29 C design exit
# temperature, and a tower held at 29 C can never deliver water colder than the
# chilled-water return.

def _apply_water_economizer(model, reference_system, vintage, ruleset, audit):
    prefix = '8.4.5' if str(vintage) == '2025' else '8.4.4'
    article = f'{prefix}.12. (Table -12 -> 5.2.2.9)'
    spec = ruleset['water_economizer']
    loops = _chilled_water_loops(model)
    if not loops:
        audit.warn('build', f'reference system {reference_system} routes to the 5.2.2.9 water economizer but the '
                            'reference has NO chilled-water loop with a chiller — no economizer built',
                   article=article, ruling='D-56')
        return

    for chw in loops:
        _build_water_economizer(chw, reference_system, spec, article, audit)


def _chilled_water_loops(model):
    return [plant_loop for plant_loop in model.getPlantLoops()
            if len(plant_loop.supplyComponents(
                openstudio.model.ChillerElectricEIR.iddObjectType()))]


def _condenser_loop_for(chw):
    """The condenser loop is the one the chilled-water loop's water-cooled chillers
    reject into (their secondary plant loop)."""
    for c in chw.supplyComponents(openstudio.model.ChillerElectricEIR.iddObjectType()):
        secondary = c.to_ChillerElectricEIR().get().secondaryPlantLoop()
        if secondary.is_initialized():
            return secondary.get()
    return None


def _build_water_economizer(chw, reference_system, spec, article, audit):
    if len(chw.supplyComponents(openstudio.model.HeatExchangerFluidToFluid.iddObjectType())):
        audit.info('build', 'water-side economizer already present on this chilled-water loop — plant shared with '
                            'another reference system group', target=chw.nameString(),
                   article=article, ruling='D-56')
        return
    cw = _condenser_loop_for(chw)
    if cw is None:
        audit.warn('build', f'reference system {reference_system} routes to the 5.2.2.9 water economizer, but this '
                            'chilled-water loop rejects heat with NO condenser loop (air-cooled or purchased '
                            'cooling) — there is no evaporatively-cooled fluid to economize with, so none is built',
                   target=chw.nameString(), article=article, ruling='D-56')
        return

    hx = openstudio.model.HeatExchangerFluidToFluid(chw.model())
    hx.setName('Water-Side Economizer HX')
    hx.setHeatExchangeModelType(spec['heat_exchanger_model_type'])
    hx.setHeatTransferMeteringEndUseType(spec['metering_end_use'])
    # Capability, not a guess: sizing factor 1.0 on autosized UA and both design
    # flows sizes the exchanger to the loop's FULL design cooling load, which is
    # what "capable of ... 100% of the cooling load" asks for. Never hard-sized
    # (L-23) — the reference sizing run and the D-43 capacity iteration still govern.
    hx.autosizeHeatExchangerUFactorTimesAreaValue()
    hx.autosizeLoopSupplySideDesignFlowRate()
    hx.autosizeLoopDemandSideDesignFlowRate()
    hx.setSizingFactor(spec['sizing_factor'])
    hx.setControlType(spec['control_type'])
    if not (chw.addSupplyBranchForComponent(hx) and cw.addDemandBranchForComponent(hx)):
        hx.remove()
        audit.warn('build', 'the SDK REFUSED the water-side economizer topology on this plant — no economizer built',
                   target=chw.nameString(), article=article, ruling='D-56')
        return

    setpoint_c = chw.sizingPlant().designLoopExitTemperature()
    openstudio.model.SetpointManagerScheduled(
        chw.model(), _schedules.constant_ruleset(chw.model(), 'WSE HX Setpoint', setpoint_c)
    ).addToNode(hx.supplyOutletModelObject().get().to_Node().get())

    reset = _reset_condenser_setpoint(cw, spec, audit, setpoint_c)
    audit.decision('build', 'water-side economizer built (5.2.2.9: indirect evaporation, capable of 100% of the '
                            'cooling load at outdoor wet-bulb 7 C or lower)',
                   target=chw.nameString(),
                   inputs={'reference_system': reference_system, 'source_loop': cw.nameString(),
                           'control': spec['control_type'], 'setpoint_c': setpoint_c,
                           'sizing_factor': spec['sizing_factor'],
                           'capability_wet_bulb_c': spec['capability_wet_bulb_c'],
                           'condenser_setpoint_reset': reset},
                   value='HeatExchangerFluidToFluid between the condenser and chilled-water loops, sized for '
                         'the full design cooling load',
                   article=article, ruling='D-56')
    audit.info('build', 'the 5.2.2.9.(2) sensible-transfer criterion (outdoor dry-bulb 10 C or lower) does not '
                        'apply: the reference rejects heat through an evaporative cooling tower, so the '
                        'economizer chills the distribution fluid by indirect evaporation and sentence (1) binds',
               target=chw.nameString(),
               inputs={'capability_dry_bulb_c': spec['capability_dry_bulb_c']},
               article=article, ruling='D-56')


def _reset_condenser_setpoint(cw, spec, audit, minimum):
    """Without this the economizer cannot operate at all: the tower is pinned at the
    condenser loop's 29 C design exit temperature by plant_loops.py, so the source
    fluid is never colder than the chilled-water return. Reset it to follow the
    outdoor WET BULB (the quantity an evaporative tower actually tracks) plus the
    tower's own design approach, floored at the chilled-water setpoint — colder than
    that buys no free cooling for a loop held at 7 C — and capped at the original
    design exit temperature so nothing gets warmer than the builder intended."""
    maximum = cw.sizingPlant().designLoopExitTemperature()
    # designApproachTemperature is an OptionalDouble — unwrap, never pass it through.
    approach = None
    for t in cw.supplyComponents(openstudio.model.CoolingTowerSingleSpeed.iddObjectType()):
        value = optional_flow(t.to_CoolingTowerSingleSpeed().get().designApproachTemperature())
        if value is not None:
            approach = value
            break
    if approach is None:
        approach = spec['condenser_reset_fallback_approach_k']
    for manager in list(cw.supplyOutletNode().setpointManagers()):
        manager.remove()
    manager = openstudio.model.SetpointManagerFollowOutdoorAirTemperature(cw.model())
    manager.setName(f'{cw.nameString()} Economizer Reset')
    manager.setReferenceTemperatureType(spec['condenser_reset_reference'])
    manager.setOffsetTemperatureDifference(approach)
    manager.setMinimumSetpointTemperature(minimum)
    manager.setMaximumSetpointTemperature(maximum)
    manager.addToNode(cw.supplyOutletNode())
    reset = {'reference': spec['condenser_reset_reference'], 'approach_k': approach,
             'minimum_c': minimum, 'maximum_c': maximum}
    audit.decision('build', 'condenser loop setpoint reset to follow the outdoor wet-bulb so the tower can make '
                            'the cold water the economizer needs',
                   target=cw.nameString(), inputs=reset,
                   value=f"{spec['condenser_reset_reference']} + {approach} K approach, "
                         f'clamped to {minimum}-{maximum} C',
                   article='5.2.2.9.', ruling='D-56')
    return reset


# ==================== Table 8.4.4.7.-B note (1): humidification (D-55) ====================
#
# "Where present, humidification systems in the reference building shall use the
# same energy source as the corresponding humidification system in the proposed
# building." Humidification was previously COUNTED before the teardown and merely
# warned about — which warned even about humidifiers that go on to survive
# untouched on 'copy_proposed' loops, and let the ones on replaced loops be
# destroyed as a side effect of `air_loop.remove` rather than deliberately.
#
# Now: capture per thermal block before the teardown, rebuild on the serving
# reference loop afterwards, on the same energy source, WITH a control that
# actually operates it. An uncontrolled humidifier is silently inert in
# EnergyPlus, so a rebuild without a working setpoint would be worse than the
# warning it replaces.

def _humidifier_kind(component):
    """HumidifierSteamGas is Humidifier:Steam:Gas, which EnergyPlus burns as natural
    gas (the object carries no fuel-type field); HumidifierSteamElectric is
    resistance steam. Those are the only two humidifier classes the SDK offers on
    an air loop, so the energy source is always determinable for an attributable
    humidifier — the undeterminable case is one we cannot attribute to a block."""
    if hasattr(component, 'to_HumidifierSteamGas') and component.to_HumidifierSteamGas().is_initialized():
        return 'gas'
    if (hasattr(component, 'to_HumidifierSteamElectric')
            and component.to_HumidifierSteamElectric().is_initialized()):
        return 'electric'

    return None


def _air_loop_humidifier(air_loop):
    for component in _coils.supply_components(air_loop):
        if _humidifier_kind(component):
            return component
    return None


def _capture_humidification(reference, audit):
    """Record, per zone, the humidification of the proposed loop serving it, plus the
    material needed to rebuild a working control: the proposed's own scheduled
    minimum-humidity setpoint, if it used one. (A ZoneControlHumidistat lives on the
    THERMAL ZONE, which the teardown does not touch, so it needs no capture.)"""
    captured = {}
    attributed = []
    for air_loop in sorted_by_name(reference.getAirLoopHVACs()):
        component = _air_loop_humidifier(air_loop)
        if component is None:
            continue

        attributed.append(str(component.handle()))
        record = {'kind': _humidifier_kind(component), 'air_loop': air_loop.nameString(),
                  'name': component.nameString(),
                  'scheduled_setpoint': _scheduled_humidity_setpoint(air_loop)}
        for zone in air_loop.thermalZones():
            captured[zone.nameString()] = record
        audit.info('build', 'proposed humidification recorded for the reference rebuild',
                   target=air_loop.nameString(),
                   inputs={'energy_source': _humidifier_energy_source(record['kind']),
                           'zones': len(air_loop.thermalZones()),
                           'scheduled_setpoint': record['scheduled_setpoint'] is not None},
                   value=component.nameString(),
                   article='Table 8.4.4.7.-B Note (1)', ruling='D-55')

    orphans = [h for h in (list(reference.getHumidifierSteamElectrics())
                           + list(reference.getHumidifierSteamGass()))
               if str(h.handle()) not in attributed]
    if orphans:
        names = ', '.join(sorted(h.nameString() for h in orphans))
        audit.warn('build', f'{len(orphans)} proposed humidifier(s) sit on NO air loop serving a thermal block '
                            f'({names}) — the reference humidification they '
                            'correspond to CANNOT be determined and is not rebuilt',
                   article='Table 8.4.4.7.-B Note (1)', ruling='D-55')
    return captured


def _humidifier_energy_source(kind):
    return 'NaturalGas' if kind == 'gas' else 'Electricity'


def _scheduled_humidity_setpoint(air_loop):
    """A scheduled minimum-humidity-ratio setpoint on the proposed loop is the only
    humidity control that does NOT survive the teardown (it lives on a loop node);
    keep the SCHEDULE so the rebuilt control uses the proposed's own setpoint."""
    for spm in air_loop.model().getSetpointManagerScheduleds():
        if (spm.controlVariable() == 'MinimumHumidityRatio'
                and spm.setpointNode().is_initialized()
                and spm.setpointNode().get().airLoopHVAC().is_initialized()
                and spm.setpointNode().get().airLoopHVAC().get().handle() == air_loop.handle()):
            return spm.schedule()
    return None


def _rebuild_humidification(reference, captured, ruleset, vintage, audit):
    """Rebuild humidification on the reference loops, after they exist."""
    if not captured:
        return

    spec = ruleset['humidification']
    table = 'Table 8.4.5.7.-B' if str(vintage) == '2025' else 'Table 8.4.4.7.-B'
    article = f'{table} Note (1)'
    served = []
    for air_loop in sorted_by_name(reference.getAirLoopHVACs()):
        records = [captured[zone.nameString()] for zone in air_loop.thermalZones()
                   if captured.get(zone.nameString()) is not None]
        if not records:
            continue

        for name in [r['air_loop'] for r in records]:
            if name not in served:
                served.append(name)
        if _air_loop_humidifier(air_loop):
            audit.info('build', 'proposed humidification retained on this reference loop — the loop was not replaced',
                       target=air_loop.nameString(), article=article, ruling='D-55')
            continue
        _build_reference_humidifier(air_loop, records, spec, article, audit)

    missed = [n for n in _uniq([r['air_loop'] for r in captured.values()]) if n not in served]
    if not missed:
        return

    audit.warn('build', f"the proposed humidification on {', '.join(sorted(missed))} has NO reference loop to carry "
                        'it — the thermal blocks it served are unconditioned or zonally served in the reference, '
                        'so it is not rebuilt',
               article=article, ruling='D-55')


def _build_reference_humidifier(air_loop, records, spec, article, audit):
    kind = _elect_humidifier_kind(air_loop, records, article, audit)
    source = _humidifier_energy_source(kind)
    humidifier = (openstudio.model.HumidifierSteamGas(air_loop.model()) if kind == 'gas'
                  else openstudio.model.HumidifierSteamElectric(air_loop.model()))
    humidifier.setName(f'{air_loop.nameString()} {source} Steam Humidifier')
    # Never hard-size reference equipment (L-23): capacity follows the sizing run.
    if spec['autosize']:
        humidifier.autosizeRatedCapacity()
    if spec['autosize'] and hasattr(humidifier, 'autosizeRatedPower'):
        humidifier.autosizeRatedPower()
    if not humidifier.addToNode(air_loop.supplyOutletNode()):
        humidifier.remove()
        audit.warn('build', 'the SDK REFUSED the reference humidifier on this supply path — humidification is NOT '
                            'rebuilt on this loop', target=air_loop.nameString(), article=article, ruling='D-55')
        return

    control = _attach_humidity_control(air_loop, humidifier, records, spec)
    if control is None:
        humidifier.remove()
        audit.warn('build', 'the proposed humidification on this thermal block has NO determinable humidity '
                            'control (no zone humidistat survives and the proposed used no scheduled minimum-humidity '
                            'setpoint) — an uncontrolled humidifier is INERT, so none is rebuilt',
                   target=air_loop.nameString(), article=article, ruling='D-55')
        return

    audit.decision('build', 'reference humidification rebuilt on the proposed energy source',
                   target=air_loop.nameString(),
                   inputs={'energy_source': source,
                           'proposed_systems': _uniq([r['air_loop'] for r in records]),
                           'control': control, 'capacity': 'autosized'},
                   value=humidifier.nameString(), article=article, ruling='D-55')


def _elect_humidifier_kind(air_loop, records, article, audit):
    """Note (1) binds the SOURCE; where a reference system merges blocks whose proposed
    humidifiers disagree, the majority source is taken and the divergence is shouted."""
    votes: dict = {}
    for r in records:
        votes[r['kind']] = votes.get(r['kind'], 0) + 1
    elected = max(votes.items(),
                  key=lambda kv: (kv[1], 1 if kv[0] == 'gas' else 0))[0]
    if len(votes) == 1:
        return elected

    sources = ', '.join(sorted(_humidifier_energy_source(k) for k in votes))
    audit.warn('build', 'the proposed thermal blocks merged onto this reference system used DIFFERENT '
                        f'humidification energy sources ({sources}) '
                        f'— note (1) is satisfied for the majority source ({_humidifier_energy_source(elected)}) only',
               target=air_loop.nameString(), article=article, ruling='D-55')
    return elected


def _attach_humidity_control(air_loop, humidifier, records, spec):
    """The control has to come from the PROPOSED (8.4.3.2 identity), not be invented:
    either a zone humidistat that survived the teardown on the zone, or the
    proposed loop's own scheduled minimum-humidity setpoint."""
    node = humidifier.outletModelObject().get().to_Node().get()
    zone = next((z for z in sorted_by_name(air_loop.thermalZones())
                 if z.zoneControlHumidistat().is_initialized()), None)
    if zone is not None:
        manager = openstudio.model.SetpointManagerSingleZoneHumidityMinimum(air_loop.model())
        manager.setName(f'{air_loop.nameString()} Min Humidity Setpoint Manager')
        manager.setControlZone(zone)
        manager.addToNode(node)
        return f"{spec['control']} on {zone.nameString()}'s humidistat"

    schedule = next((r['scheduled_setpoint'] for r in records
                     if r['scheduled_setpoint'] is not None), None)
    if schedule is None:
        return None

    manager = openstudio.model.SetpointManagerScheduled(air_loop.model(), schedule)
    manager.setName(f'{air_loop.nameString()} Min Humidity Setpoint Manager')
    manager.setControlVariable('MinimumHumidityRatio')
    manager.addToNode(node)
    return f"{spec['fallback_control']} on the proposed's schedule '{schedule.nameString()}'"


# ==================== 8.4.4.15: demand-controlled ventilation follows the proposed ====
#
# 8.4.4.15.(2) (2025: 8.4.5.15.(2)), D-54 — "where demand control ventilation
# strategies required by Article 5.2.3.4. are implemented in the proposed
# building, the reference building shall be modeled with those same
# strategies". The reference OA controller is rebuilt from scratch
# (build_oa_system) with the package's ZoneSum convention and DCV off, so the
# proposed's strategy has to be copied back onto it.
#
# The strategy is the DCV FLAG plus, where it is itself a demand-control
# method, the system outdoor-air method: CO2-based DCV rides
# IndoorAirQualityProcedure and occupancy-proportional DCV rides the
# ProportionalControl* methods, so copying only the flag would silently
# substitute occupancy-based control for the proposed's strategy. The
# PEAK-rate methods (ZoneSum, Standard 62.1 Ventilation Rate Procedure) are
# NOT copied: those determine the peak ventilation rate, which is sentence
# (1)'s subject, and the reference realizes (1) through the cloned
# DesignSpecification:OutdoorAir under ZoneSum.
DCV_METHODS = ('IndoorAirQualityProcedure', 'IndoorAirQualityProcedureGenericContaminant',
               'IndoorAirQualityProcedureCombined', 'ProportionalControlBasedOnOccupancySchedule',
               'ProportionalControlBasedOnDesignOccupancy', 'ProportionalControlBasedOnDesignOARate')


def _apply_dcv(air_loops, zones, proposed_dcv, vintage, audit):
    prefix = '8.4.5' if str(vintage) == '2025' else '8.4.4'
    article = f'{prefix}.15.(2)'
    sources = [proposed_dcv[z.nameString()] for z in zones
               if proposed_dcv.get(z.nameString()) is not None]
    enabled = [s for s in sources if s['dcv']]

    for air_loop in _array(air_loops):
        oa_system = air_loop.airLoopHVACOutdoorAirSystem()
        if oa_system.empty():
            continue

        mech = oa_system.get().getControllerOutdoorAir().controllerMechanicalVentilation()
        if not enabled:
            audit.info('rules', 'no demand-controlled ventilation on the proposed systems serving these thermal '
                                'blocks — none modeled in the reference',
                       target=air_loop.nameString(),
                       inputs={'proposed_loops': _uniq([s['air_loop'] for s in sources])},
                       article=article, ruling='D-54')
            continue

        mech.setDemandControlledVentilation(True)
        methods = _uniq([s['method'] for s in enabled if s['method'] is not None])
        copied = [m for m in methods if m in DCV_METHODS]
        if len(copied) == 1:
            mech.setSystemOutdoorAirMethod(copied[0])
        audit.decision('rules', 'proposed demand-controlled ventilation strategy copied to the reference system',
                       target=air_loop.nameString(),
                       inputs={'proposed_loops': _uniq([s['air_loop'] for s in enabled]),
                               'proposed_system_outdoor_air_method': methods,
                               'blocks_with_dcv': f'{len(enabled)} of {len(sources)}'},
                       value='demand-controlled ventilation on, system outdoor air method '
                             f'{mech.systemOutdoorAirMethod()}',
                       article=article, ruling='D-54')
        _audit_dcv_caveats(air_loop, mech, sources, enabled, copied, article, audit)


def _audit_dcv_caveats(air_loop, mech, sources, enabled, copied, article, audit):
    """Everything about the copy that a reader must not have to infer: a partly-DCV
    merged system, an ambiguous set of demand-control methods, and a CO2-based
    strategy whose contaminant balance did not survive into the reference."""
    if len(enabled) < len(sources):
        audit.warn('rules', f'only {len(enabled)} of {len(sources)} proposed thermal blocks served by this '
                            'reference system carry demand-controlled ventilation — the reference system is a '
                            'single controller, so the strategy is applied to ALL of its blocks',
                   target=air_loop.nameString(), article=article, ruling='D-54')
    if len(copied) > 1:
        audit.warn('rules', f"the proposed thermal blocks use DIFFERENT demand-control methods ({', '.join(copied)}) "
                            f'— the reference keeps {mech.systemOutdoorAirMethod()} and the other strategies are '
                            'NOT reproduced',
                   target=air_loop.nameString(), article=article, ruling='D-54')
    if not mech.systemOutdoorAirMethod().startswith('IndoorAirQualityProcedure'):
        return

    # getZoneAirContaminantBalance CREATES the unique object when absent — probe
    # the optional accessor so a diagnostic never mutates the reference model.
    balance = mech.model().getOptionalZoneAirContaminantBalance()
    if balance.is_initialized() and balance.get().carbonDioxideConcentration():
        return

    audit.warn('rules', 'CO2-based demand-controlled ventilation copied, but the reference model has NO carbon '
                        'dioxide concentration balance — the strategy will NOT operate in EnergyPlus',
               target=air_loop.nameString(), article=article, ruling='D-54')


# ==================== 8.4.4.18: reference fan specifications ====================
# 8.4.4.18.(3): systems 1/3/4/5 -> supply fan 640 Pa @ 40% combined efficiency, no
# return fan. 8.4.4.18.(4): system 6 -> supply 1000 Pa @ 55%, return 250 Pa @ 30%.

def _apply_fan_rules(air_loops, reference_system, ruleset, audit):
    fans = ruleset['fans']
    spec = fans['system_6'] if reference_system == 6 else fans['systems_1_3_4_5']
    for air_loop in _array(air_loops):
        for comp in _coils.supply_components(air_loop):
            fan = comp.to_FanConstantVolume().get() if comp.to_FanConstantVolume().is_initialized() else None
            if fan is None:
                fan = (comp.to_FanVariableVolume().get()
                       if comp.to_FanVariableVolume().is_initialized() else None)
            if fan is None:
                continue

            is_return = re.search(r'return', fan.nameString(), re.IGNORECASE) is not None
            pa = spec.get('return_pa') if is_return else spec.get('supply_pa')
            eff = spec.get('return_efficiency') if is_return else spec.get('supply_efficiency')
            if pa is None:
                continue  # sys 1/3/4/5 has no return-fan spec

            fan.setPressureRise(pa)
            _set_fan_total_efficiency(fan, eff)
            audit.decision('rules', f"{'return' if is_return else 'supply'} fan set to reference spec",
                           target=fan.nameString(),
                           value=f'{pa} Pa @ {ruby_round(eff * 100)}% combined fan-motor efficiency',
                           article=fans['article'])


def _set_fan_total_efficiency(fan, efficiency):
    if hasattr(fan, 'setFanTotalEfficiency'):
        fan.setFanTotalEfficiency(efficiency)
    else:
        fan.setFanEfficiency(efficiency)


def _apply_heat_pump_limits(air_loops, ruleset, audit):
    """8.4.4.13.(2)(d): the reference heat pump shall not operate in heating mode
    below -10 degC."""
    cutoff = ruleset['heat_pump_reference']['heating_cutoff_oat_c']
    for air_loop in _array(air_loops):
        for comp in _coils.supply_components(air_loop):
            staged = comp.to_CoilHeatingDXMultiSpeed()
            if not (comp.to_CoilHeatingDXSingleSpeed().is_initialized() or staged.is_initialized()):
                continue

            coil = staged.get() if staged.is_initialized() else comp.to_CoilHeatingDXSingleSpeed().get()
            coil.setMinimumOutdoorDryBulbTemperatureforCompressorOperation(cutoff)
            audit.decision('rules', 'heat pump heating cutoff set', target=coil.nameString(),
                           value=f'compressor off below {cutoff} degC',
                           article=ruleset['heat_pump_reference']['article'])


def optional_flow(value):
    """Unwrap an SDK optional numeric (flow, capacity, ...) to a value or None.

    :param value: OptionalDouble, numeric or None
    :return: the contained value, or None when uninitialized"""
    if not hasattr(value, 'is_initialized'):
        return value

    return value.get() if value.is_initialized() else None


# ==================== 8.4.4.8: oversizing caps + D-52 (2)(b) ====================
# The builders' GENERIC per-zone sizing factors. These sentinels MUST match
# the zone_heating/zone_cooling_sizing_factor values the sizing blocks in
# data/sizing.json stamp on generic systems (1.3/1.1) and on the HP builds
# (cooling 1.0, required "without oversizing" by 8.4.4.13.(2)(b)) — if
# sizing.json changes, change these WITH it, or the 8.4.4.8 cap below
# silently stops clearing the zone stamps (zone factors override the
# global Sizing:Parameters).
GENERIC_ZONE_HEATING_FACTOR = 1.3
GENERIC_ZONE_COOLING_FACTOR = 1.1
HP_ZONE_COOLING_FACTOR = 1.0


def _apply_oversizing_caps(proposed, reference, ruleset, audit):
    """8.4.4.8: reference oversizing = the lesser of the proposed oversizing and the
    cap (30% heating / 10% cooling), applied via the model-wide sizing factors."""
    caps = ruleset['oversizing']
    sizing = proposed.getSizingParameters()
    heat_prop = sizing.heatingSizingFactor()
    cool_prop = sizing.coolingSizingFactor()
    heat_ref = min(heat_prop, 1.0 + caps['heating_max_fraction'])
    cool_ref = min(cool_prop, 1.0 + caps['cooling_max_fraction'])
    ref_sizing = reference.getSizingParameters()
    ref_sizing.setHeatingSizingFactor(heat_ref)
    ref_sizing.setCoolingSizingFactor(cool_ref)
    # T1 (audit 2026-07-25): zone-level sizing factors OVERRIDE the global
    # Sizing:Parameters in EnergyPlus, so the builders' generic 1.3/1.1 zone
    # stamps silently defeated this cap. Reset the GENERIC zone factors so
    # the capped globals govern; PRESERVE any non-generic factor (the HP
    # zone cooling factor 1.0 required by 8.4.4.13.(2)(b) "without
    # oversizing").
    cleared = 0
    hp_pinned = 0
    for sz in reference.getSizingZones():
        # Ruby guards this block with `rescue StandardError; next` because .get on an
        # empty OptionalDouble raises. The Python wheel raises a SystemError there AND
        # leaves the C-level error indicator set, which then poisons the next unrelated
        # C call — so the empty case is tested, not rescued. Same outcome, same `next`:
        # nothing stamped, nothing to clear.
        heating = opt(sz.zoneHeatingSizingFactor())
        cooling = opt(sz.zoneCoolingSizingFactor())
        if heating is None or cooling is None:
            continue

        if abs(heating - GENERIC_ZONE_HEATING_FACTOR) < 1e-9:
            sz.resetZoneHeatingSizingFactor()
            cleared += 1
        if abs(cooling - GENERIC_ZONE_COOLING_FACTOR) < 1e-9:
            sz.resetZoneCoolingSizingFactor()
            cleared += 1
        elif abs(cooling - HP_ZONE_COOLING_FACTOR) < 1e-9:
            hp_pinned += 1  # the HP builders' deliberate 1.0 — preserved
    audit.decision('rules', 'equipment oversizing capped',
                   inputs={'proposed_heating': heat_prop, 'proposed_cooling': cool_prop,
                           'generic_zone_factors_cleared': cleared},
                   value=f'heating sizing factor {ruby_round(heat_ref, 3)} = min(proposed '
                         f"{ruby_round(heat_prop, 3)}, cap {ruby_round(1.0 + caps['heating_max_fraction'], 2)}); "
                         f'cooling {ruby_round(cool_ref, 3)} = min(proposed {ruby_round(cool_prop, 3)}, cap '
                         f"{ruby_round(1.0 + caps['cooling_max_fraction'], 2)})",
                   article=caps['article'], ruling='D-22')
    if hp_pinned == 0:
        return

    # 8.4.4.13.(2)(b): "the heat pump's cooling capacity shall be set based on
    # the peak cooling load, without oversizing". The HP builders stamp a
    # Sizing:Zone cooling factor of 1.0, which OVERRIDES (does not multiply
    # with) the capped global above — measured on the sized DX coil: identical
    # capacity with the global at 1.10 vs 1.00 (A/B ratio 1.0000), while
    # clearing the zone factor grew it 4.15%, proving the probe's sensitivity.
    audit.decision('rules', 'heat pump cooling sized at the peak cooling load, without oversizing',
                   inputs={'zones_pinned': hp_pinned, 'global_cooling_factor': cool_ref},
                   value='per-zone cooling sizing factor 1.0 overrides the global factor (measured: sized DX '
                         'capacity identical with the global at 1.10 vs 1.00)',
                   article=f"{heat_pump_article_base(ruleset.get('selection') or {})}.(2)(b)", ruling='D-52')


_ARTICLE_NUMBER_RE = re.compile(r'\d+\.\d+\.\d+\.\d+')


def heat_pump_article_base(selection):
    """The heat-pump article is 8.4.4.13 in 2020 and 8.4.5.13 in 2025. BOTH
    rulesets already carry the correct spelling in
    selection.special_rules.heat_pump.article, so derive it rather than
    hardcoding — a 2025 run was citing the 2020 article number to the AHJ.

    Same trade-off as _audit_terminal_secondary_split: the coverage generator
    only scans for a QUOTED literal after `article:`, so a computed article is
    not picked up as a "Cited at" link. The article is declared in the
    article_coverage manifests either way, and citing the wrong number is worse
    than citing fewer times."""
    raw = ((selection.get('special_rules') or {}).get('heat_pump') or {}).get('article')
    match = _ARTICLE_NUMBER_RE.search('' if raw is None else str(raw))
    return match.group(0) if match else '8.4.4.13'


# ==================== 8.4.4.13.(2)(g): the HP auxiliary-fuel election (D-52) ==========
# 8.4.4.13.(2)(g)/(h) — the reference heat pump's terminal/auxiliary heating
# energy type (D-52). The election is ANNUAL-ENERGY-based: among the energy
# types used for terminal or auxiliary heating of the thermal blocks the
# heat pump serves, elect the one with the largest annual energy use —
# PROVIDED the heat pump exceeds the vendored threshold (33%) of the total
# annual space-heating energy use for those blocks. (g)(i) scopes an
# air-source HP to its own blocks; (g)(ii) scopes a water-/ground-source HP
# to the blocks of ALL heat pumps connected to the same water loop. All
# quantities are DELIVERED heat (one consistent basis across fuels).
#
# Returns None — falling back to the structural 8.4.4.9.(4) proxy, audited —
# when there is no annual data (simulate: 'sizing'/'none'), when the blocks
# have no terminal/aux heating at all, or when the 33% proviso fails (the
# sentence then simply does not elect).
#
# (h) forces electricity when the HP is not air-, water- or ground-source.
# Our taxonomy classifies every detected HP as 'air', 'water_loop' or
# 'external' (water/ground), so (h) is only ever AFFIRMATIVELY established
# for a source-less detection — which keeps the proxy instead, with the
# inapplicability recorded, rather than guessing.

def heat_pump_aux_energy_type(group, facts, hp_rules, annual, audit, article_base='8.4.4.13'):
    """:param group: one classify.characterize group (the heat-pump system)
    :param facts: the full classify.characterize output
    :param hp_rules: the ruleset's heat-pump rules block (threshold source), or None
    :param annual: proposed-annual delivered-heat data or None
        ({'loops': {name: {'hp_j':, 'aux': [{'fuel':, 'j':}]}},
          'zones': {name: [{'role':, 'fuel':, 'j':}]}})
    :param audit: AuditLog or None
    :return: str or None — elected reference energy-type variant ('gas', 'electric'),
        or None when sentence (g) does not elect (proxy applies)"""
    audit = audit if audit is not None else NullAudit()
    threshold = (hp_rules or {}).get('aux_energy_type_threshold_fraction') or 0.33
    if annual is None:
        audit.info('selection',
                   'no proposed annual data (simulate: :sizing/:none, or the annual run predates this '
                   'feature) — the 8.4.4.13.(2)(g) auxiliary-fuel election cannot run; the structural '
                   '8.4.4.9.(4) proxy elects the fuel instead',
                   target=','.join(group['zones']), article=f'{article_base}.(2)(g)', ruling='D-52')
        return None

    scope_loops, scope_zones, sentence = _election_scope(group, facts)
    hp_j = 0.0
    aux_by_fuel: dict = {}
    for loop_name in scope_loops:
        entry = (annual.get('loops') or {}).get(loop_name) or {}
        hp_j += float(entry.get('hp_j') or 0.0)
        for a in _array(entry.get('aux')):
            aux_by_fuel[a['fuel']] = aux_by_fuel.get(a['fuel'], 0.0) + float(a.get('j') or 0.0)
    for zone_name in scope_zones:
        for e in _array((annual.get('zones') or {}).get(zone_name)):
            if e['role'] == 'hp':
                hp_j += float(e.get('j') or 0.0)
            else:
                aux_by_fuel[e['fuel']] = aux_by_fuel.get(e['fuel'], 0.0) + float(e.get('j') or 0.0)

    total_j = hp_j + sum(aux_by_fuel.values())
    if not aux_by_fuel or total_j <= 0.0:
        audit.info('selection',
                   'the proposed thermal blocks have no terminal or auxiliary heating energy in the annual '
                   'run — 8.4.4.13.(2)(g) has nothing to elect; the structural 8.4.4.9.(4) proxy elects the fuel',
                   target=','.join(group['zones']),
                   inputs={'hp_gj': ruby_round(hp_j / 1e9, 2)},
                   article=f'{article_base}.(2)(g)', ruling='D-52')
        return None

    share = hp_j / total_j
    if share <= threshold:
        audit.decision('selection',
                       f"the heat pump carries {ruby_round(share * 100, 1)}% of the blocks' annual space-heating "
                       f'energy — NOT above the {ruby_round(threshold * 100)}% proviso, so sentence (g) does not '
                       'elect; the structural 8.4.4.9.(4) proxy elects the fuel',
                       target=','.join(group['zones']),
                       inputs={'hp_gj': ruby_round(hp_j / 1e9, 2), 'total_gj': ruby_round(total_j / 1e9, 2),
                               'share': ruby_round(share, 3), 'threshold': threshold, 'sentence': sentence},
                       article=f'{article_base}.(2){sentence}', ruling='D-52')
        return None

    elected_fuel, elected_j = max(aux_by_fuel.items(), key=lambda kv: kv[1])
    variant = _energy_type_variant(elected_fuel)
    if variant is None:
        audit.warn('selection',
                   f"the largest terminal/aux energy type is '{elected_fuel}', which maps to NO reference "
                   'system variant — the structural 8.4.4.9.(4) proxy elects the fuel instead',
                   target=','.join(group['zones']),
                   inputs={'by_fuel_gj': {f: ruby_round(j / 1e9, 2) for f, j in aux_by_fuel.items()}},
                   article=f'{article_base}.(2){sentence}', ruling='D-52')
        return None
    audit.decision('selection',
                   'auxiliary heating energy type ELECTED from the proposed annual run: the terminal/aux '
                   f'energy type with the largest annual energy use is {elected_fuel} '
                   f"({ruby_round(elected_j / 1e9, 2)} GJ delivered), and the heat pump's "
                   f'{ruby_round(share * 100, 1)}% share exceeds the {ruby_round(threshold * 100)}% proviso '
                   '((h) inapplicable: the source is classified air/water/ground)',
                   target=','.join(group['zones']),
                   inputs={'by_fuel_gj': {f: ruby_round(j / 1e9, 2) for f, j in aux_by_fuel.items()},
                           'hp_gj': ruby_round(hp_j / 1e9, 2), 'share': ruby_round(share, 3),
                           'sentence': sentence, 'scope_loops': scope_loops,
                           'scope_zone_count': len(scope_zones)},
                   value=variant, article=f'{article_base}.(2){sentence}', ruling='D-52')
    return variant


def _election_scope(group, facts):
    """(g)(i) vs (g)(ii): an 'external'-source (water/ground) heat pump elects over
    the thermal blocks of ALL heat pumps connected to the same source water loop, so
    sibling zone groups sharing a source loop are pulled in."""
    loops = [group['air_loop']] if group.get('air_loop') is not None else []
    zones = list(group['zones'])
    if ('external' in (group.get('heat_pump_sources') or [])
            and group.get('heat_pump_source_loops')):
        for other in (facts.get('zone_groups') or []):
            if other is group:
                continue
            shared = [x for x in _array(other.get('heat_pump_source_loops'))
                      if x in group['heat_pump_source_loops']]
            if not shared:
                continue

            for name in ([other['air_loop']] if other.get('air_loop') is not None else []):
                if name not in loops:
                    loops.append(name)
            for z in other['zones']:
                if z not in zones:
                    zones.append(z)
        return loops, zones, '(g)(ii)'
    return loops, zones, '(g)(i)'


def _energy_type_variant(fuel):
    """Map an elected proposed energy type onto the reference system-definition
    variant. Purchased heating is represented by a gas-fired boiler (8.4.4.6.(1));
    an unknown type cannot elect (None -> structural proxy)."""
    if re.search(r'gas|oil|propane|purchased', str(fuel), re.IGNORECASE):
        return 'gas'
    if re.search(r'electric', str(fuel), re.IGNORECASE):
        return 'electric'

    return None


def _reference_energy_type(group, selection, facts, audit):
    """8.4.4.9.(4)/8.4.4.10.(3): reference energy type follows the proposed system;
    8.4.4.6.(1): purchased heating is represented by a gas-fired boiler."""
    fuels = group['heating_energy_types']
    if 'Purchased' in fuels or (facts.get('purchased_energy') or {}).get('heating'):
        audit.decision('selection', 'purchased heating energy -> represented by gas-fired modulating boiler',
                       target=','.join(group['zones']),
                       article=selection['special_rules']['purchased_heating']['article'])
        return 'gas'
    if any(re.search(r'gas|oil|propane', str(f), re.IGNORECASE) for f in fuels):
        return 'gas'
    if 'Electricity' in fuels:
        return 'electric'

    audit.warn('selection', 'no proposed heating energy type detected — electric reference assumed',
               target=','.join(group['zones']), article='8.4.4.9.(4)')
    return 'electric'
