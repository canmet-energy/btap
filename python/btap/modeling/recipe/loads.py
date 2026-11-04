"""The loads section of a recipe: one aggregate per space type.

Covers osruby's `ecm_lighting`, `ecm_plugs` and `ecm_infiltration`, and
campus's `reduce_lighting_load_by_percentage`,
`reduce_infiltration_by_percentage` and `led_lighting`.

**A SCALING FACTOR CANNOT BE READ FROM A MODEL, and this section does not
pretend otherwise.** osruby's fields are `lighting_scaling_factor` and
`elec_equipment_scaling_factor`, and campus's are reduction percentages —
both are RATIOS against a baseline the model does not carry. A model holds
only the result. So the writer emits the ABSOLUTE density and says, in the
section itself, that the factor form is not recoverable; a recipe claiming a
factor of 1.0 because it could not find the baseline would be inventing the
baseline too.

The fractions are different: `fraction_radiant`, `fraction_visible`,
`return_air_fraction`, `fraction_latent` and `fraction_lost` are stored on the
definition and ARE read directly.
"""

from __future__ import annotations

from btap._compat import opt, sorted_by_name

SPREAD_WARNING_RATIO = 1.5

# The five mutually exclusive infiltration methods, as (reader, recipe field).
# Exactly one is ever set, because each setter clears the others.
_INFILTRATION_READERS = (
    ('designFlowRate', 'infiltration_design_flow_rate_m3_per_s'),
    ('flowperSpaceFloorArea', 'infiltration_flow_per_space_m3_per_s_m2'),
    ('flowperExteriorSurfaceArea',
     'infiltration_flow_per_exterior_area_m3_per_s_m2'),
    ('flowperExteriorWallArea',
     'infiltration_flow_per_exterior_wall_area_m3_per_s_m2'),
    ('airChangesperHour', 'infiltration_air_changes_per_hour'),
)


def _num(value):
    """A float from a plain number or an optional, or None."""
    if value is None:
        return None
    if hasattr(value, 'is_initialized'):
        value = opt(value)
        if value is None:
            return None
    return float(value)


def _aggregate(values, areas=None):
    """Area-weighted mean with its spread, or None when nothing is readable.

    Weighted by FLOOR AREA when it is available, because a space type's
    density applies per square metre and an unweighted mean over instances
    would let a one-room space type outvote a forty-room one.
    """
    pairs = [(a, v) for a, v in zip(areas or [1.0] * len(values), values)
             if v is not None]
    if not pairs:
        return None
    weight = sum(a for a, _v in pairs) or float(len(pairs))
    mean = sum(v * a for a, v in pairs) / weight
    vs = sorted(v for _a, v in pairs)
    out = {'value': round(mean, 6),
           'from': {'instances': len(pairs),
                    'min': round(vs[0], 6), 'max': round(vs[-1], 6)}}
    if vs[0]:
        ratio = vs[-1] / vs[0]
        out['from']['spread_ratio'] = round(ratio, 2)
        if ratio > SPREAD_WARNING_RATIO:
            out['from']['spread_warning'] = (
                f'these {len(pairs)} values span {round(ratio, 2)}x, so one '
                'number is a lossy summary of the set')
    return out


def _lighting(space_type, floor_area):
    rows = [light.lightsDefinition() for light in space_type.lights()]
    if not rows:
        return None
    out = {}
    for field, reader in (
            ('lighting_power_density_w_m2', 'wattsperSpaceFloorArea'),
            ('lighting_watts_per_person', 'wattsperPerson'),
            ('lighting_fraction_radiant', 'fractionRadiant'),
            ('lighting_fraction_visible', 'fractionVisible'),
            ('lighting_return_air_fraction', 'returnAirFraction')):
        agg = _aggregate([_num(getattr(d, reader)()) for d in rows],
                         [floor_area] * len(rows))
        if agg is not None:
            out[field] = agg
    if out:
        # Watts/Area and Watts/Person are mutually exclusive, so naming the
        # method tells a reader which of the two densities above is the real
        # one rather than leaving them to infer it from which is present.
        out['lighting_calculation_method'] = sorted(
            {d.designLevelCalculationMethod() for d in rows})
    return out or None


