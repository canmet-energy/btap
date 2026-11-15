"""The space-type section of a recipe: the floor-area mix.

phylroy's addition (2026-11-04): the recipe needs space types BY FLOOR AREA,
because that is what lets a reader generate a building with the right mix. A
2000 m2 office is not described by its space type NAMES — it is described by
the proportions, and without them a reader would have to invent them.

The loads section already carries a per-space-type floor area, but only for
space types that HAVE loads, and with no fractions or total. This section is
the whole mix, including space types carrying nothing.

Three things make an area wrong if ignored, so each is handled and reported:

**Multipliers.** A space with `multiplier() == 5` represents five, so its
floor area counts five times. Ignoring it would understate every repeated
space type in a multi-storey model.

**`partofTotalFloorArea`.** A plenum or similar is excluded from a building's
floor area by the SDK's own flag. Counting it would dilute every fraction and
make them describe a building larger than the one that exists.

**Spaces with no space type.** Their floor area cannot be attributed, so it is
reported separately rather than dropped — area that vanishes between the
model and the recipe is area a reader cannot account for.

Measured on `Office_pre-1960` and `Hangar_pre-1960`: none of the three occurs
(no excluded spaces, none unassigned, every multiplier 1). So the corpus does
not exercise those branches and the tests construct them instead.
"""

from __future__ import annotations

from btap._compat import opt, sorted_by_name


def space_types_section(model, audit=None):
    """The recipe's space-type mix, by floor area.

    `fraction_of_total` is of the TOTAL floor area, so the fractions of all
    attributed space types plus the unassigned fraction sum to 1.

    :returns: ``{'total_floor_area_m2': …, 'by_space_type': {…},
                 'excluded_from_floor_area': {…}, 'unassigned': {…}}``
    """
    by_space_type = {}
    unassigned_area, unassigned_spaces = 0.0, 0
    excluded_area, excluded_names = 0.0, []

    for space in sorted_by_name(model.getSpaces()):
        area = space.floorArea() * space.multiplier()
        if not space.partofTotalFloorArea():
            excluded_area += area
            excluded_names.append(space.nameString())
            continue
        space_type = opt(space.spaceType())
        if space_type is None:
            unassigned_area += area
            unassigned_spaces += 1
            continue
        entry = by_space_type.setdefault(
            space_type.nameString(),
            {'floor_area_m2': 0.0, 'spaces': 0,
             'standards_building_type': opt(space_type.standardsBuildingType()),
             'standards_space_type': opt(space_type.standardsSpaceType())})
        entry['floor_area_m2'] += area
        entry['spaces'] += 1

    total = sum(e['floor_area_m2'] for e in by_space_type.values()) \
        + unassigned_area
    for entry in by_space_type.values():
        entry['fraction_of_total'] = (round(entry['floor_area_m2'] / total, 6)
                                      if total else None)
        entry['floor_area_m2'] = round(entry['floor_area_m2'], 2)

    section = {
        'total_floor_area_m2': round(total, 2),
        'by_space_type': dict(sorted(by_space_type.items())),
        'excluded_from_floor_area': {
            'spaces': len(excluded_names),
            'floor_area_m2': round(excluded_area, 2),
            'names': sorted(excluded_names)[:20],
            'why': 'partofTotalFloorArea is false on these spaces — plenums '
                   'and the like — so their area is NOT in the total or the '
                   'fractions',
        },
        'unassigned': {
            'spaces': unassigned_spaces,
            'floor_area_m2': round(unassigned_area, 2),
            'fraction_of_total': (round(unassigned_area / total, 6)
                                  if total else None),
            'why': 'these spaces have no space type, so their area cannot be '
                   'attributed — reported rather than dropped, because area '
                   'that vanishes between model and recipe is area a reader '
                   'cannot account for',
        },
    }

    # The standards keys are what a reader needs to resolve a space type
    # against a code catalogue, and they are frequently absent on a hand-built
    # model. That absence is the reason such a model fails NECB's space-type
    # preflight gate, so the recipe states it rather than leaving a reader to
    # discover it at run time.
    untagged = sorted(name for name, entry in by_space_type.items()
                      if entry['standards_building_type'] is None
                      or entry['standards_space_type'] is None)
    section['from'] = {
        'space_types': len(by_space_type),
        'untagged_space_types': len(untagged),
        'untagged': untagged[:20],
    }
    if audit is not None:
        if untagged:
            audit.warn('recipe',
                       f'{len(untagged)} of {len(by_space_type)} space '
                       'type(s) carry no standards building/space type — a '
                       'reader cannot resolve them against a code catalogue, '
                       'and a model built from them would fail an NECB '
                       'space-type preflight gate',
                       inputs={'untagged': untagged[:20]})
        if unassigned_spaces:
            audit.warn('recipe',
                       f'{unassigned_spaces} space(s) have no space type — '
                       f'{round(unassigned_area, 1)} m2 of floor area is '
                       'unattributed',
                       inputs={'unassigned_m2': round(unassigned_area, 2)})
    return section
