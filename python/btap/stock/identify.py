"""Suggest catalogue systems for an unidentified zone group — as CANDIDATES.

phylroy asked to try identifying the system (2026-11-04), because without it a
recipe from a hand-built model cannot regenerate the building: HVAC drives
85.6% of site energy on `Office_pre-1960` — heating alone is 71.4% — and
`catalog_name` is null for every one of its 47 zone groups, so the reader
refuses all of them and the "round trip" rebuilds only the other 14%.

**This does not overturn the refusal rule; it supplies evidence to it.**
`classify.py` is right that structural identification cannot be made reliable:

    the facts a classifier needs here are DESTROYED by the time the coil scan
    runs [...] A real packaged unit and a field-erected built-up DX coil then
    both read as `loop_dx_cooling`, and nothing downstream can tell them
    apart.

So this never writes `catalog_name` and never makes a group `resolved`. It
returns a RANKED list of candidates, each with the facts that matched and the
facts that did not, and the caller decides. A candidate that is built is
audited as a candidate.

**The catalogue already contains six `origin: campus` systems** — "Hot water
unit heaters", "PSZ MAU Hot Water with water-heated PTAC", "Shared hot water
heating-only air handler", "Shared furnace with DX cooling and no outdoor
air", "Shared hot water air handler with water reheat" and "Recirculating CRAH
chilled water with humidity control". Someone curated those from the campus
project, and they map almost one-to-one onto the Office archetype's
signatures, which is why this is worth attempting at all rather than scoring
blind.
"""

from __future__ import annotations

from btap.modeling.hvac import catalog

#: `family_guess` from `classify.py` -> the catalogue families that could
#: realise it. Deliberately WIDE: narrowing happens on the facts below, and a
#: family omitted here can never be suggested, which is the worse error.
FAMILY_CANDIDATES = {
    'unconditioned': (),
    'zonal_heating_only': ('baseboards', 'unit_heaters'),
    'zonal_heat_cool': ('mau_ptac', 'fan_coils', 'vrf', 'wshp', 'doas_pthp',
                        'zone_terminal'),
    'central_doas_or_cv': ('furnace', 'psz', 'doas', 'evap_cooler'),
    'packaged_single_zone': ('psz', 'furnace'),
    'multizone_vav': ('vav_reheat', 'dual_duct'),
}

#: A zonal unit the classifier saw -> the catalogue family or attribute it
#: implies.
_ZONAL_FAMILY = {'unit_heater': 'unit_heaters', 'ptac': 'mau_ptac',
                 'baseboard': None}


def _fuel_tokens(energy_types):
    """Normalise `['NaturalGas']` to the words catalogue fields use."""
    out = set()
    for fuel in energy_types or ():
        lowered = str(fuel).lower()
        if 'gas' in lowered or 'propane' in lowered:
            out.add('gas')
        elif 'electric' in lowered:
            out.add('electric')
        elif 'district' in lowered or 'steam' in lowered:
            out.add('district')
        elif 'oil' in lowered or 'diesel' in lowered:
            out.add('oil')
    return out