def _plugs(space_type, floor_area):
    rows = [equip.electricEquipmentDefinition()
            for equip in space_type.electricEquipment()]
    if not rows:
        return None
    out = {}
    for field, reader in (
            ('plug_power_density_w_m2', 'wattsperSpaceFloorArea'),
            ('elec_equipment_fraction_radiant', 'fractionRadiant'),
            ('elec_equipment_fraction_latent', 'fractionLatent'),
            ('elec_equipment_fraction_lost', 'fractionLost')):
        agg = _aggregate([_num(getattr(d, reader)()) for d in rows],
                         [floor_area] * len(rows))
        if agg is not None:
            out[field] = agg
    return out or None


def _people(space_type, floor_area):
    """Occupancy, through whichever of THREE mutually exclusive methods is set.

    A first version read only `peopleperSpaceFloorArea` and reported nothing:
    measured on `Office_pre-1960`, all fifteen definitions use `Area/Person`
    with `spaceFloorAreaperPerson == 10.3`, so the density reader returns None
    for every one of them. The "absent, never defaulted" rule is what made
    that visible as a gap rather than a zero.
    """
    rows = [person.peopleDefinition() for person in space_type.people()]
    if not rows:
        return None
    out = {}
    for field, reader in (
            ('occupancy_people_per_m2', 'peopleperSpaceFloorArea'),
            ('occupancy_number_of_people', 'numberofPeople'),
            ('occupancy_m2_per_person', 'spaceFloorAreaperPerson'),
            ('occupancy_fraction_radiant', 'fractionRadiant')):
        agg = _aggregate([_num(getattr(d, reader)()) for d in rows],
                         [floor_area] * len(rows))
        if agg is not None:
            out[field] = agg
    if out:
        out['occupancy_calculation_method'] = sorted(
            {d.numberofPeopleCalculationMethod() for d in rows})
    return out or None


def _infiltration(space_type):
    rows = list(space_type.spaceInfiltrationDesignFlowRates())
    if not rows:
        return None
    out = {}
    for reader, field in _INFILTRATION_READERS:
        agg = _aggregate([_num(getattr(r, reader)()) for r in rows])
        if agg is not None:
            out[field] = agg
    if out:
        out['infiltration_calculation_method'] = sorted(
            {r.designFlowRateCalculationMethod() for r in rows})
    return out or None


def loads_section(model, audit=None):
    """The recipe's loads section, one entry per space type that has loads.

    Space types with no loads at all are omitted rather than listed as empty:
    a space type carrying nothing is not a load specification.

    :returns: ``{'by_space_type': {...}, 'not_recoverable': [...]}``
    """
    by_space_type = {}
    for space_type in sorted_by_name(model.getSpaceTypes()):
        floor_area = sum(space.floorArea() * space.multiplier()
                         for space in space_type.spaces()) or 1.0
        entry = {}
        for key, reader in (('lighting', _lighting), ('plugs', _plugs),
                            ('occupancy', _people)):
            got = reader(space_type, floor_area)
            if got is not None:
                entry[key] = got
        infiltration = _infiltration(space_type)
        if infiltration is not None:
            entry['infiltration'] = infiltration
        if entry:
            entry['from'] = {'spaces': len(space_type.spaces()),
                             'floor_area_m2': round(floor_area, 1)}
            by_space_type[space_type.nameString()] = entry

    section = {
        'by_space_type': by_space_type,
        'not_recoverable': [
            {'field': 'lighting_scaling_factor',
             'why': 'a ratio against a baseline the model does not carry — '
                    'only the resulting absolute density can be read'},
            {'field': 'elec_equipment_scaling_factor',
             'why': 'as above'},
        ],
    }
    if audit is not None:
        audit.info('recipe',
                   f'loads read for {len(by_space_type)} space type(s); '
                   'scaling factors are NOT recoverable from a model and are '
                   'declared so rather than defaulted to 1.0',
                   inputs={'space_types': len(by_space_type)})
    return section
