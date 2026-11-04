"""Build a model from a recipe — the recipe READER (#198).

The other half of #196. The writer derives a recipe from a model; this applies
one to geometry.

**Geometry is an input, not part of the recipe.** osruby's architecture is the
precedent — `resources/*.osm` geometry per building type, one assumptions row
per variant — and it is the whole reason the writer aggregates to one value
per assembly class: a recipe that carried every surface could only ever be
re-applied to the model it came from.

Five rules, each the inverse of a writer rule:

**An absent field is left alone, never defaulted.** The writer omits what it
could not read; the reader must not invent it. Every application is reported
as applied or skipped, so a caller can see which half of the recipe reached
the model.

**A lossy aggregate stays lossy.** A field carrying a `spread_warning` is
applied as its single value AND the warning is re-emitted: averaging 76 walls
into one number does not become safe because the number is now being written.

**An unresolved system cannot be built.** A `resolved: false` zone group is
REFUSED by name rather than built from `family_guess`, which `classify.py`
states is a guess. This is the rule the writer exists to protect, and the
reader is where it would be broken.

**Scaling factors are not accepted.** The writer declares them unrecoverable,
so a recipe cannot ask for one; only the absolute form is applied.

**An untagged space type is applied and re-warned**, because a model built
from one fails NECB's space-type preflight gate — and the caller should learn
that here rather than from a refused compliance run.
"""

from __future__ import annotations

from btap._compat import sorted_by_name
from btap.modeling import loads as Loads
from btap.modeling import shw as Shw
from btap.modeling.envelope import constructions
from btap.modeling.hvac import efficiency as Efficiency
from btap.modeling.hvac import thermostats as Thermostats
from btap.modeling.hvac import ventilation as Ventilation
from btap.modeling.recipe.writer import SCHEMA


class RecipeError(ValueError):
    """A recipe that cannot be applied, with the reason."""


def _value(field):
    """The number out of an aggregate, or None when the field is absent.

    The writer wraps every aggregate as ``{'value': …, 'from': {…}}`` so the
    provenance travels with it. A bare number is accepted too, so a
    hand-authored recipe does not have to carry fake provenance.
    """
    if field is None:
        return None
    if isinstance(field, dict):
        return field.get('value')
    return float(field)


def _warn_if_lossy(field, label, audit, step='recipe'):
    if not isinstance(field, dict) or audit is None:
        return
    warning = field.get('from', {}).get('spread_warning')
    if warning:
        audit.warn(step,
                   f'{label} is applied from an aggregate that the recipe '
                   f'itself flags as lossy: {warning}',
                   inputs={'applied': field.get('value'),
                           'min': field.get('from', {}).get('min')
                           or field.get('from', {}).get('u_min'),
                           'max': field.get('from', {}).get('max')
                           or field.get('from', {}).get('u_max')})


def _apply_space_type_loads(space_type, entry, applied, skipped, audit):
    lighting = entry.get('lighting', {})
    lpd = _value(lighting.get('lighting_power_density_w_m2'))
    if lpd is not None:
        _warn_if_lossy(lighting['lighting_power_density_w_m2'],
                       f'{space_type.nameString()} lighting power density',
                       audit)
        Loads.set_lighting(
            space_type, watts_per_area_si=lpd,
            radiant=_value(lighting.get('lighting_fraction_radiant')),
            visible=_value(lighting.get('lighting_fraction_visible')),
            return_air_fraction=_value(
                lighting.get('lighting_return_air_fraction')),
            audit=audit)
        applied.append(f'{space_type.nameString()}: lighting')
    elif lighting:
        skipped.append(f'{space_type.nameString()}: lighting — no '
                       'Watts/Area density in the recipe')

    plugs = entry.get('plugs', {})
    plug_density = _value(plugs.get('plug_power_density_w_m2'))
    if plug_density is not None:
        _warn_if_lossy(plugs['plug_power_density_w_m2'],
                       f'{space_type.nameString()} plug density', audit)
        Loads.set_electric_equipment(
            space_type, watts_per_area_si=plug_density,
            radiant=_value(plugs.get('elec_equipment_fraction_radiant')),
            latent=_value(plugs.get('elec_equipment_fraction_latent')),
            lost=_value(plugs.get('elec_equipment_fraction_lost')),
            audit=audit)
        applied.append(f'{space_type.nameString()}: plugs')

    occupancy = entry.get('occupancy', {})
    for field, kwarg in (('occupancy_people_per_m2', 'people_per_area_si'),
                         ('occupancy_m2_per_person', 'area_per_person_si'),
                         ('occupancy_number_of_people', 'number_of_people')):
        value = _value(occupancy.get(field))
        if value is None:
            continue
        # The three are mutually exclusive, so the FIRST present wins and the
        # rest are skipped rather than overwriting each other — which is what
        # passing all three would do.
        Loads.set_people(
            space_type, audit=audit,
            fraction_radiant=_value(
                occupancy.get('occupancy_fraction_radiant')),
            **{kwarg: value})
        applied.append(f'{space_type.nameString()}: occupancy ({field})')
        break

    infiltration = entry.get('infiltration', {})
    for field, kwarg in (
            ('infiltration_air_changes_per_hour', 'air_changes_per_hour'),
            ('infiltration_flow_per_exterior_area_m3_per_s_m2',
             'per_exterior_area_si'),
            ('infiltration_flow_per_space_m3_per_s_m2', 'per_floor_area_si'),
            ('infiltration_flow_per_exterior_wall_area_m3_per_s_m2',
             'per_exterior_wall_area_si'),
            ('infiltration_design_flow_rate_m3_per_s', 'design_flow_rate_si')):
        value = _value(infiltration.get(field))
        if value is None:
            continue
        Loads.set_infiltration(space_type, audit=audit, **{kwarg: value})
        applied.append(f'{space_type.nameString()}: infiltration ({field})')
        break


