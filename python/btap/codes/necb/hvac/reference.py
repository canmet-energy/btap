"""NECB performance-path helpers: reference HVAC selection (Table 8.4.4.7.-A/-B) and
the proposed->reference transform (port of btap-necb's hvac/reference.rb).

All rule content lives in each edition's own reference_rules.json (vendored, with
article-level provenance); this code is a rules interpreter, not a rules store.

Port notes (D-79): Ruby's symbol keys collapse to str throughout — the
characterization facts dict, the building info dict and the assignment actions
('build' / 'copy_proposed' / 'through_the_wall') are all str-keyed/str-valued.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import openstudio

from btap._compat import NullAudit, opt, ruby_round, sorted_by_name
from btap.audit import emit_coverage
from btap.codes import resolve
from btap.codes.necb import code_id, rulesdata
from btap.costing.hvac import geometry as _costing_geometry
from btap.modeling.hvac import classify as _classify
from btap.modeling.hvac.components import coils as _coils
from btap.modeling.hvac.components import schedules as _schedules
from btap.modeling.hvac.systems.plant_loops import BOILER_PART_LOAD_CLASS_FEATURE


def rules(edition):
    """This edition's HVAC reference ruleset — a shim over the family's ONE
    loader (:func:`btap.codes.necb.rulesdata.load`), which owns the cache.

    :param edition: the NECB edition ('2020' or '2025')
    :return: dict — the edition's manifest-declared ``hvac`` rule file
    """
    return rulesdata.load("hvac", code_id(edition))


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


def select_reference_systems(*, facts, building, code='necb2020', audit=None,
                             proposed_annual=None):
    """Select the NECB reference HVAC system for every zone group of a characterized
    model. Pure logic: no model access — everything comes from the facts dict (see
    btap.modeling.characterize) and the building info.

    :param facts: dict — btap.modeling.characterize output
    :param building: dict — 'storeys' (above-ground count), 'zone_types'
        ({zone name => space-type description string}), optional 'kitchen_hood_zones',
        'refrigerated_zones' (lists of zone names for conditions the model cannot express)
    :param code: the code id, e.g. 'necb2020'
    :param audit: AuditLog or None
    :return: list[Assignment]
    """
    return _select_reference_systems(facts=facts, building=building,
                                     ruleset=resolve(code),
                                     audit=audit, proposed_annual=proposed_annual)


def _select_reference_systems(*, facts, building, ruleset, audit=None,
                              proposed_annual=None):
    """The Table 8.4.4.7.-A selection against ONE resolved edition (Stage 6)."""
    audit = audit if audit is not None else NullAudit()
    rules_data = ruleset.rules("hvac")
    selection = rules_data['selection']
    definitions = rules_data['system_definitions']
    hp_rules = rules_data['heat_pump_reference']

    assignments = []
    # The multi-energy disclosure dedupes per serving system. The set is
    # scoped to THIS call rather than written into `facts`, which is the
    # caller's dict and documented as pure input — two calls on one dict used
    # to yield one disclosure (Fable, `117`).
    disclosed: set = set()
    #: Article 13.(2)(g) elections already made in THIS selector call,
    #: keyed by `_election_scope`. Call-scoped for the same reason
    #: `disclosed` is: `facts` is the caller's dict and documented as
    #: pure input, so two calls on one dict must not share state.
    elected: dict = {}
    for group in facts['zone_groups']:
        if not (group['heated'] or group['cooled']):
            continue  # unconditioned: no reference system

        # ONE ASSIGNMENT PER THERMAL BLOCK, not per serving system.
        #
        # This iterated the GROUP — zones sharing one PROPOSED air loop — and
        # treated it as the unit Sentence 8.4.x.7.(1) assigns a system to. It
        # is not: it is a serving set. The consequence was a reference
        # "single-zone" System 3 built as ONE air loop over five thermal
        # blocks, its supply temperature following one elected control zone
        # while the other four drifted — 932 unmet heating hours in sample
        # 18's reference, which fails 8.4.1.2.(3) and made the run report NOT
        # COMPLIANT for the reference's failure rather than the proposed
        # building's performance.
        #
        # Sol's `139` ruled it, against the Code and the NRC User's Guide
        # rather than the legacy gem: Division A defines a single-zone
        # secondary system as one serving only ONE thermal block; 8.4.x.1.(4)(c)
        # keeps the proposed building's thermal blocks in the reference; and the
        # Guide's Figures 8-3, 8-4 and 8-7 each say "each thermal block is
        # considered separate from all other thermal blocks". Its Example 8-4
        # is decisive: to serve two proposed zones with one System 4 unit the
        # modeller must MERGE the zones, not attach two retained zones to one
        # "single-zone" unit.
        #
        # The architecture already separated these concerns and only this
        # iteration conflated them — the merge step below re-groups the
        # MULTIZONE families (2/5/6) by catalogue identity and deliberately
        # leaves "single-zone families (1/3/4/hp) ... their selection
        # grouping". So selecting per block gives 3/4/1/hp one unit each while
        # 2/5/6 recombine exactly as before, Note (3)'s facade split included.
        #
        # The serving GROUP stays the source of truth for service-set facts —
        # fuels, plant correspondence, DCV, dispatch, Article 9/10 allocation —
        # which is Sol's first disposition item: keep `zone_groups`, stop using
        # it as the block partition.
        # The Article 13 election's scope, computed from the ORIGINAL group
        # BEFORE it is split: `_election_scope` reads `group['zones']`, and a
        # block view has one. (g)(ii) also reaches sibling groups sharing a
        # source water loop, which only the unsplit group can see.
        scope_loops, scope_zones, scope_sentence = _election_scope(group, facts)
        election_key = (tuple(sorted(scope_loops)), tuple(sorted(scope_zones)),
                        scope_sentence)
        for block in _blocks_of(group, election_key):
            category = _category_for(block, building, selection, audit)
            assignment = _assign(block, category, building, selection, audit)
            result = _finalize(assignment, block, definitions, selection, facts,
                               audit, hp_rules=hp_rules,
                               proposed_annual=proposed_annual,
                               ruleset=ruleset, disclosed=disclosed,
                               elected=elected)
            if result is not None:
                assignments.append(result)
    return assignments


def _blocks_of(group, election_key=None):
    """One view per retained thermal block in ``group``.

    Each view narrows ``zones`` to a single block and inherits every other
    key, so the block carries its serving system's facts without the group
    pretending to be one block.

    ``design_cooling_kw`` is inherited UNCHANGED, deliberately. It is a
    group-level quantity and the one rule that reads it — Table 8.4.x.7.-A's
    "Where the proposed building or space has a cooling capacity exceeding
    20 kW" for a Data Processing Area — turns on whether "building or space"
    means the serving system or the block. That is a separate Code reading,
    not something to decide by inheritance: this change alters WHICH blocks get
    their own unit, not WHAT a capacity threshold measures. Splitting it would
    silently move a Code threshold's basis.
    """
    serving = tuple(group['zones'])
    # `_origin_group` is the UNSPLIT group, carried because some questions are
    # not the block's to answer. The Article 13 election is one: it weighs the
    # proposed heat pump's auxiliary energy over every block that heat pump
    # serves, so handing it a one-block view makes it elect from one block's
    # auxiliary fuel and call that the answer for all of them.
    extra = {'_serving_zones': serving, '_election_key': election_key,
             '_origin_group': group}
    if len(serving) == 1:
        return [dict(group, **extra)]
    return [dict(group, zones=[zone], **extra) for zone in serving]




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

def _subsection(ruleset):
    """This edition's reference subsection prefix — `8.4.4` or `8.4.5`.

    Read from the edition's manifest, never written as a literal: the same
    article NUMBER names a different requirement in each edition, so a
    hardcoded citation is wrong for every edition but the one it was written
    against. `None` falls back to 2020's, which is what the hardcoded value
    already was — but the fallback is now visible instead of implicit.
    """
    if ruleset is None:
        return '8.4.4'
    return ruleset.article('reference_subsection')


def _audit_corner_block_grouping(result, assignment, prefix, audit):
    """AHJ-10: which facade a CORNER block was assigned to, and that we chose it.

    The register used to claim this choice was audited. It was not — Sol's `127`
    traced the deciding code to `VAVReheat._dominant_orientation`, which has no
    audit object, and the later `multizone selection groups merged` entry
    records neither the corner block's identity nor the elected facade. So a
    reviewer could not see which facade a corner block was given.

    The fix is the metadata handoff Sol specified, not a second copy of the
    rule: the generic builder records WHAT it measured and elected, and this
    function — in `btap.codes`, where NECB ids belong — decides whether that
    raises a question and writes it down.

    Table -B Note (3) says only that blocks are "grouped together based on
    facade orientation". It supplies neither the metric nor the tie-break, so a
    block with exposure on MORE THAN ONE orientation is assigned by a rule we
    chose. A single-facade block is unambiguous and raises nothing.
    """
    evidence = getattr(result, 'grouping_evidence', None)
    if not evidence or assignment.reference_system != 6:
        return
    corners = [record for record in evidence
               if len(record.get('facade_areas_m2') or {}) > 1]
    if not corners:
        return
    audit.decision(
        'selection',
        'corner thermal blocks assigned to ONE facade group by largest '
        'exterior wall area, with an N/E/S/W tie-break — Note (3) says only '
        'that blocks are grouped by facade orientation and supplies neither '
        'the metric nor the tie-break, so this assignment is ours',
        target=','.join(record['zone'] for record in corners),
        inputs={'corner_blocks': {record['zone']: {
                    'facade_areas_m2': record['facade_areas_m2'],
                    'elected': record['elected']} for record in corners},
                'tie_break': corners[0].get('tie_break')},
        article=f'Table {prefix}.7.-B Note (3)', ruling='D-18',
        ahj='AHJ-10')


def _finalize(assignment, group, definitions, selection, facts, audit,
              hp_rules=None, proposed_annual=None, ruleset=None,
              disclosed=None, elected=None):
    if assignment.action == 'copy_proposed':
        return assignment

    hp_rule = selection['special_rules']['heat_pump']
    hp_article = heat_pump_article_base(selection)
    if _heat_pump_redirects(group) and assignment.reference_system in hp_rule['applies_to_systems']:
        audit.decision('selection',
                       'proposed heat pump -> reference is an air-source heat pump '
                       f'(Table {hp_article})',
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
    boiler_part_load_curve_class = None
    if assignment.reference_system == 'hp':
        # ONE ELECTION PER HEAT PUMP OR SOURCE-LOOP SET, reused on every block
        # it serves. (2)(g) states its own comparison scope and it is not the
        # thermal block: see `_election_scope`. Without this, five blocks served
        # by one ASHP ran five identical annual comparisons and audited five
        # times, which is not five questions — it is one question, obscured
        # (Sol, `141`; D-52's existing contract).
        scope = group.get('_election_key')
        if elected is not None and scope is not None and scope in elected:
            assignment.energy_type = elected[scope]
        else:
            # The ORIGINAL proposed group, not this block's view. Keying the
            # cache on the full scope stopped a second call; it did not make
            # the FIRST call full-scope. Measured on one ASHP over two blocks
            # with 10 GJ of auxiliary gas on the first and 100 GJ of
            # auxiliary electricity on the second: the one-block view elects
            # `gas` from `{'NaturalGas': 10.0}` with `scope_zone_count: 1`,
            # where (g)(i)'s proposed-heat-pump scope elects `electric` from
            # `{'NaturalGas': 10.0, 'Electricity': 100.0}` (Sol, `143`).
            assignment.energy_type = heat_pump_aux_energy_type(
                group.get('_origin_group') or group, facts, hp_rules,
                proposed_annual, audit, article_base=hp_article)
            if elected is not None and scope is not None:
                elected[scope] = assignment.energy_type
    if assignment.energy_type is None:
        assignment.energy_type, boiler_part_load_curve_class = \
            _reference_energy_type(group, selection, facts, audit)
    # The 8.4.x.9.(5) disclosure runs on EVERY election path, not only the
    # structural one. It used to live inside _reference_energy_type, which
    # `_finalize` skips whenever heat_pump_aux_energy_type elects a type —
    # so an ANNUAL run of a mixed ASHP group produced the 8.4.4.13.(2)(g)
    # election and NO multi-energy disclosure at all (Sol, `114`).
    #
    # The scope question is now RULED (`119`, on fetched normative text):
    # 8.4.x.13 does NOT supersede 8.4.x.9.(5). They operate concurrently,
    # with Article 13 controlling heat-pump topology and the terminal or
    # auxiliary energy-type election under its own (2)(g), while (5)'s
    # capacity-allocation and operating-characteristic obligations survive
    # for the serving system. Clause 13.(2)(f) expressly incorporates
    # Subsections 8.4.1, 8.4.2 and 8.4.4/8.4.5. So the disclosure belongs on
    # this path as a matter of ruling, not of caution — and it must not say
    # the auxiliary election eliminates electric reference heating.
    _disclose_multi_energy(group, selection, facts, audit,
                           ruleset=ruleset, disclosed=disclosed)
    definition = definitions[str(assignment.reference_system)]
    variant = definition[assignment.energy_type]
    assignment.catalog_name = variant['name']
    assignment.config = variant.get('config')

    # D-89: the ONE part-load curve class the Code itself selects. 8.4.4.6.(1)
    # (2025: 8.4.5.6.(1)) names a "gas-fired MODULATING boiler" for purchased
    # heating, so the class travels with the selection rather than being
    # inferred from the equipment row. It rides the assignment's config exactly
    # as `purchased_cooling_reference_cop` does (below), and the build site
    # stamps it onto the boilers `replace_system` creates. Nothing else
    # propagates a class: a proposed condensing boiler does NOT make the
    # reference condensing (8.4.4.9.(4) transfers the ENERGY TYPE, not the
    # equipment kind).
    if boiler_part_load_curve_class is not None:
        merged = dict(assignment.config or {})
        merged['boiler_part_load_curve_class'] = boiler_part_load_curve_class
        assignment.config = merged

    # D-39 (A4 ruled conditional, phylroy 2026-07-28): Table 8.4.4.7.-B lists
    # System 5's heating as "None", but 8.4.4.1.(5) requires the presence or
    # absence of heating per thermal block to be IDENTICAL to the proposed.
    # Reconciliation: the table's "None" governs the default composition
    # (cooling-only TPFC when the proposed block is unheated); sentence (5)
    # overrides presence when the proposed block IS heated.
    #
    # "THE EXISTING TWO-PIPE CHANGEOVER HEATING IS KEPT — NO SYSTEM INVENTED"
    # was the old wording here and it was false (Sol, `129`.4). There is no
    # existing changeover heating to keep: this path BUILDS a hot-water loop, a
    # boiler and heating coils — and an MAU heating coil — inside a FOUR-PIPE
    # fan-coil surrogate. The Code does not select that topology, which is the
    # substance of the AHJ-11 referral, and the surrogate's missing plant-side
    # changeover is AHJ-18.
    if assignment.reference_system == 5:
        # PER EDITION. These were hardcoded to 2020's numbering, so a necb2025
        # run told an authority its System-5 condition came from 8.4.4.1.(5)
        # and Table 8.4.4.7.-B — the other edition's articles (Sol, `129`.5).
        # `8.4.5.9` naming a different requirement in each edition is the exact
        # collision the repository contract warns about, and here it reached
        # product output.
        prefix = _subsection(ruleset)
        presence_article = f'{prefix}.1.(5); Table {prefix}.7.-B'
        if group['heated']:
            audit.decision('selection',
                           'System 5 reference MODELS HEATING in the two-pipe surrogate — the '
                           f'proposed block is heated, so {prefix}.1.(5)\'s presence requirement '
                           'overrides the Table -B "None" heating column. The Code does not '
                           'select the topology of that heating: a hot-water loop, boiler and '
                           'heating coils are BUILT here, inside a four-pipe fan-coil surrogate',
                           target=','.join(group['zones']),
                           article=presence_article,
                           ruling='D-39',
                           # AHJ-11, on THIS branch only. Sentence (5) requires
                           # identical heating presence while Table -B's cell
                           # for this system says "None" — a genuine internal
                           # tension Sol's `126` confirmed in both editions.
                           # The `else` branch below honours the table on an
                           # UNHEATED block, which is text-consistent and must
                           # not cite anything (Sol, `127`).
                           ahj='AHJ-11')
        else:
            merged = dict(assignment.config or {})
            merged.update({'heating': 'none', 'needs_boiler': False,
                           'mau_heating_coil_type': 'None'})
            assignment.config = merged
            audit.decision('selection',
                           f'System 5 reference built COOLING-ONLY — Table {prefix}.7.-B heating '
                           '"None" honoured (proposed block is unheated)',
                           target=','.join(group['zones']),
                           article=f'Table {prefix}.7.-B; {prefix}.1.(5)', ruling='D-39')

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


def reference_hvac(model, code='necb2020', building=None, audit=None, proposed_annual=None):
    """Generate the NECB reference HVAC for a proposed model (any OSM). The proposed
    model is untouched: the reference is built on a clone.

    Pipeline (all article-tagged in the audit): characterize the proposed HVAC ->
    select reference systems per Table 8.4.4.7.-A -> replace each zone group's HVAC
    with the mapped catalog system (energy type follows proposed) -> apply the
    reference modeling rules (8.4.4.8 oversizing caps, 8.4.4.18 fan specs, 8.4.4.13
    heat-pump operating limits) -> apply the edition's minimum efficiencies.

    Sizing: the package never runs simulations. Capacity-threshold selection rules and
    the proposed-oversizing comparison use sized values when present and warn when
    not; run your sizing pass on the proposed model first for full fidelity, and on
    the returned reference model before applying downstream (efficiencies re-apply
    cleanly via apply_efficiencies after sizing).

    The returned reference is READY TO SIZE (D-90): the build-time efficiency pass
    reads the proposed's sizing through the clone, so before returning,
    prepare_for_resizing releases the plant capacities that pass derived from sizing
    — capacities the model supplied as INPUTS are kept — and, deliberately, EVERY
    hard-set pump power, including one carried in with a plant this reference COPIED
    from the proposed (the D-58 residential identity).

    Pump power is released because 8.4.4.14 (2025: 8.4.5.14) assigns the reference's
    rated power to this pass rather than letting it be inherited as a number: (1)
    inherits the corresponding proposed pump's head and efficiency, (2) combines
    multiple pumps' peak shaft power, and (3) falls back to the proposed's W/(L/s)
    where head or efficiency is NOT known. Ownership tracking could not preserve a
    value anyway: the post-sizing pass re-derives power for every non-SWH pump it
    finds, whoever set the old one. Releasing BEFORE sizing is what avoids the
    EnergyPlus FATAL on 'Calculated Pump Efficiency > 100%' — a frozen power and head
    meeting a freshly sized flow, found on the SmallHotel gas variant.

    The RELEASE is settled (Sol, 2026-09-16: a hard wattage must not survive a change
    of reference flow). The value that REPLACES it is not. D-11 implements (1)-(3)
    through one mechanism — a whole-building, loop-type W/(L/s) blend, which is (3)'s
    metric — and on a COPIED loop the corresponding pump is the SAME pump, with known
    head and efficiency, so (1) governs there instead. DF-11 tracks the branch;
    behaviour is unchanged here.

    So a direct sizing run of the returned model sizes the reference's own plant, but
    pump power comes back AUTOSIZED and is NOT recoverable from the model: call
    apply_efficiencies(reference, code=..., proposed=proposed) after sizing, as the
    pipeline does, so the transfer lands on the sized flows. WITHOUT proposed= the
    Table curves still apply but no power is transferred (the skip is audited) and
    EnergyPlus sizes each pump from its own head and flow. A service-water circulator
    is released here too, yet left 'as built' by that pass (D-27, outside 8.4.4.14),
    so it simply stays autosized.

    :param model: the proposed openstudio.model.Model
    :param code: the code id, e.g. 'necb2020'
    :param building: dict or None — overrides for 'storeys', 'zone_types',
        'kitchen_hood_zones', 'refrigerated_zones' (defaults derived from the model)
    :param audit: AuditLog or None
    :return: ReferenceResult — model (clone), assignments, audit
    """
    return _reference_hvac(model, resolve(code), building=building,
                           audit=audit, proposed_annual=proposed_annual)


def _reconcile_declared_storeys(reference, building, audit):
    """Stamp the storey count the SELECTOR used onto the reference's Building.

    The two halves of the System 6 grouping disagreed (Fable's `131` F2). The
    selector reads `building['storeys']` — the `--storeys` override — while
    `VAVReheat` reads `helpers.above_ground_storeys(model)`, which falls back to
    a BuildingStory count and then to 1. Nothing wrote the override onto the
    model, so a building the selector had just classified as more than four
    storeys was GROUPED as one storey: one whole-building VAV, no facade split,
    no Note (3) corner assignment, and no AHJ-10 citation.

    That is worse than the missing citation. `pipeline.py`'s own preflight
    warns that the fallback "would silently treat the building as ONE storey";
    with the override supplied it did exactly that, one layer down.

    Writing it on the REFERENCE only, never the proposed: the selector's
    premise is what the reference must be built on, and the caller's model is
    not ours to edit.

    THE OVERRIDE WINS, including over a model that declares its own count.
    The first version skipped those, calling it deference to the model — and
    Fable's `133` G4 showed that reproduces the very defect F2 fixed: a model
    declaring 2 with `--storeys 6` selected on 6 and GROUPED on 2, one
    whole-building VAV, no facade split, no citation, and no audit entry
    either. As he put it, that is not deference, it is the same split with the
    roles swapped — because `_building_info` already lets the override win in
    the selector. Deference would have to mean refusing the override there
    too.

    So the override wins in both halves, and a CONTRADICTION is warned with
    both numbers named. The audit contract is that warnings are never silent,
    and holding two storey counts while saying nothing breaks it whichever
    number wins.
    """
    declared = (building or {}).get('storeys')
    if not declared:
        return
    declared = int(declared)
    existing = opt(reference.getBuilding().standardsNumberOfAboveGroundStories())
    if existing is not None and int(existing) != declared:
        audit.warn('build',
                   f'the supplied building data says {declared} above-ground '
                   f'storeys and the model DECLARES {int(existing)} — the '
                   'supplied value is an override and wins, here and in the '
                   'reference-system selection, so both halves group on one '
                   'premise; correct the model or drop the override if that '
                   'is not intended',
                   inputs={'storeys': declared,
                           'model_declared_storeys': int(existing)},
                   ruling='D-18')
    elif existing is not None:
        return
    reference.getBuilding().setStandardsNumberOfAboveGroundStories(declared)
    audit.info('build',
               'declared above-ground storey count stamped on the reference '
               'from the supplied building data — the selector and the system '
               'builder must group on the SAME premise',
               inputs={'storeys': declared}, ruling='D-18')


def _reference_hvac(model, ruleset, building=None, audit=None, proposed_annual=None):
    """The proposed -> reference HVAC transform against ONE resolved edition.

    Everything under it — the selection, the per-assignment rules, the
    humidification rebuild, the efficiencies pass and the coverage emission —
    reads this same :class:`btap.codes.Ruleset` (Stage 6).
    """
    import btap.modeling as modeling
    from btap.audit import AuditLog
    from btap.codes.necb.hvac import efficiency as _efficiency

    audit = audit if audit is not None else AuditLog()
    reference = _clone_model(model)
    _reconcile_declared_storeys(reference, building, audit)
    _clear_proposed_part_load_classes(reference, audit)
    _clear_proposed_capacity_ownership(reference, audit)

    facts = _classify.characterize(reference, audit=audit)
    info = _building_info(reference, building, audit)
    assignments = _select_reference_systems(facts=facts, building=info,
                                            ruleset=ruleset, audit=audit,
                                            proposed_annual=proposed_annual)

    rules_data = ruleset.rules("hvac")
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
    proposed_humidification = _capture_humidification(
        reference, audit, table=f'Table {_subsection(ruleset)}.7.-B')
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
        # SYSTEM 1 MERGES TOO. Only Systems 3 and 4 are labelled
        # "Single-zone" in Table 8.4.x.7.-B, which is the wording Sol's `139`
        # turns on; System 1 is a "Unitary air conditioner with baseboard
        # heating" whose Note (2) central make-up air unit serves the blocks
        # together. Selecting per block and merging 1 alongside 2/5/6 keeps
        # that one central unit while 3, 4 and the heat-pump redirects get one
        # unit per block.
        #
        # Splitting System 1 was the one thing my per-block change got wrong:
        # `test_hvac_necb_through_the_wall_build` asserts "System 1 = one
        # central MAU for ventilation air" and saw five.
        # `through_the_wall` is System 1 too — `_residential_assignment`
        # returns it with `reference_system=1`, realised as a central MAU plus
        # per-zone PTACs. Keying on the action alone excluded it, so five
        # blocks produced five MAUs where the Note (2) central unit is one.
        key = ([a.catalog_name, a.config]
               if a.action in ('build', 'through_the_wall')
               and a.reference_system in (1, 2, 5, 6)
               else None)
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
                       article=f'Table {_subsection(ruleset)}.7.-B Note (3)',
                       ruling='D-28')
    assignments = [m[1] for m in merged]

    purchased_cooling_chillers = []
    # DESTRUCTION IS PHASED AHEAD OF CONSTRUCTION, for the whole affected
    # closure at once.
    #
    # `replace_system` is `build_system(..., remove_existing=True)`, so a
    # per-assignment call tore down and built in one step. That was harmless
    # while one assignment covered a whole serving system, and wrong once
    # selection became per thermal block: five block assignments tore down five
    # times, and a plant SHARED by those blocks survived whichever teardown ran
    # first and was then re-adopted by name. Sample 13's own fixture
    # description had warned of exactly that — "with several single-zone groups
    # the district loop survives the per-group teardown and is adopted by name,
    # so the article is only half-applied" — and the multi-energy witnesses
    # caught it: a plant the Code REPLACES kept its proposed markers.
    #
    # Sol's `141`: "Destructive replacement must be planned for the whole
    # affected HVAC closure and completed before replacement construction
    # begins." Phasing it also makes the outcome assignment-order invariant,
    # which a per-assignment teardown can never be.
    replaced_zone_names = [name for assignment in assignments
                           if assignment.action != 'copy_proposed'
                           for name in assignment.zones]
    if replaced_zone_names:
        modeling.remove_hvac_from_zones(
            reference, [zones_by_name[name] for name in replaced_zone_names])
        audit.info('build',
                   'proposed HVAC torn down for every thermal block the '
                   'reference replaces, in ONE pass before any reference '
                   'system is built — a plant shared by several blocks must '
                   'not survive one block\'s teardown and be re-adopted',
                   target=','.join(replaced_zone_names),
                   inputs={'blocks': len(replaced_zone_names),
                           'assignments': sum(1 for a in assignments
                                              if a.action != 'copy_proposed')},
                   ruling='D-101')

    for assignment in assignments:
        if assignment.action == 'copy_proposed':
            audit.info('build', 'proposed system retained in reference (residential rule)',
                       target=','.join(assignment.zones),
                       article='; '.join(a for a in assignment.articles if a is not None))
            continue

        zones = [zones_by_name[n] for n in assignment.zones]
        existing_chillers = {str(chiller.handle())
                             for chiller in reference.getChillerElectricEIRs()}
        existing_boilers = {str(boiler.handle())
                            for boiler in reference.getBoilerHotWaters()}
        # NOT `replace_system`: the teardown already ran above for the whole
        # closure. Removing again here would destroy a plant another block's
        # system has already been built onto.
        result = modeling.build_system(reference, assignment.catalog_name, zones,
                                       config=assignment.config)
        _audit_corner_block_grouping(result, assignment,
                                     _subsection(ruleset), audit)
        purchased_cooling_cop = (assignment.config or {}).get(
            'purchased_cooling_reference_cop')
        if purchased_cooling_cop is not None:
            new_purchased_chillers = [
                (chiller, purchased_cooling_cop)
                for chiller in reference.getChillerElectricEIRs()
                if str(chiller.handle()) not in existing_chillers
            ]
            purchased_cooling_chillers.extend(new_purchased_chillers)
            for chiller, cop in new_purchased_chillers:
                chiller.additionalProperties().setFeature(
                    'btap_purchased_cooling_reference_cop', cop)
        # D-89: persist the selected part-load curve class ON the boiler. The
        # efficiency pass runs AGAIN after reference sizing, so a class held
        # only in this function's locals would be silently overwritten before
        # the annual run (the purchased-cooling COP above is the precedent for
        # exactly that trap). additionalProperties survives clone, save/load
        # and the second pass; the applier reads it back.
        boiler_class = (assignment.config or {}).get('boiler_part_load_curve_class')
        if boiler_class is not None:
            for boiler in reference.getBoilerHotWaters():
                if str(boiler.handle()) not in existing_boilers:
                    boiler.additionalProperties().setFeature(
                        BOILER_PART_LOAD_CLASS_FEATURE, boiler_class)
        built_inputs = {'system': assignment.reference_system, 'action': assignment.action}
        if boiler_class is not None:
            built_inputs['boiler_part_load_curve_class'] = boiler_class
        audit.decision('build', 'reference system built', target=','.join(assignment.zones),
                       inputs=built_inputs,
                       value=assignment.catalog_name,
                       article='; '.join(_uniq([a for a in assignment.articles if a is not None])))
        _apply_fan_rules(result.air_loops, assignment.reference_system, rules_data, audit)
        _apply_zone_fan_rules(zones, assignment.reference_system, rules_data, audit)
        if assignment.reference_system == 'hp':
            _apply_heat_pump_limits(result.air_loops, rules_data, audit)
        _apply_economizers(reference, result.air_loops, assignment.reference_system,
                           ruleset.id, rules_data, audit)
        _apply_dcv(result.air_loops, zones, proposed_dcv, ruleset.id, audit)
        _apply_operating_schedules(result.air_loops, proposed_availability, audit)
        _audit_terminal_secondary_split(zones, assignment.reference_system,
                                        ruleset.id, audit)
        # The (5)(b) fact, for THIS ASSIGNMENT'S groups.
        #
        # This read `group`, which the assignment loop never binds — its only
        # binding is the DCV capture loop far above, so every assignment got
        # whichever zone group iterated LAST. Fable's `131` F1 reproduced both
        # directions through the real build: four single-fuel System 3 zones
        # lost the citation they are owed when a multi-fuel zonal group
        # iterated last, and a multi-fuel zone carried AHJ-1 and AHJ-15
        # together — the claim that its priority is prescribed and the claim
        # that it is not — when it iterated first.
        #
        # The comment that stood here said the fact "is established HERE, where
        # the group's energy types are known". It was established for one group
        # and applied to all of them.
        assignment_zones = set(assignment.zones)
        prescribed = any(
            len(service_set_heating_fuels(candidate, facts)[0]) > 1
            for candidate in (facts.get('zone_groups') or ())
            if assignment_zones & set(candidate.get('zones') or ()))
        _apply_zone_dispatch(zones, assignment.reference_system, ruleset.id,
                             audit, priority_prescribed=prescribed)

    _rebuild_humidification(reference, proposed_humidification, rules_data,
                            ruleset.id, audit)
    _purge_orphaned_ems(reference, audit)
    _purge_orphaned_vrf(reference, audit)
    _apply_oversizing_caps(model, reference, rules_data, audit)
    _efficiency._apply(reference, ruleset=ruleset, audit=audit)
    for chiller, cop in purchased_cooling_chillers:
        chiller.setReferenceCOP(cop)
        audit.decision('efficiency', 'purchased-cooling reference chiller COP applied',
                       target=chiller.nameString(), value=f'COP {cop}',
                       article='Table 8.4.3.5')
    _emit_article_coverage(rules_data, audit)
    # D-90: hand back a model ready to size — the pass above read the proposed's
    # sizing through the clone, so its plant capacities and pump powers are released
    _efficiency.prepare_for_resizing(reference, audit=audit, code=ruleset.id)

    return ReferenceResult(model=reference, assignments=assignments, audit=audit)


def _audit_terminal_secondary_split(zones, reference_system, code, audit):
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
    prefix = resolve(code).article('reference_subsection')
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


#: D-91 scope: the constant-volume rooftop terminals Systems 3 and 4 build.
_CONSTANT_VOLUME_TERMINALS = ('OS_AirTerminal_SingleDuct_ConstantVolume_NoReheat',
                              'OS_AirTerminal_SingleDuct_Uncontrolled')


def _visibly_zero_capacity(component):
    """True only when a component's capacity is KNOWN and is zero.

    Unknown is not zero. An autosized component has no capacity before sizing,
    and treating that as zero would silently drop AHJ-15 on the ordinary
    unsized path — under-disclosing a question, which is the direction that
    hides things. So an unreadable capacity counts as present.
    """
    baseboard = component.to_ZoneHVACBaseboardConvectiveElectric()
    if baseboard.is_initialized():
        value = baseboard.get().nominalCapacity()
        return bool(value.is_initialized()) and float(value.get()) <= 0.0
    water = component.to_ZoneHVACBaseboardConvectiveWater()
    if water.is_initialized():
        coil = water.get().heatingCoil().to_CoilHeatingWaterBaseboard()
        if coil.is_initialized():
            value = coil.get().heatingDesignCapacity()
            return bool(value.is_initialized()) and float(value.get()) <= 0.0
    return False


def _dispatch_ahj(priority_prescribed, ordered, zeroed):
    """AHJ-15's narrowing, applied where the dispatch order is chosen.

    Sol's `126` narrowed it to the case where Article 9.(5)(b) does NOT already
    prescribe the proposed priority — where it does, the priority is carried
    over rather than chosen by us, and there is nothing to refer. `127` adds
    that a zero-capacity component is not a second competing path.

    The (5)(b) fact is CARRIED IN from the selection rather than rediscovered
    here: this function knows the final topology but not the proposed group's
    energy types, and rebuilding that knowledge would be the duplicated
    predicate D-100 exists to remove.
    """
    if priority_prescribed:
        return None
    if not [zone for zone in ordered if zone not in set(zeroed)]:
        return None
    return 'AHJ-15'


def _apply_zone_dispatch(zones, reference_system, code, audit,
                         priority_prescribed=False):
    """D-91 — zone equipment dispatch for one-unit-per-block Systems 3 and 4.

    Legacy creation order puts the baseboard first in `SequentialLoad`, so it
    answers the zone load predicted before the supply air arrives, and the
    always-on constant-volume rooftop then delivers outdoor-air-cooled air with
    little load left to meet: the corpus 01 reference missed its heating
    setpoint for ~800 occupied hours. 8.4.4.9.(3) (2025: 8.4.5.9.(3)) sets
    installed capacities, not an operating order, and 8.4.2.10.(2) requires
    limited capacities to be represented — so the order is adjudicated here:
    the rooftop terminal is offered the full load first in both orders and the
    baseboard, the more controllable device, serves the residual.

    Everything is set explicitly — scheme, both priorities and all four
    sequential fractions — because a proposed `UniformLoad` scheme or other
    fractions survive the clone and the equipment teardown. Only a zone with its
    own System 3/4 loop and exactly one constant-volume terminal and one
    baseboard as its conditioning equipment is in scope. A zone exhaust fan does
    not condition the zone and teardown deliberately keeps it (a kitchen hood
    selects System 4), so it is ignored in that test and ends up after the
    terminal and baseboard. Shared units (D-28 grouping), the heat-pump
    reference, System 6 and zones with any other conditioning equipment are left
    untouched."""
    if reference_system not in (3, 4):
        return
    ordered, zeroed = [], []
    for zone in zones:
        loop = zone.airLoopHVAC()
        if not loop.is_initialized() or len(loop.get().thermalZones()) != 1:
            continue
        equipment = [e for e in zone.equipmentInHeatingOrder()
                     if not e.to_FanZoneExhaust().is_initialized()]
        terminals = [e for e in equipment
                     if e.iddObjectType().valueName() in _CONSTANT_VOLUME_TERMINALS]
        baseboards = [e for e in equipment
                      if e.to_ZoneHVACBaseboardConvectiveWater().is_initialized()
                      or e.to_ZoneHVACBaseboardConvectiveElectric().is_initialized()]
        if len(equipment) != 2 or len(terminals) != 1 or len(baseboards) != 1:
            continue
        terminal, baseboard = terminals[0], baseboards[0]
        # AHJ-15 needs BOTH to be able to serve overlapping demand, so a
        # component whose capacity is visibly ZERO excludes the zone — it is
        # not a second path competing for the load (Sol, `127`).
        if _visibly_zero_capacity(baseboard):
            zeroed.append(zone.nameString())
        zone.setLoadDistributionScheme('SequentialLoad')
        zone.setHeatingPriority(terminal, 1)
        zone.setCoolingPriority(terminal, 1)
        zone.setHeatingPriority(baseboard, 2)
        zone.setCoolingPriority(baseboard, 2)
        for component in (terminal, baseboard):
            zone.setSequentialHeatingFraction(component, 1.0)
            zone.setSequentialCoolingFraction(component, 1.0)
        ordered.append(zone.nameString())
    if not ordered:
        return

    prefix = resolve(code).article('reference_subsection')
    audit.decision('rules', 'zone dispatch: the rooftop air terminal runs before the baseboard',
                   target=','.join(ordered),
                   inputs={'zones': len(ordered), 'reference_system': reference_system,
                           'load_distribution': 'SequentialLoad',
                           'air_terminal_priority': 1, 'baseboard_priority': 2,
                           'sequential_fractions': 1.0},
                   value='the rooftop unit is offered the full zone load and the baseboard serves '
                         'the residual; heating energy moves from the baseboards and hot-water plant '
                         'to the rooftop coil — accepted, because the article sets installed '
                         'capacities, not annual shares',
                   article=f'{prefix}.9.(3); 8.4.2.10.(2)', ruling='D-91',
                   ahj=_dispatch_ahj(priority_prescribed, ordered, zeroed))


def _apply_zone_fan_rules(zones, reference_system, rules_data, audit):
    """T10 (audit 2026-07-25): 8.4.4.18.(3) fan spec (640 Pa / 40% combined)
    covers HVAC systems 1-5 — including their ZONE-equipment supply fans
    (fan coils, PTAC/PTHP OnOff fans), which previously kept SDK defaults."""
    if reference_system == 6:
        return

    spec = (rules_data.get('fans') or {}).get('systems_1_3_4_5', {}).get('supply') or {}
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


def apply_economizer_thresholds(model, audit=None, code=None):
    """T3 (audit 2026-07-25): 8.4.4.12 economizers apply only where Article
    5.2.2.7 applies to the proposed system — mechanical cooling AND (sized
    supply > 1500 L/s OR cooling capacity > 20 kW); dwelling-only/hotel
    systems exempt (approximated: System 1 already exempt per D-20; zone
    types are not re-derivable here). POST-SIZING pass, umbrella-called
    alongside apply_energy_recovery: strips economizers from loops below the
    trigger, loudly.

    :param model: sized reference openstudio.model.Model (modified in place)
    :param audit: AuditLog or None (a new one is created if None)
    :param code: code id, for the edition's own article prefix. `None` keeps
        2020's, which is what the hardcoded value already was — the economizer
        article is 8.4.4.12 in NECB 2020 and 8.4.5.12 in NECB 2025, and both
        entries here spelled 2020's into the ARTICLE FIELD on every 2025 run
        (Fable's `133` G3). In NECB 2025 `8.4.4.12` does not exist at all:
        that subsection stops at `.2`.
    :return: AuditLog — the audit carrying every keep/strip decision
    """
    economizer_article = f'{_subsection(resolve(code) if code else None)}.12.'
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
                           article=f'{economizer_article}; 5.2.2.7.(1)', ruling='D-22')
        else:
            ctrl.setEconomizerControlType('NoEconomizer')
            audit.decision('rules', 'economizer REMOVED — below the 5.2.2.7 trigger (<=1500 L/s and <=20 kW)',
                           target=air_loop.nameString(),
                           inputs={'supply_l_s': ruby_round(supply * 1000, 0),
                                   'cooling_kw': ruby_round(cooling_w / 1000.0, 1)},
                           value='NoEconomizer', article=f'{economizer_article}; 5.2.2.7.(1)', ruling='D-22')
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


def _purge_orphaned_vrf(model, audit):
    """A proposed VRF outdoor unit whose terminals left with the proposed HVAC.

    replace_system removes the zone terminals, but the outdoor unit is neither
    zone equipment nor on a loop, so it stays behind serving nothing. That
    leftover is not harmless: the classic VRF object carries no
    heating/cooling-only field of its own, so the terminals were also the only
    evidence of its Table 5.2.12.1.-I class, and a condenser serving no zones
    reaches EnergyPlus as dead input. The reference has no VRF system — say so
    and remove it, rather than leaving the efficiency pass to reason about a
    unit that serves nothing (D-85).
    """
    orphans = [unit for unit in sorted_by_name(model.getAirConditionerVariableRefrigerantFlows())
               if not unit.terminals()]
    for unit in orphans:
        audit.info('build', 'proposed VRF outdoor unit serves no reference zone — removed',
                   target=unit.nameString(), inputs={'terminals': 0},
                   article='8.4.4.1.', ruling='D-85')
        unit.remove()
    return orphans


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


def _emit_article_coverage(rules_data, audit):
    """Completeness accounting: every article of the reference subsection is written
    to the audit with its handling status and how many decisions cited it this run —
    unimplemented or partially-implemented articles surface as warnings, so a missed
    requirement is visible in every log rather than discovered by review."""
    emit_coverage(rules_data['article_coverage'], audit)


def _clear_proposed_part_load_classes(reference, audit):
    """D-89 forbids proposed-to-reference class propagation: the ONLY class
    the reference carries is the one its own selection elects (purchased
    heating -> modulating). A boiler cloned from the proposed may arrive
    tagged — by a user, a tool, or a previous reference pass — and the
    efficiency pass gives a present tag precedence over the row, so every
    incoming tag is removed here, before any reference system is built."""
    cleared = []
    # Every object the efficiency pass resolves a class for: boilers and
    # both gas heating coil types (single- and multi-stage). A new consumer
    # in efficiency.py must be added here too — the propagation test asserts
    # the two lists agree.
    consumers = (list(reference.getBoilerHotWaters())
                 + list(reference.getCoilHeatingGass())
                 + list(reference.getCoilHeatingGasMultiStages()))
    for component in consumers:
        props = component.additionalProperties()
        feature = props.getFeatureAsString(BOILER_PART_LOAD_CLASS_FEATURE)
        if feature.is_initialized() and feature.get():
            cleared.append(f"{component.nameString()}={feature.get()}")
            props.resetFeature(BOILER_PART_LOAD_CLASS_FEATURE)
    if cleared:
        audit.info('build', 'proposed part-load class tags not carried into the reference',
                   target=','.join(c.split('=')[0] for c in cleared),
                   inputs={'cleared': cleared}, ruling='D-89')


def _clear_proposed_capacity_ownership(reference, audit):
    """D-90: plant capacity ownership is re-derived from the REFERENCE's own
    sizing. A boiler, chiller or tower cloned from the input model may carry the
    ownership features of an efficiency pass it already went through; a stale
    'autosized' basis would make the reference stage from another run's sizing
    and a stale base name would rename it, so every incoming feature is removed
    before any reference system is built."""
    from btap.codes.necb.hvac import efficiency as _efficiency

    cleared = []
    for component in (list(reference.getBoilerHotWaters())
                      + list(reference.getChillerElectricEIRs())
                      + list(reference.getCoolingTowerSingleSpeeds())):
        props = component.additionalProperties()
        present = [f for f in _efficiency.OWNERSHIP_FEATURES if props.hasFeature(f)]
        for feature in present:
            props.resetFeature(feature)
        if present:
            cleared.append(component.nameString())
    if cleared:
        audit.info('build', 'plant capacity ownership carried in with the model not used in the '
                            "reference — re-derived from the reference's own sizing",
                   target=','.join(cleared), inputs={'components': len(cleared)}, ruling='D-90')


def _clone_model(model):
    clone = model.clone()
    return clone.to_Model() if hasattr(clone, 'to_Model') else clone


def _building_info(model, overrides, audit):
    """Building info defaults derived from the model, overridable by the caller."""
    # DERIVED LAZILY. The model is the source of truth for its own storey
    # count, and asking it now raises when it cannot say — so a caller who has
    # already supplied the count must not be made to answer for the model's
    # silence. Computing first and overriding second would fail the very runs
    # the override exists for.
    info = {'zone_types': _zone_space_types(model)}
    if overrides:
        info.update(overrides)
    if info.get('storeys') is None:
        info['storeys'] = _costing_geometry.above_ground_storeys(model)
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


def _apply_economizers(model, air_loops, reference_system, code, rules_data, audit):
    """8.4.4.12 (2025: 8.4.5.12): reference cooling-with-outside-air. Table -12
    routes systems 1/3/4/6 and all heat-pump systems to 5.2.2.8 (air economizer:
    up to 100% outdoor air, differential reversion) and systems 2/5 to 5.2.2.9
    (WATER-side economizer, built since D-56)."""
    prefix = resolve(code).article('reference_subsection')
    if reference_system in (2, 5):
        _apply_water_economizer(model, reference_system, code, rules_data, audit)
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

def _apply_water_economizer(model, reference_system, code, rules_data, audit):
    prefix = resolve(code).article('reference_subsection')
    article = f'{prefix}.12. (Table -12 -> 5.2.2.9)'
    spec = rules_data['water_economizer']
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


def _capture_humidification(reference, audit, table='Table 8.4.4.7.-B'):
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
                   article=f'{table} Note (1)', ruling='D-55')

    orphans = [h for h in (list(reference.getHumidifierSteamElectrics())
                           + list(reference.getHumidifierSteamGass()))
               if str(h.handle()) not in attributed]
    if orphans:
        names = ', '.join(sorted(h.nameString() for h in orphans))
        audit.warn('build', f'{len(orphans)} proposed humidifier(s) sit on NO air loop serving a thermal block '
                            f'({names}) — the reference humidification they '
                            'correspond to CANNOT be determined and is not rebuilt',
                   article=f'{table} Note (1)', ruling='D-55')
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


def _rebuild_humidification(reference, captured, rules_data, code, audit):
    """Rebuild humidification on the reference loops, after they exist."""
    if not captured:
        return

    spec = rules_data['humidification']
    prefix = resolve(code).article('reference_subsection')
    table = f'Table {prefix}.7.-B'
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
            # NO AHJ-12 here, deliberately. The reference kept the proposed
            # loop, so its identity independently settles whether
            # humidification is present and no choice was made — Sol's `127`
            # excludes exactly that case. A missing citation looks identical to
            # a forgotten one, which is the risk site-owned applicability
            # trades for removing a duplicated predicate, so the reason sits
            # here rather than only in the register.
            audit.info('build', 'proposed humidification retained on this reference loop — the loop was not replaced',
                       target=air_loop.nameString(), article=article, ruling='D-55')
            continue
        _build_reference_humidifier(air_loop, records, spec, article, audit)

    missed = [n for n in _uniq([r['air_loop'] for r in captured.values()]) if n not in served]
    if not missed:
        return

    # TARGETED. Fable's `131` F10: this passed no `target=`, so the condition
    # reached the report as ('AHJ-12', None) and its approval line carried no
    # "Applies to" — the loop names existed only inside the action text, where
    # the resolver cannot and must not read them.
    audit.warn('build', f"the proposed humidification on {', '.join(sorted(missed))} has NO reference loop to carry "
                        'it — the thermal blocks it served are unconditioned or zonally served in the reference, '
                        'so it is not rebuilt',
               target=','.join(sorted(missed)),
               article=article, ruling='D-55', ahj='AHJ-12')


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
                            'rebuilt on this loop', target=air_loop.nameString(),
                   article=article, ruling='D-55', ahj='AHJ-12')
        return

    control = _attach_humidity_control(air_loop, humidifier, records, spec)
    if control is None:
        humidifier.remove()
        audit.warn('build', 'the proposed humidification on this thermal block has NO determinable humidity '
                            'control (no zone humidistat survives and the proposed used no scheduled minimum-humidity '
                            'setpoint) — an uncontrolled humidifier is INERT, so none is rebuilt',
                   target=air_loop.nameString(), article=article,
                   ruling='D-55', ahj='AHJ-12')
        return

    audit.decision('build', 'reference humidification rebuilt on the proposed energy source',
                   target=air_loop.nameString(),
                   inputs={'energy_source': source,
                           'proposed_systems': _uniq([r['air_loop'] for r in records]),
                           'control': control, 'capacity': 'autosized'},
                   value=humidifier.nameString(), article=article,
                   ruling='D-55', ahj='AHJ-12')


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


def _apply_dcv(air_loops, zones, proposed_dcv, code, audit):
    prefix = resolve(code).article('reference_subsection')
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

def _apply_fan_rules(air_loops, reference_system, rules_data, audit):
    fans = rules_data['fans']
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


def _apply_heat_pump_limits(air_loops, rules_data, audit):
    """8.4.4.13.(2)(d): the reference heat pump shall not operate in heating mode
    below -10 degC."""
    cutoff = rules_data['heat_pump_reference']['heating_cutoff_oat_c']
    for air_loop in _array(air_loops):
        for comp in _coils.supply_components(air_loop):
            staged = comp.to_CoilHeatingDXMultiSpeed()
            if not (comp.to_CoilHeatingDXSingleSpeed().is_initialized() or staged.is_initialized()):
                continue

            coil = staged.get() if staged.is_initialized() else comp.to_CoilHeatingDXSingleSpeed().get()
            coil.setMinimumOutdoorDryBulbTemperatureforCompressorOperation(cutoff)
            audit.decision('rules', 'heat pump heating cutoff set', target=coil.nameString(),
                           value=f'compressor off below {cutoff} degC',
                           article=rules_data['heat_pump_reference']['article'])


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


def _apply_oversizing_caps(proposed, reference, rules_data, audit):
    """8.4.4.8: reference oversizing = the lesser of the proposed oversizing and the
    cap (30% heating / 10% cooling), applied via the model-wide sizing factors."""
    caps = rules_data['oversizing']
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
                   article=f"{heat_pump_article_base(rules_data.get('selection') or {})}.(2)(b)", ruling='D-52')


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
    # The STRUCTURAL proxy lives in a different article from the one
    # article_base names, so it needs the subsection on its own. Fable's `131`
    # F6: these said '8.4.4.9.(4)' on a 2025 run whose `article=` correctly
    # said 8.4.5.13, and the resolver quotes the action verbatim as the
    # condition detail — so an authority was handed a 2020 number, which in
    # 2025 is the archetype-EUI subsection entirely.
    #
    # This block sat ABOVE the docstring, which made it a leading comment and
    # left `__doc__` None (Fable's `133` G6).
    proxy = '.'.join(article_base.split('.')[:3]) + '.9.(4)'
    audit = audit if audit is not None else NullAudit()
    threshold = (hp_rules or {}).get('aux_energy_type_threshold_fraction') or 0.33
    if annual is None:
        # NO AHJ-2. Sol's `127`: the absence of annual data in a `none` or
        # `sizing` run is a MODE limitation, not a question an authority can
        # settle — (2)(g)'s basis is only live once the comparison is actually
        # made.
        audit.info('selection',
                   'no proposed annual data (simulate: :sizing/:none, or the annual run predates this '
                   f'feature) — the {article_base}.(2)(g) auxiliary-fuel election cannot run; the '
                   f'structural {proxy} proxy elects the fuel instead',
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
        # NO AHJ-2 either: with no auxiliary energy there is nothing for the
        # (2)(g) comparison to weigh, so no basis question arises.
        audit.info('selection',
                   'the proposed thermal blocks have no terminal or auxiliary heating energy in the annual '
                   f'run — {article_base}.(2)(g) has nothing to elect; the structural {proxy} '
                   'proxy elects the fuel',
                   target=','.join(group['zones']),
                   inputs={'hp_gj': ruby_round(hp_j / 1e9, 2)},
                   article=f'{article_base}.(2)(g)', ruling='D-52')
        return None

    share = hp_j / total_j
    if share <= threshold:
        audit.decision('selection',
                       f"the heat pump carries {ruby_round(share * 100, 1)}% of the blocks' annual space-heating "
                       f'energy — NOT above the {ruby_round(threshold * 100)}% proviso, so sentence (g) does not '
                       f'elect; the structural {proxy} proxy elects the fuel',
                       target=','.join(group['zones']),
                       inputs={'hp_gj': ruby_round(hp_j / 1e9, 2), 'total_gj': ruby_round(total_j / 1e9, 2),
                               'share': ruby_round(share, 3), 'threshold': threshold, 'sentence': sentence},
                       article=f'{article_base}.(2){sentence}', ruling='D-52',
                       ahj='AHJ-2')
        return None

    elected_fuel, elected_j = max(aux_by_fuel.items(), key=lambda kv: kv[1])
    variant = _energy_type_variant(elected_fuel)
    if variant is None:
        audit.warn('selection',
                   f"the largest terminal/aux energy type is '{elected_fuel}', which maps to NO reference "
                   f'system variant — the structural {proxy} proxy elects the fuel instead',
                   target=','.join(group['zones']),
                   inputs={'by_fuel_gj': {f: ruby_round(j / 1e9, 2) for f, j in aux_by_fuel.items()}},
                   article=f'{article_base}.(2){sentence}', ruling='D-52',
                   # CITES, even though the election could not be carried out.
                   # Fable's `131` F5: by this point BOTH of Sol's `127`
                   # positive conditions have happened — the (2)(g) share
                   # comparison was made and the largest auxiliary type was
                   # elected on the delivered-heat basis AHJ-2 is about. That
                   # the elected fuel then maps to no variant is a mapping
                   # limitation, not a reason the disposition stops applying.
                   # `_energy_type_variant` covers gas|oil|propane|purchased
                   # and electric, so a hydronic coil on a loop with no
                   # recognised fuel ('Unknown') lands here.
                   ahj='AHJ-2')
        return None
    audit.decision('selection',
                   "auxiliary heating energy type ELECTED from the proposed run's simulated period: "
                   f'the terminal/aux energy type with the largest energy use over that period is {elected_fuel} '
                   f"({ruby_round(elected_j / 1e9, 2)} GJ delivered), and the heat pump's "
                   f'{ruby_round(share * 100, 1)}% share exceeds the {ruby_round(threshold * 100)}% proviso '
                   '((h) inapplicable: the source is classified air/water/ground)',
                   target=','.join(group['zones']),
                   inputs={'by_fuel_gj': {f: ruby_round(j / 1e9, 2) for f, j in aux_by_fuel.items()},
                           'hp_gj': ruby_round(hp_j / 1e9, 2), 'share': ruby_round(share, 3),
                           'sentence': sentence, 'scope_loops': scope_loops,
                           'scope_zone_count': len(scope_zones)},
                   value=variant, article=f'{article_base}.(2){sentence}',
                   ruling='D-52', ahj='AHJ-2')
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


def _heating_plant(group, facts):
    """The single hot-water plant serving this group, by fuel-set intersection.

    Intersection finds the plant that carries ANY of the group's heating
    energy types, which is NOT the same as a plant that carries them all:
    samples 16/17/18 have a GAS-ONLY hot-water plant plus electric heating
    elsewhere in the serving group, and they intersect on NaturalGas alone.
    Callers must therefore ask `_plant_is_multi_fuel` before saying anything
    about boilers per energy type (Sol, `113`).
    """
    wanted = {str(f) for f in group.get('heating_energy_types') or ()}
    candidates = [pl for pl in (facts.get('plants') or ())
                  if pl.get('type') == 'hot_water'
                  and wanted & set(pl.get('fuels') or ())]
    return candidates[0] if len(candidates) == 1 else None


def _heating_plant_name(group, facts):
    plant = _heating_plant(group, facts)
    return None if plant is None else plant.get('name')


def _plant_covers_group(plant, group, facts=None):
    """True when ONE plant carries EVERY energy type the serving group uses.

    `len(plant.fuels) > 1` is NOT enough, and Sol built the counter-example
    (`114`): a group of {Electricity, NaturalGas, FuelOilNo2} served by a
    gas+oil plant took the plant-specific branch and reported shares of
    {NaturalGas: 0.6, FuelOilNo2: 0.4} — electricity dropped out of the
    DENOMINATOR entirely. A plant-only allocation may be described as the
    group's allocation only when the plant accounts for the whole group.
    """
    if plant is None:
        return False
    plant_fuels = {str(f) for f in (plant.get('fuels') or ())}
    # The SERVICE SET, per AHJ-5. A water-loop heat-pump group's service set
    # includes its source-loop boiler's fuel, which the terminal hot-water
    # plant does not carry — so this correctly reports NO coverage there and
    # the (6) cardinality condition does not fire for that shape.
    if facts is None:
        group_fuels = {str(f) for f in (group.get('heating_energy_types') or ())}
    else:
        group_fuels, _added = service_set_heating_fuels(group, facts)
    return len(plant_fuels) > 1 and group_fuels <= plant_fuels


def multi_energy_articles(selection, ruleset=None):
    """``(capacity_ratio, single_boiler)`` for the RESOLVED edition.

    8.4.4.9.(5)/(6)(b) in 2020 and 8.4.5.9.(5)/(6)(b) in 2025. A hardcoded
    literal here cited 2020's numbers to the AHJ on every 2025 run (Sol,
    `113`).

    The subsection comes from the manifest's own `reference_subsection`
    registry when a ruleset is in hand, as `_audit_terminal_secondary_split`
    already does. Deriving it from the heat-pump article instead had a SILENT
    2020 fallback: `heat_pump_article_base` returns '8.4.4.13' when that rule
    value is missing or malformed, so a 2025 selection would have cited 2020
    without a word (Fable, `117`). The derivation is kept only as the
    fallback for a caller with no ruleset, and it is the narrower risk of the
    two.
    """
    if ruleset is not None:
        subsection = ruleset.article('reference_subsection')
    else:
        subsection = heat_pump_article_base(selection).rsplit('.', 1)[0]
    return f'{subsection}.9.(5)', f'{subsection}.9.(6)(b)'


def _heating_allocation(group, facts):
    """``(shares, watts_by_fuel)`` for a multi-energy heating group, or None.

    8.4.4.9.(5) ratios the proposed building's heating equipment CAPACITY
    allocation per energy type. `classify` records that allocation on the
    plant it belongs to; this finds the plant serving THIS group by fuel-set
    intersection and returns the shares when every capacity is known.

    Returns None when the allocation cannot be established — an autosized
    plant, no sizing run, or more than one candidate plant. That is the common
    case rather than the edge: every multi-fuel plant in the sample corpus is
    autosized, and a `--simulate none` run never sizes at all. The caller must
    say UNKNOWN rather than guess a fraction (Sol, `110`).
    """
    wanted = {str(f) for f in group.get('heating_energy_types') or ()}
    candidates = [pl for pl in (facts.get('plants') or ())
                  if pl.get('type') == 'hot_water'
                  and wanted & set(pl.get('fuels') or ())]
    if len(candidates) != 1:
        return None
    watts = candidates[0].get('fuel_capacities_w') or {}
    known = {f: w for f, w in watts.items() if w}
    if len(known) < 2 or len(known) != len(watts):
        return None
    total = sum(known.values())
    if total <= 0:
        return None
    return {f: w / total for f, w in known.items()}, known


#: What was ACTUALLY measured, named precisely enough to be checked. My
#: previous wording said the annual result was "unchanged at the legacy gem's
#: 0.5 sizing factor", which is false: it changed by -616.6 kWh. What was
#: unchanged across BOTH experiments is that the secondary boiler never
#: fired. Sol caught the conflation (`114`), and the two statements are not
#: the same claim.
#:
#: Both experiments ran on sample 11's necb2020 reference model (gas-primary)
#: with CWEC2020 Toronto weather. Neither says anything about a 2025 runtime,
#: a different sample, or a cooling plant.
#: The subsection the measurement was taken under. The experiments ran on one
#: edition, so the note travels only to that edition: attaching it elsewhere
#: would present it as verifying a model it never touched (Sol, `114`).
_MEASURED_SUBSECTION = '8.4.4'
_FIXTURE_MEASUREMENT = (
    'MEASURED on sample 11 only, necb2020, gas-primary, annual, on the model '
    'FED TO THE SIZING RUN (both boilers autosized, 64,396 W each) — which is '
    'NOT the model the annual pipeline runs, where the staging pass has '
    'already driven the secondary to ~0 W: '
    '(i) BOILER COUNT at sizingFactor 1.0 — two boilers 158,219.4 kWh vs one '
    'boiler 158,219.4 kWh, identical to 0.1 kWh; (ii) SIZING FACTOR at two '
    'boilers — 1.0 gives 158,219.4 kWh and 0.5 gives 157,602.8 kWh, a CHANGE '
    'of -616.6 kWh (-0.39%). What held in BOTH experiments is that the '
    'secondary boiler never fired, which is NOT the same statement as the '
    'annual kWh being unchanged. These are measurements on that one fixture, '
    'edition and model state, NOT a property of this model.')


def service_set_heating_fuels(group, facts):
    """The energy types a group's HEATING SERVICE SET uses, which is not the
    same as the energy types its own terminal equipment burns.

    AHJ-5, ruled by Sol's `126` against fetched text. A water-loop heat-pump
    group's own `heating_energy_types` carries only the compressor fuel, but
    Division A defines a primary system as equipment converting fuel or
    electricity to heating and distributing it to secondary systems — giving
    boilers as the example — and the Article 13 Appendix note says a water-loop
    heat-pump system's source loop may include an auxiliary heat source, "e.g.
    a boiler". Article 13.(1) routes that case back to Table 7-A and does not
    exclude Article 9. So an active fuel-fired source-loop boiler is a SECOND
    energy type used by the heating service set, and 8.4.x.9.(5) fires.

    In Sol's words: "classifying only the group-local compressor fuel and
    ignoring the source-loop heat is a predicate defect."

    **The 8.4.2.2.(5) exclusion is NOT detected.** A genuinely redundant source
    whose controls operate it only when the primary is not operating may be
    excluded — the mutually-exclusive-controls test AHJ-4 settled — and nothing
    here inspects control schemes. A normal source-loop boiler that runs while
    compressors run does not qualify for that exclusion, so including it is the
    right default; a true standby boiler is OVER-disclosed, and that direction
    is deliberate because it over-reports a question rather than hiding one.
    """
    fuels = {str(f) for f in (group.get('heating_energy_types') or ())}
    loops = {str(n) for n in (group.get('heat_pump_source_loops') or ())}
    if not loops:
        return fuels, set()
    added = set()
    for plant in (facts.get('plants') or ()):
        if str(plant.get('name')) not in loops:
            continue
        for fuel in (plant.get('fuels') or ()):
            text = str(fuel)
            if text and text not in fuels:
                added.add(text)
    return fuels | added, added


def _disclosure_ahj(source_loop_fuels, covers):
    """The register ids this multi-energy disclosure branch owns.

    SITE-OWNED applicability (Sol's `127`): this branch has the selected
    topology, so it declares which dispositions apply rather than letting the
    final collector re-characterize the model to guess. `path.py` previously
    recomputed `multi_energy_serving_systems` for exactly that, which was a
    second source of truth beside the branch that already knew.

    * AHJ-1 always — an affected run's single-fuel reference is the
      non-conforming substitution an authority must accept.
    * AHJ-3 only where ONE hydronic plant carries the group's fuels, because
      the (6) cardinality question needs such a plant to exist.
    * AHJ-5 only where the SOURCE LOOP contributed a fuel, as the `ruled`
      explanation of why this group entered scope. It adds no condition.
    """
    ids = ['AHJ-1']
    if source_loop_fuels:
        ids.append('AHJ-5')
    return ' '.join(ids)


def _plant_cardinality_ahj():
    """AHJ-3 alone, because its scope is the PLANT and not the service set.

    It used to ride on the AHJ-1 entry, which forced one dedupe key for two
    different questions: AHJ-1 follows each proposed heating service and
    allocation choice, AHJ-3 follows the hydronic plant cardinality choice, and
    one plant can carry two service sets. Keying the pair by plant collapsed
    the two AHJ-1 records into one (Sol, `143`).
    """
    return 'AHJ-3'


def multi_energy_serving_groups(facts):
    """Serving groups whose PROPOSED heating system uses more than one energy
    type, excluding the purchased-energy route.

    These are exactly the groups 8.4.x.9.(5) governs and this tool does not
    implement: it elects ONE reference energy type, and Sol ruled on fetched
    normative text (`119`) that no single-fuel basis satisfies (5)(a)'s
    capacity ratio. A run containing any of them therefore cannot carry an
    unqualified Code-compliance determination.

    A pure function of `facts`, deliberately: the caller needs this to label
    the verdict, and deriving it by scanning audit prose would couple the
    determination to wording. It is the same predicate
    `_disclose_multi_energy` applies per group.
    """
    out = []
    for group in facts.get('zone_groups') or ():
        fuels, _added = service_set_heating_fuels(group, facts)
        if 'Purchased' in fuels or len(fuels) < 2:
            continue
        out.append(group)
    return out


def multi_energy_serving_systems(facts, *, hydronic_only=False):
    """The DEDUPED serving-system identities behind `multi_energy_serving_groups`.

    The group list overcounts: sample 11 is five thermal blocks served by ONE
    plant, so the disclosure emits ONE finding while the group list has five
    entries. A verdict label built from the group count would say "5
    multi-energy serving systems" where there is one — the same overcounting
    mistake in a new place. This applies the disclosure's own dedupe key, so
    the label and the findings always agree.
    """
    seen: dict = {}
    for group in multi_energy_serving_groups(facts):
        plant = _heating_plant(group, facts)
        if _plant_covers_group(plant, group, facts):
            key = f"plant:{plant.get('name')}"
            label = plant.get('name') or 'the shared heating plant'
        elif hydronic_only:
            # `hydronic_only` selects the systems a BOILER question can apply
            # to. Sentence (6) governs "where a hydronic system is modeled",
            # so a mixed group with no plant carrying its fuels cannot raise a
            # boiler-cardinality conflict — asking it to was Sol's `122`
            # blocker 3, where a bare dual-fuel thermal-block group with no
            # hydronic plant was handed the boiler question anyway.
            continue
        else:
            key = 'group:' + ','.join(sorted(group['zones']))
            label = ','.join(group['zones'])
        seen.setdefault(key, label)
    return [seen[k] for k in sorted(seen)]


def _disclose_multi_energy(group, selection, facts, audit, ruleset=None,
                           disclosed=None):
    """8.4.x.9.(5): disclose a multi-energy proposed heating system.

    Called from `_finalize` on EVERY election path. It states what is
    UNRESOLVED and nothing else — four separate corrections from Sol's `113`
    and `114` all came from this entry claiming more than the model supports:

    * a gas-only plant was described as holding one boiler per energy type;
    * a plant covering only part of the group had its fuels reported as the
      group's whole allocation;
    * the ratio was called NOT MET when it is not verified or enforced —
      sample 16's reference does carry electric ASHP heating stages, so
      "the other types carry no reference capacity" was simply false;
    * (6)(b) was cited as a demonstrated departure without any capacity to
      establish which of (6)(b)/(c)/(d) even applies.
    """
    fuels, source_loop_fuels = service_set_heating_fuels(group, facts)
    # 8.4.x.6 is the separate route for THIS group only. The building-wide
    # `facts.purchased_energy.heating` flag used to suppress the diagnostic
    # everywhere, so district heat on one primary system hid the (5) finding
    # for an unrelated gas+electric serving system. 8.4.x.6 governs the
    # purchased-energy system's CORRESPONDING system, not every group
    # (Sol, `119`/`120`).
    if 'Purchased' in fuels:
        return
    distinct = {str(f) for f in fuels}
    if len(distinct) < 2:
        return

    ratio_article, boiler_article = multi_energy_articles(selection, ruleset)
    sentence_six = boiler_article.split('(')[0] + '(6)'
    plant = _heating_plant(group, facts)
    covers = _plant_covers_group(plant, group, facts)
    plant_name = (plant or {}).get('name')
    # ONE DISCLOSURE PER CODE DECISION SCOPE, listing every affected block.
    #
    # The scope is the proposed HEATING SERVICE/ALLOCATION choice, not the
    # thermal block: 8.4.x.9.(5) transfers one capacity allocation and one
    # operating priority from one proposed heating system. One multi-energy
    # plant and one control sequence serving five blocks is ONE unresolved
    # choice affecting five block-level reference systems — "repeating the
    # same warning five times does not disclose five questions; it obscures
    # one question" (Sol, `141`).
    #
    # Where a plant COVERS the service set, the plant is that scope and the key
    # was already right — which is why a shared plant stayed at one disclosure
    # through the block refactor. Where no plant covers it, the scope is the
    # SERVICE SET, so the key must name the original serving zones rather than
    # the narrowed block. Sol is explicit that `plant:<name>` is not a
    # universal service identity: 8.4.x.9.(6)(a) distinguishes a plant from the
    # systems it serves, so both keys are kept.
    service_set = tuple(group.get('_serving_zones') or group['zones'])
    # THE AHJ-1 SCOPE IS THE SERVICE SET, ALWAYS. `plant:<name>` was used
    # whenever a plant covered the group, which is not a service identity: two
    # independent proposed serving systems drawing on ONE dual-fuel hot-water
    # plant are two 8.4.x.9.(5) allocation choices, and the plant key emitted a
    # single warning for both. 8.4.x.9.(6)(a) itself distinguishes a plant from
    # the systems it serves, and AHJ-3's cardinality question — which IS
    # per-plant — is emitted separately below.
    key = 'service:' + ','.join(sorted(service_set))
    # `disclosed` is the caller's call-scoped set; the `facts` fallback keeps
    # a direct unit-test call working without leaking into a pipeline run.
    seen = facts.setdefault('_multi_energy_warned', set()) \
        if disclosed is None else disclosed
    if key in seen:
        return
    seen.add(key)

    # Every affected block is listed, so a reader sees the one question's full
    # reach rather than one block of it.
    # The TARGET is the affected blocks, not the plant: a plant name told a
    # reader nothing about this question's reach, and the test that was meant
    # to prove the entry "names every affected block" only required the target
    # to be non-empty, which a plant name satisfies.
    target = ','.join(service_set)
    inputs = {'proposed_energy_types': sorted(distinct),
              'serving_system': target,
              'affected_blocks': sorted(service_set),
              'affected_block_count': len(service_set),
              'reconciled': False}
    if plant is not None:
        # The fuels are recorded whenever a plant is IDENTIFIED. Gating this on
        # the name meant an unnamed plant silently lost the one input a reader
        # needs to check the claim.
        inputs['plant_energy_types'] = sorted(
            {str(f) for f in (plant.get('fuels') or ())})
        if plant_name:
            inputs['serving_plant'] = plant_name
    if not covers:
        # Nothing may be said about boilers per energy type, nor about the
        # group's shares, because the plant does not account for the group.
        inputs['group_shares'] = (
            'UNRESOLVED: no single plant carries every energy type this '
            'group uses, so a plant-only capacity split would omit the '
            'others from the denominator')
        audit.warn(
            'selection',
            'UNRESOLVED: the heating equipment serving this group uses MORE '
            f'THAN ONE ENERGY TYPE. {ratio_article} requires the reference '
            'heating capacities to follow the proposed energy-type '
            'allocation, and this tool does NOT compute or enforce that '
            'allocation — it elects ONE energy type for the group. Whether '
            'the reference happens to match the proposed allocation is '
            'therefore NOT VERIFIED here, in either direction, and a '
            'passing annual result is not evidence that it does',
            target=target, inputs=inputs, article=ratio_article,
            ahj=_disclosure_ahj(source_loop_fuels, covers=False))
        return

    allocation = _heating_allocation(group, facts)
    if allocation is None:
        inputs['proposed_capacity_shares'] = 'unavailable without sizing'
    else:
        shares, watts = allocation
        inputs['proposed_capacity_shares'] = {
            f: round(s, 4) for f, s in sorted(shares.items())}
        inputs['proposed_capacity_w'] = {
            f: round(w, 1) for f, w in sorted(watts.items())}
    # Which of (6)(b)/(c)/(d) applies depends on the REFERENCE plant's
    # heating capacity, which does not exist at selection time. Cite the
    # sentence, never a subclause we cannot establish (Sol, `114`.4).
    inputs['plant_boiler_count'] = plant.get('boiler_count')
    inputs['boiler_count_subclause'] = (
        f'NOT ESTABLISHED: {sentence_six} bands the requirement by the '
        f'reference plant capacity, which is not known at selection time, '
        f'so no subclause is claimed')
    # NOTHING about the reference plant is asserted here. Sol reproduced four
    # outcomes (`120`, `121`), and the entry lists them rather than choosing:
    # the proposed plant may be adopted; it may be torn down and REPLACED by
    # a newly built plant of the selected variant (a one-group mixed
    # gas/electric loop became a different two-boiler NaturalGas plant, with
    # no proposed handle on either boiler); it may be torn down and not
    # rebuilt where the variant needs no boiler; and if a hydronic plant does
    # result, the post-sizing staging pass acts on primary/secondary ROLE
    # blind to fuel, whose effect differs by capacity band and by whether any
    # role is recognised at all -- `_plant_role` returns None unless there
    # are exactly two boilers.
    inputs['live_capacity_outcome'] = (
        'NOT ESTABLISHED at selection time. The reference plant may be this '
        'plant adopted; may be a DIFFERENT plant, built by the selected '
        'variant after this one is torn down, holding none of these devices; '
        'or may not exist at all, where the variant needs no boiler. If a '
        'hydronic plant does result, the post-sizing '
        'staging pass acts on primary/secondary ROLE and is blind to energy '
        'type: an equal role-labelled pair in the two-boiler band is '
        'PRESERVED, a recognised secondary below the single-boiler threshold '
        'is driven to ~0 W, and a plant whose devices take no recognised '
        'role is not staged at all. Which of these applies, and therefore '
        'whether the proposed allocation survives, is not known here')
    if ratio_article.startswith(_MEASURED_SUBSECTION):
        inputs['fixture_measurement'] = _FIXTURE_MEASUREMENT
    else:
        inputs['fixture_measurement'] = (
            'NONE for this edition: the boiler-count and sizing-factor '
            'experiments were run under '
            f'{_MEASURED_SUBSECTION} and say nothing about this one')
    audit.warn(
        'selection',
        'UNRESOLVED: the PROPOSED heating system puts MORE THAN ONE ENERGY '
        'TYPE on ONE BOILER PLANT that carries every energy type the group '
        'uses. What the REFERENCE plant ends up with is not established '
        'here: it depends on the selected system variant, on whether the '
        'plant is adopted or torn down, and on a post-sizing staging pass '
        'that acts on primary/secondary ROLE blind to energy type and whose '
        'effect differs by capacity band and by whether any role is '
        'recognised at all. '
        f'Whether that conflicts with {sentence_six} is NOT established '
        f'here, because its applicable subclause depends on the reference '
        f'plant capacity. NEITHER {ratio_article}\'s capacity-ratio clause '
        f'(a) nor its operating-priority clause (b) is computed or enforced, '
        'so the allocation is NOT VERIFIED in either direction, and a '
        'passing annual result is not evidence that it is satisfied',
        target=target, inputs=inputs,
        article=f'{ratio_article}; {sentence_six}',
        ahj=_disclosure_ahj(source_loop_fuels, covers=True))

    # AHJ-3 IS A SEPARATE RECORD, SCOPED TO THE PLANT. The (6) cardinality
    # question is asked once of the hydronic plant however many serving systems
    # draw on it, so it dedupes on the plant while the allocation disclosure
    # above dedupes on the service set. One plant with two multi-energy service
    # sets therefore yields two AHJ-1 records and ONE AHJ-3 record, a shape the
    # single combined entry could not express (Sol, `143`).
    plant_key = f'plant:{plant_name}'
    if plant_key not in seen:
        seen.add(plant_key)
        audit.warn(
            'selection',
            'UNRESOLVED: ONE hydronic heating plant carries every energy type '
            f'the serving systems use, so {sentence_six} bands a requirement '
            'on the REFERENCE plant by its heating capacity — which does not '
            'exist at selection time, so no subclause is claimed. How many '
            'reference boiler plants correspond to this proposed plant is an '
            'N:1 correspondence question the acceptable-solution text does '
            'not settle',
            target=plant_name or 'unnamed hydronic plant',
            inputs={'serving_plant': plant_name,
                    'plant_energy_types': sorted(
                        {str(f) for f in (plant.get('fuels') or ())}),
                    'plant_boiler_count': plant.get('boiler_count'),
                    'service_sets_drawing_on_it': 'NOT ESTABLISHED at '
                    'selection time: each serving system is disclosed '
                    'separately, and this record is the plant-scoped question',
                    'boiler_count_subclause': inputs[
                        'boiler_count_subclause']},
            article=sentence_six,
            ahj=_plant_cardinality_ahj())


def _reference_energy_type(group, selection, facts, audit):
    """8.4.4.9.(4)/8.4.4.10.(3): reference energy type follows the proposed system;
    8.4.4.6.(1): purchased heating is represented by a gas-fired boiler.

    Returns ``(energy_type, boiler_part_load_curve_class)``. The class is
    ``None`` for every selection but purchased heating — D-89: the Code names
    a MODULATING boiler only there, and the class it names is read from the
    rule file (never a literal here), so a future edition that names a
    different class changes data, not code.
    """
    # GROUP-LOCAL on purpose. AHJ-5's service set decides whether 8.4.x.9.(5)
    # FIRES; it does not decide the reference's energy type. Electing a
    # source-loop boiler's gas here would change a water-loop heat-pump
    # group's whole reference system type, which Sol's `126` ruling does not
    # ask for and no measurement supports.
    fuels = group['heating_energy_types']
    if 'Purchased' in fuels or (facts.get('purchased_energy') or {}).get('heating'):
        purchased_heating = selection['special_rules']['purchased_heating']
        part_load_curve_class = purchased_heating.get('part_load_curve_class')
        audit.decision('selection', 'purchased heating energy -> represented by gas-fired modulating boiler',
                       target=','.join(group['zones']),
                       inputs={'part_load_curve_class': part_load_curve_class},
                       article=purchased_heating['article'], ruling='D-89')
        return 'gas', part_load_curve_class
    # MULTI-ENERGY: this function ELECTS one energy type and says nothing
    # about 8.4.x.9.(5). The disclosure moved out to
    # `_disclose_multi_energy`, which `_finalize` calls after EVERY election
    # path — including the heat-pump auxiliary election, which used to skip
    # this function entirely and so emitted no disclosure at all (Sol, `114`).
    #
    # The cascade below prefers a fossil fuel whenever one is present. It does
    # NOT weigh the proposed capacity allocation: a capacity-dominant election
    # was written, measured to flip the reference's whole system type on a
    # sized electric-dominant plant, and separated onto its own branch because
    # no frozen scenario exercised it (Sol, `113`).
    #
    # Sol's `112` REJECTED the hydronic carve-out I proposed, and Fable's
    # `117` confirmed the reading against the live text of both editions: (5)
    # is conditioned on the PROPOSED system's energy types with no hydronic
    # exclusion, (6) constrains a reference plant without replacing (5), and
    # (4) shows the Code writes "Except as provided in Sentence (5)" when it
    # intends an exception. Table -B's System 2 is inherently hydronic and
    # dual-fuel-capable, so a carve-out would silently exempt it.
    if any(re.search(r'gas|oil|propane', str(f), re.IGNORECASE) for f in fuels):
        return 'gas', None
    if 'Electricity' in fuels:
        return 'electric', None

    audit.warn('selection', 'no proposed heating energy type detected — electric reference assumed',
               target=','.join(group['zones']), article='8.4.4.9.(4)')
    return 'electric', None
