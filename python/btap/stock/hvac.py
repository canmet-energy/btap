"""The HVAC section of a recipe — and the one place it must refuse to guess.

`hvac/classify.py::characterize` does the hard part: it groups zones by air
loop, classifies the plants, and resolves a `catalog_name` where it can. This
section shapes that into a recipe and, crucially, does NOT fill in the gap
where it cannot.

**A system name is never synthesised.** Measured on the campus archetypes,
`catalog_name` is null for all 25 zone groups of
`gagetown_coldlake_Hangar_pre-1960` — and that is the classifier being
correct, not deficient. `_recognize_gem_name` resolves the air loop's NAME
against the catalogue, and a hand-built loop called `Packaged Rooftop Air
Conditioner` resolves to nothing. `classify.py` states why structural
identification cannot substitute:

    the facts a classifier needs here are DESTROYED by the time the coil scan
    runs [...] A real packaged unit and a field-erected built-up DX coil then
    both read as `loop_dx_cooling`, and nothing downstream can tell them
    apart.

So an unresolved group is emitted as `resolved: false` with the descriptive
facts the classifier DID establish, and `family_guess` is carried under that
name rather than promoted to `system`. A recipe naming a catalogue system the
source model is not would build something that silently differs from the
original — the worst failure available to a tool whose output looks
authoritative.
"""

from __future__ import annotations

from btap.modeling.hvac import classify

# Facts worth carrying into a recipe for an UNRESOLVED group: enough for a
# human to pick a catalogue system, without pretending one was identified.
_DESCRIPTIVE = (
    'family_guess', 'heated', 'cooled', 'heating_energy_types',
    'cooling_energy_types', 'terminal_type', 'zonal_units',
    'loop_dx_cooling', 'packaged_unitary', 'heat_pump',
    'system_outdoor_air_method', 'dcv', 'ventilation_sized',
    # The loop coil's MEDIUM. `heating_energy_types` is the fuel resolved
    # through the plant, so it cannot tell a hydronic coil on a gas
    # boiler from a gas burner — the identifier's primary error.
    'supply_heating_media',
)


def _hashable(value):
    """A value usable as a dict key — the descriptive facts include lists."""
    if isinstance(value, list):
        return tuple(_hashable(item) for item in value)
    if isinstance(value, dict):
        return tuple(sorted((k, _hashable(v)) for k, v in value.items()))
    return value


def hvac_section(model, audit=None):
    """The recipe's HVAC section, from `characterize`.

    :returns: ``{'zone_groups': [...], 'plants': [...], 'from': {...}}``
    """
    facts = classify.characterize(model)
    raw = facts.get('zone_groups', [])

    # COLLAPSED BY SIGNATURE, per phylroy's constraint that the recipe be
    # generic rather than exhaustive. Measured on `Office_pre-1960`: 47 zone
    # groups reduce to 10 distinct descriptions — 15 unconditioned, 15 gas
    # baseboard, 8 unit heater, and seven singletons — so emitting all 47
    # repeats the same dictionary 4.7 times over on average and describes
    # nothing the 10 do not.
    buckets, order = {}, []
    for group in raw:
        catalog_name = group.get('catalog_name')
        if catalog_name is not None:
            key = ('resolved', catalog_name, group.get('family'))
        else:
            key = ('unresolved', tuple(
                (name, _hashable(group[name]))
                for name in _DESCRIPTIVE if name in group))
        if key not in buckets:
            buckets[key] = {'groups': [], 'first': group}
            order.append(key)
        buckets[key]['groups'].append(group)

    groups, unresolved = [], 0
    for key in order:
        bucket = buckets[key]
        members, first = bucket['groups'], bucket['first']
        zones, air_loops = [], []
        for member in members:
            zones += member.get('zones', [])
            if member.get('air_loop'):
                air_loops.append(member['air_loop'])
        entry = {
            'resolved': key[0] == 'resolved',
            'zone_groups': len(members),
            'zones': sorted(set(zones)),
            'air_loops': sorted(set(air_loops)),
        }
        if key[0] == 'resolved':
            entry['system'] = first.get('catalog_name')
            entry['family'] = first.get('family')
        else:
            unresolved += len(members)
            entry['descriptive'] = {name: first[name]
                                    for name in _DESCRIPTIVE if name in first}
            entry['evidence'] = first.get('evidence', [])[:6]
            entry['note'] = (
                'no catalogue system identified — the air loop name does not '
                'resolve to one, and structural identification would be a '
                'guess. family_guess is a GUESS and is reported as one; a '
                'reader must choose the system.')
        groups.append(entry)

    section = {
        'zone_groups': groups,
        'plants': facts.get('plants', []),
        'purchased_energy': facts.get('purchased_energy'),
        'from': {
            'built_by_gem': facts.get('built_by_gem'),
            'zone_groups': len(raw),
            'distinct_descriptions': len(groups),
            'resolved': len(raw) - unresolved,
            'unresolved': unresolved,
        },
    }
    if unresolved and audit is not None:
        audit.warn('recipe',
                   f'{unresolved} of {len(raw)} zone group(s) have NO '
                   'catalogue system identified — the recipe reports them as '
                   'unresolved rather than naming a system the model is not',
                   inputs={'unresolved': unresolved,
                           'resolved': len(groups) - unresolved})
    return section