def _apply_envelope(model, envelope, applied, skipped, audit):
    """Opaque and glazed assemblies, by surface class.

    Each surface's construction is replaced with one at the recipe's
    conductance, through `opaque_at_conductance` /
    `fenestration_at_conductance`, which already reuse by name so one
    conductance produces one construction rather than one per surface.
    """
    import openstudio

    from btap._compat import opt
    from btap.modeling.recipe.envelope import film_class

    for key, field in sorted(envelope.get('opaque', {}).items()):
        if field is None:
            continue
        surface_type, boundary = key.split(':', 1)
        u = field.get('u_si')
        if u is None:
            skipped.append(f'{key}: no u_si')
            continue
        _warn_if_lossy({'value': u, 'from': field.get('from', {})},
                       f'{key} U-value', audit)
        films = constructions.film_r(film_class(surface_type),
                                     boundary.lower())
        # The recipe's U INCLUDES air films; a construction's conductance
        # excludes them, so the films come back off before it is applied.
        # Writing the U straight through would make every assembly worse than
        # the recipe says by exactly the film resistance.
        if 1.0 / u - films <= 0:
            skipped.append(
                f'{key}: U {u} is higher than the film resistance alone '
                f'({round(1.0 / films, 3) if films else "inf"}), so no '
                'assembly can achieve it')
            continue
        conductance = 1.0 / (1.0 / u - films)
        count = 0
        for surface in sorted_by_name(model.getSurfaces()):
            if (surface.surfaceType() != surface_type
                    or surface.outsideBoundaryCondition() != boundary):
                continue
            existing = opt(surface.construction())
            if existing is None:
                skipped.append(f'{surface.nameString()}: no construction to '
                               'base an assembly on')
                continue
            replacement = constructions.opaque_at_conductance(
                model, existing, conductance)
            surface.setConstruction(replacement)
            count += 1
        if count:
            applied.append(f'{key}: U {u} on {count} surface(s)')

    for key, field in sorted(envelope.get('fenestration', {}).items()):
        if field is None:
            continue
        sub_type, boundary = key.split(':', 1)
        u = field.get('u_si')
        if u is None:
            skipped.append(f'{key}: no u_si')
            continue
        _warn_if_lossy({'value': u, 'from': field.get('from', {})},
                       f'{key} U-value', audit)
        count = 0
        for sub in sorted_by_name(model.getSubSurfaces()):
            if sub.subSurfaceType() != sub_type:
                continue
            surface = opt(sub.surface())
            if (surface is None
                    or surface.outsideBoundaryCondition() != boundary):
                continue
            existing = opt(sub.construction())
            if existing is None:
                skipped.append(f'{sub.nameString()}: no construction')
                continue
            # A fenestration U IS the overall U, so it goes through as given.
            replacement = constructions.fenestration_at_conductance(
                model, existing, u)
            sub.setConstruction(replacement)
            count += 1
        if count:
            applied.append(f'{key}: U {u} on {count} sub-surface(s)')
    del openstudio