def _score(row, group):
    """Score one catalogue row against one zone group's facts.

    Returns ``(score, matched, against)`` where `matched` are the facts that
    agreed and `against` the facts that did not. A disagreement does NOT
    disqualify — it lowers the score and is reported, because the facts
    themselves are partly structural guesses and a hard filter on a guess
    would silently discard the right answer.
    """
    matched, against = [], []
    score = 0.0

    heat = _fuel_tokens(group.get('heating_energy_types'))
    cool = _fuel_tokens(group.get('cooling_energy_types'))
    zonal = set(group.get('zonal_units') or ())
    family = row.get('family')

    # The family is the strongest single signal, and it is already filtered by
    # the caller, so agreement here is assumed rather than scored.

    for unit in zonal:
        implied = _ZONAL_FAMILY.get(unit)
        if implied is None:
            continue
        if family == implied:
            score += 3.0
            matched.append(f'zonal unit {unit!r} implies family {implied!r}')

    if 'baseboard' in zonal:
        baseboard = row.get('baseboard_type')
        if baseboard in ('Hot Water', 'Electric'):
            score += 2.0
            matched.append(f'baseboard present; row has {baseboard!r}')
            if baseboard == 'Hot Water' and 'gas' in heat:
                score += 1.0
                matched.append('hot-water baseboard with gas heating')
            elif baseboard == 'Electric' and 'electric' in heat:
                score += 1.0
                matched.append('electric baseboard with electric heating')
        elif baseboard == 'None':
            score -= 1.5
            against.append('baseboard present but row has none')
    elif row.get('baseboard_type') in ('Hot Water', 'Electric'):
        score -= 1.0
        against.append(f"row has {row['baseboard_type']!r} baseboard, "
                       'none seen in the group')

    # A COIL MEDIUM IS NOT A FUEL, and conflating them inverted this test.
    # Measured: the `vav_reheat` family has NO gas coil at all — 12 rows are
    # 'Hot Water' and 8 'Electric' — because a reheat coil is hydronic or
    # electric and gas reaches it THROUGH A BOILER. A first version asked
    # whether the coil string contained the fuel word, so for a gas-heated
    # building the correct hot-water rows were penalised exactly like the wrong
    # electric ones, and electric won on name order. A hot-water coil fed by a
    # gas boiler is a gas-heated system.
    coil = str(row.get('heating_coil_type') or '').lower()
    # Fuels that can fire a boiler, and therefore agree with a hydronic coil.
    boiler_fuels = {'gas', 'oil', 'district'}
    if coil and heat:
        if 'electric' in coil:
            if 'electric' in heat:
                score += 2.0
                matched.append("electric heating coil matches electric "
                               "heating")
            else:
                score -= 1.5
                against.append(f'electric heating coil against {sorted(heat)} '
                               '— no boiler can feed it')
        elif 'water' in coil or 'steam' in coil:
            if heat & boiler_fuels:
                score += 2.0
                matched.append(f'{row["heating_coil_type"]!r} coil fed by a '
                               f'{sorted(heat & boiler_fuels)} boiler')
            elif 'electric' in heat:
                # An electric boiler is legal but unusual; mildly against.
                score -= 0.5
                against.append(f'{row["heating_coil_type"]!r} coil with '
                               'electric-only heating implies an electric '
                               'boiler')
        elif 'gas' in coil:
            if 'gas' in heat:
                score += 2.0
                matched.append('gas heating coil matches gas heating')
            else:
                score -= 1.5
                against.append(f'gas heating coil against {sorted(heat)}')

    # THE BOILER'S OWN FUEL, which is the field that breaks the tie that cost
    # 75,600 kWh. 'Baseboard gas boiler' and 'Baseboard district hot water'
    # both scored 3.50 on baseboard medium alone, so the alphabetical sort
    # picked DISTRICT for a NaturalGas building — and the generated model
    # carried 75,600 kWh of district heating the original does not use at all.
    # Nine catalogue rows declare `boiler_fuel` and one declares
    # `hw_source: district`; both were being ignored.
    boiler_fuel = _fuel_tokens([row.get('boiler_fuel')]
                               if row.get('boiler_fuel') else [])
    if boiler_fuel and heat:
        if boiler_fuel & heat:
            score += 2.5
            matched.append(f"boiler fuel {row['boiler_fuel']!r} matches "
                           f'{sorted(heat)}')
        else:
            score -= 2.0
            against.append(f"boiler fuel {row['boiler_fuel']!r} against "
                           f'{sorted(heat)}')

    # A district source is a different PLANT, not a different efficiency, so
    # proposing one for a building that fires its own boiler introduces an
    # energy stream the original has none of.
    if row.get('hw_source') == 'district':
        if 'district' in heat:
            score += 2.5
            matched.append('district hot water matches district heating')
        else:
            score -= 3.0
            against.append(
                f'row is DISTRICT hot water but the group heats with '
                f'{sorted(heat) or "nothing"} — this would introduce a '
                'purchased-heat stream the building does not have')
    if row.get('chw_source') == 'district' and 'district' not in cool:
        score -= 3.0
        against.append('row is district chilled water; the group is not')

    if row.get('needs_boiler') and heat & {'gas', 'oil', 'district'}:
        score += 0.5
        matched.append(f'row needs a boiler; group heats with {sorted(heat)}')
    elif row.get('needs_boiler') and heat:
        score -= 0.5
        against.append(f'row needs a boiler; group heats with {sorted(heat)}')

    if cool:
        if row.get('needs_chiller') or row.get('chiller_type'):
            score += 0.5
            matched.append('group is cooled; row carries a chiller')
        elif 'electric' in cool:
            score += 0.5
            matched.append('group cools electrically; row is DX-capable')
    elif row.get('needs_chiller'):
        score -= 1.0
        against.append('row needs a chiller; group is not cooled')

    # Provenance, as a TIEBREAK and nothing more. Six rows carry
    # `origin: campus` and were curated from the project these archetypes come
    # from, so they are a better first guess for a campus model — but a
    # provenance tag is not evidence about the equipment, so it cannot
    # outweigh a fact.
    if row.get('origin') == 'campus':
        score += 0.25
        matched.append("row origin is 'campus' (tiebreak only)")

    return score, matched, against


def identify_candidates(group, *, limit=3):
    """Ranked catalogue candidates for one zone group's descriptive facts.

    :param group: a zone group from `hvac_section`, resolved or not. A group
        that is already resolved returns no candidates — there is nothing to
        guess.
    :returns: a list of ``{'system', 'family', 'score', 'matched',
        'against'}``, best first, or ``[]`` when the group is unconditioned or
        no family could be proposed.
    """
    if group.get('resolved'):
        return []
    facts = group.get('descriptive') or group
    guess = facts.get('family_guess')
    families = FAMILY_CANDIDATES.get(guess)
    if not families:
        return []

    scored = []
    for row in catalog.rows():
        if row.get('family') not in families:
            continue
        score, matched, against = _score(row, facts)
        scored.append({'system': row.get('name'), 'family': row.get('family'),
                       'origin': row.get('origin'), 'score': round(score, 2),
                       'matched': matched, 'against': against})
    scored.sort(key=lambda c: (-c['score'], c['system'] or ''))
    return scored[:limit]


def suggest(section, *, limit=3):
    """Add `candidates` to every unresolved group of an `hvac_section`.

    The section is returned CHANGED IN PLACE for convenience, but nothing is
    marked resolved and no `system` key is written: a candidate stays a
    candidate until something outside this module accepts it.
    """
    for group in section.get('zone_groups', []):
        if group.get('resolved'):
            continue
        candidates = identify_candidates(group, limit=limit)
        group['candidates'] = candidates
        group['candidate_note'] = (
            'RANKED GUESSES, not identifications. classify.py establishes '
            'that structural identification cannot be made reliable because '
            'the facts needed are destroyed before the coil scan runs. Each '
            'candidate carries what matched and what did not; a caller must '
            'accept one explicitly, and building from it is audited as a '
            'candidate.' if candidates else
            'no candidate: the group is unconditioned, or its family_guess '
            'proposes no catalogue family.')
    return section