def _apply_controls(model, controls, applied, skipped, audit):
    thermostats = controls.get('thermostats', {})
    for which, kwarg in (('heating', 'heating'), ('cooling', 'cooling')):
        profile = thermostats.get(f'{which}_setpoint')
        if not profile:
            continue
        if 'constant_c' in profile:
            value = profile['constant_c']
        elif 'occupied_c' in profile and 'setback_c' in profile:
            value = Thermostats.setback_schedule(
                model, f'Recipe {which.title()} Setback',
                occupied_c=profile['occupied_c'],
                setback_c=profile['setback_c'],
                occupied_from_hour=0,
                occupied_to_hour=int(profile.get('occupied_until_hour') or 24))
        else:
            skipped.append(f'{which} setpoint: profile has neither a constant '
                           'nor an occupied/setback pair')
            continue
        count = Thermostats.set_thermostats_in_model(
            model, audit=audit, **{kwarg: value})
        applied.append(f'{which} setpoint on {count} zone(s)')

    economizers = controls.get('economizers') or {}
    rows = economizers.get('by_air_loop') or []
    if rows:
        control_type = rows[0]['economizer_control_type']
        count = Ventilation.set_economizer_in_model(
            model, control_type=control_type, audit=audit)
        applied.append(f'economizer {control_type} on {count} loop(s)')
        if any(row.get('dcv_enabled') for row in rows):
            for air_loop in sorted_by_name(model.getAirLoopHVACs()):
                Ventilation.set_demand_controlled_ventilation(
                    air_loop, audit=audit)
            applied.append('demand-controlled ventilation')

    daylighting = controls.get('daylighting') or {}
    if daylighting.get('controls'):
        skipped.append(
            f"{len(daylighting['controls'])} daylighting control(s): a "
            'sensor position is specific to the geometry it was read from, '
            'so it is not transferable to different geometry')


def _apply_equipment(model, equipment, applied, skipped, audit):
    fans = equipment.get('fans', {})
    total = _value(fans.get('fan_total_eff'))
    motor = _value(fans.get('fan_motor_eff'))
    if total is not None or motor is not None:
        _warn_if_lossy(fans.get('fan_total_eff'), 'fan total efficiency',
                       audit)
        written = Efficiency.set_fan_efficiency_in_model(
            model, total_efficiency=total, motor_efficiency=motor,
            audit=audit)
        applied.append(f'fan efficiency, {written} field(s)')

    pumps = equipment.get('pumps', {})
    pump_motor = _value(pumps.get('pump_motor_eff'))
    if pump_motor is not None:
        written = Efficiency.set_pump_efficiency_in_model(
            model, motor_efficiency=pump_motor, audit=audit)
        applied.append(f'pump motor efficiency on {written} pump(s)')

    heaters = equipment.get('water_heaters', {})
    efficiency = _value(heaters.get('shw_thermal_eff'))
    ua = _value(heaters.get('shw_off_cycle_ua_w_per_k'))
    for heater in sorted_by_name(model.getWaterHeaterMixeds()):
        if efficiency is not None:
            Shw.set_water_heater_efficiency(
                heater, thermal_efficiency=efficiency, audit=audit)
        if ua is not None:
            Shw.set_water_heater_losses(heater, ua_w_per_k=ua, audit=audit)
    stratified = model.getWaterHeaterStratifieds()
    for heater in sorted_by_name(stratified):
        if efficiency is not None:
            Shw.set_water_heater_efficiency(
                heater, thermal_efficiency=efficiency, audit=audit)
    if efficiency is not None or ua is not None:
        applied.append('water heater performance')
    if stratified and ua is not None:
        skipped.append(
            f'{len(stratified)} stratified tank(s): the recipe carries a '
            'mixed-tank W/K UA, which is not the quantity their flue and '
            'per-unit-area skin losses hold')


def _build_hvac(model, groups, applied, refused, audit):
    """Build HVAC from ACCEPTED candidates, auditing each as a candidate.

    Reached only when the caller passes `accept_candidates=True`. A group with
    no candidate is still refused: accepting candidates does not mean
    inventing one where the identifier proposed none.

    `build_system(..., remove_existing=True)` tears down whatever serves those
    zones first, which is what makes this a GENERATION rather than an overlay.
    The earlier simulation comparison was an overlay — the original HVAC was
    inherited untouched — and that is why its -2.53% described only the 14% of
    site energy the recipe actually rebuilt.
    """
    from btap.modeling.hvac import builder

    for group in groups:
        candidates = group.get('candidates') or []
        zone_names = group.get('zones') or []
        if not candidates:
            refused.append(
                f'HVAC for {len(zone_names)} zone(s): no candidate to accept '
                '— the identifier proposed none, and accepting candidates '
                'does not mean inventing one')
            continue
        chosen = candidates[0]
        zones = [z for z in sorted_by_name(model.getThermalZones())
                 if z.nameString() in set(zone_names)]
        if not zones:
            refused.append(
                f"HVAC {chosen['system']!r}: none of its "
                f'{len(zone_names)} zone(s) exist in this geometry')
            continue
        try:
            builder.build_system(model, chosen['system'],
                                 [z for z in zones], remove_existing=True)
        except Exception as exc:
            refused.append(
                f"HVAC {chosen['system']!r} on {len(zones)} zone(s): the "
                f'builder refused it — {type(exc).__name__}: {exc}')
            continue
        applied.append(
            f"HVAC {chosen['system']!r} (CANDIDATE, score "
            f"{chosen['score']}) on {len(zones)} zone(s)")
        if audit is not None:
            audit.warn('recipe',
                       'HVAC built from a CANDIDATE, not an identified '
                       'system — the recipe reported no catalogue system for '
                       'these zones and this is a ranked guess',
                       target=chosen['system'],
                       inputs={'score': chosen['score'],
                               'family': chosen.get('family'),
                               'origin': chosen.get('origin'),
                               'zones': len(zones),
                               'matched': chosen.get('matched', [])[:4],
                               'against': chosen.get('against', [])})


def build_from_recipe(recipe, model, *, accept_candidates=False, audit=None):
    """Apply ``recipe`` to ``model``, which supplies the geometry.

    :returns: ``{'applied': [...], 'skipped': [...], 'refused': [...]}`` —
        a per-field account, because a caller has to be able to see which half
        of a recipe reached the model.
    :param accept_candidates: build HVAC from each unresolved group's TOP
        ranked candidate instead of refusing it. OFF by default: a candidate
        is a guess, `classify.py` establishes that structural identification
        cannot be made reliable, and a caller has to say so deliberately.
        Every system built this way is audited as a candidate, with its score
        and the facts that went AGAINST it.
    :raises RecipeError: on an unknown schema.
    """
    schema = recipe.get('schema')
    if schema != SCHEMA:
        raise RecipeError(
            f'recipe schema {schema!r} is not {SCHEMA} — refusing rather than '
            'guessing which fields moved')

    applied, skipped, refused = [], [], []

    for field in recipe.get('loads', {}).get('not_recoverable', []):
        if field.get('field') in recipe.get('loads', {}):
            refused.append(f"{field['field']}: declared unrecoverable by the "
                           'writer, so it may not be applied')

    space_types = {st.nameString(): st
                   for st in sorted_by_name(model.getSpaceTypes())}
    for name, entry in sorted(recipe.get('loads', {})
                              .get('by_space_type', {}).items()):
        space_type = space_types.get(name)
        if space_type is None:
            skipped.append(f'{name}: no such space type in the geometry')
            continue
        _apply_space_type_loads(space_type, entry, applied, skipped, audit)

    _apply_envelope(model, recipe.get('envelope', {}), applied, skipped, audit)
    _apply_controls(model, recipe.get('controls', {}), applied, skipped, audit)
    _apply_equipment(model, recipe.get('equipment', {}), applied, skipped,
                     audit)

    unresolved = [group for group in recipe.get('hvac', {})
                  .get('zone_groups', []) if not group.get('resolved')]
    if accept_candidates:
        _build_hvac(model, unresolved, applied, refused, audit)
    else:
        for group in unresolved:
            refused.append(
                f"HVAC for {len(group.get('zones', []))} zone(s) "
                f"({', '.join(group.get('zones', [])[:3])}…): the recipe "
                'reports no catalogue system, and family_guess is a guess — '
                'building from it would produce a system the source model is '
                'not. Pass accept_candidates=True to build from the ranked '
                'candidate instead.')

    untagged = (recipe.get('space_types', {}).get('from', {})
                .get('untagged_space_types', 0))
    if untagged and audit is not None:
        audit.warn('recipe',
                   f'{untagged} space type(s) in this recipe carry no '
                   'standards building/space type — a model built from it '
                   'will fail an NECB space-type preflight gate',
                   inputs={'untagged_space_types': untagged})

    if audit is not None:
        audit.info('recipe', 'recipe applied',
                   inputs={'applied': len(applied), 'skipped': len(skipped),
                           'refused': len(refused)})
    return {'applied': applied, 'skipped': skipped, 'refused': refused}
