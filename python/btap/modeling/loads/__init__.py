"""Space-type load primitives: infiltration, plug loads, lighting fractions.

**Code-family-neutral by construction.** Nothing here knows what NECB is, and
nothing here holds a value. Every function takes CONCRETE SI quantities and
applies them; deciding what a 1972 Ottawa office's infiltration should be is
the caller's business.

These were lifted out of `btap.codes.necb.loads.apply` and
`btap.codes.necb.lighting.apply_lights` for issue #183's phase 0. Before the
lift they existed ONLY inside the NECB appliers, so a model authored through
`btap.modeling` alone could not set infiltration, plug loads or lighting
fractions at all — and for stock and retrofit work on a pre-1960 building,
infiltration is arguably the dominant difference from a 2005 one.

The NECB appliers now read their record, convert to SI, and call down here.
That direction is what D-77 allows: `codes` imports `modeling`, never the
reverse.

**Units are SI**, the SDK's own. The NECB tables are in IP
(ft^3/min*ft^2) and the conversion stays on the NECB side, so this module
carries none of that convention.
"""

from __future__ import annotations

from btap._compat import opt

# NO module-level `import openstudio`. `btap.modeling` has none — three
# inside-function imports instead — because the package must import on a bare
# runner: the zero-install lane (`python3 -m unittest`) has no SDK, and
# `@needs_sdk` can only SKIP a test whose module already imported. A
# module-level import here made `tests.modeling.test_load_primitives`
# unimportable rather than skipped, and the bare lane failed with
# `ModuleNotFoundError: No module named 'openstudio'`.


def single_instance(instances, create, audit=None, step='loads'):
    """The first of ``instances``, removing any duplicates, or ``create()``.

    Ruby's block form, lifted verbatim in behaviour from
    `codes/necb/loads/apply.py::_single_instance`: a space type carrying two
    infiltration objects is a model defect either way, and silently using one
    of them would make the applied value depend on object order.
    """
    instances = sorted(instances)
    if not instances:
        return create()
    for extra in instances[1:]:
        if audit is not None:
            audit.info(step,
                       f"removed duplicate load instance {extra.nameString()}")
        extra.remove()
    return instances[0]


def unshared_definition(instance, *, audit=None, step='loads'):
    """The instance's definition, SPLIT first if any other instance shares it.

    Setting a value on a shared definition changes every instance using it,
    and a caller naming one space type did not ask for that. Measured:
    `set_lighting(type_0, watts_per_area_si=25.0)` on a definition shared with
    `type_1` left `type_1` reading 25.0 too.

    Structural to all ELEVEN `SpaceLoadDefinition` subclasses and already in
    the corpus — 4 of the 28 hand-built campus archetypes share one, and all
    three `Hangar` vintages share a `LightsDefinition`, an
    `ElectricEquipmentDefinition` AND a `PeopleDefinition` between the
    `Shop-Machinery` and `Shop-Machinery-Hangar` space types (#186).

    **The split is the SDK's own operation.** `SpaceLoadInstance::makeUnique()`
    is documented as "ensures that no other instances share this instances
    definition", and measured: shared by three, `L0.makeUnique()` gives L0 a
    clone carrying the value while L1 and L2 keep the original, and it is a
    NO-OP when the instance is already unique. Nothing but that instance's own
    object can hold the definition — the OpenStudio 3.11 IDD shows
    `OS:Lights:Definition` and its siblings referenced ONLY by their instance
    object — so once `instances()` is down to one, mutating it is sound.

    **There is deliberately NO reuse-by-name here, and the first version of
    this function had it.** The idea was to keep the object count proportional
    to distinct VALUES: name a clone after its value, and let the next sharer
    needing the same value adopt it instead of cloning again. It re-created
    #186 one object down. The key encoded only the primary density, so
    everything else a setter writes — calculation METHOD, the heat-split
    fractions, a construction — was outside the key, and the reuse branch
    returned a definition OTHER instances were already using and then wrote
    those unmatched fields into it:

        set_lighting(T0, watts_per_area_si=25.0, radiant=0.3)
        set_lighting(T1, watts_per_area_si=25.0, radiant=0.7)
            -> T0 silently reads radiant 0.7

        set_lighting(T0, watts_per_area_si=10.0)
        set_lighting(T1, watts_per_person=10.0)
            -> both round to 'W-10.0', T1 adopts T0's clone and switches the
               method, and T0's watts-per-area reads None

    `opaque_at_conductance` reuses by name safely because it RETURNS the
    construction and writes nothing afterwards. This function returns an
    object its caller is about to write into, which is a different contract
    and cannot take the same shortcut. A second collision came free: two
    different shared originals whose names differ only after the last colon
    (`Bldg:Core`, `Bldg:Perim`) truncated to the same base and collapsed onto
    one object.

    So this function does ONE thing. The price is object count: fifty space
    types sharing one definition and all written produce fifty definitions,
    which is semantically right — each instance owns its values — and larger
    than it needs to be. Shrinking it belongs in a separate pass that merges
    definitions which are field-for-field identical, AFTER the writes, where
    equality is measured rather than inferred from a name (#189).

    The clone is named after the INSTANCE, so the name identifies whose
    definition it is and claims nothing about its contents. An earlier version
    named it after the value, which produced labels like `...:W-0.0` on a
    definition whose density was an inherited non-zero.

    **An UNSHARED definition is never renamed.** The NECB appliers call these
    setters, their definitions are already unique and carefully named, and
    renaming them would move every frozen baseline for no behavioural reason.

    :returns: a definition no other instance shares, safe to mutate.
    """
    definition = instance.definition()
    sharers = definition.instances()
    if len(sharers) <= 1:
        return definition

    was = definition.nameString()
    instance.makeUnique()
    split = instance.definition()
    split.setName(f"{instance.nameString()} Definition")
    if audit is not None:
        audit.info(step,
                   'load definition split — it was shared, and setting it '
                   'would have changed every instance using it',
                   target=instance.nameString(),
                   inputs={'was': was, 'now': split.nameString(),
                           'sharers_before': len(sharers)})
    return split


def _definition_fingerprint(definition):
    """Every field of ``definition`` but its Handle and Name, with its type.

    The exclusion is DERIVED from the IDD rather than positional: measured on
    OpenStudio 3.11, `LightsDefinition`, `PeopleDefinition`,
    `InternalMassDefinition` and `ElectricEquipmentDefinition` all name field 0
    `Handle` and field 1 `Name`, and reading those names means the function
    does not break if a type ever orders them differently.

    `idfObject().fieldComment(i)` is NOT usable for this — it returns an empty
    optional on a constructed object, so filtering on it excludes nothing and
    every fingerprint silently includes the handle, which makes every
    definition unique. That was the first version.

    Object REFERENCES are compared by handle, so two definitions pointing at
    different schedule or construction objects are different even if those
    objects are themselves identical. Conservative in the safe direction: a
    merge that should not happen is worse than one that is missed.
    """
    idf = definition.idfObject()
    idd = idf.iddObject()
    fields = []
    for index in range(idf.numFields()):
        field = opt(idd.getField(index))
        if field is not None and field.name() in ('Handle', 'Name'):
            continue
        fields.append(opt(idf.getString(index)) or '')
    return (definition.iddObjectType().valueName(), tuple(fields))


def deduplicate_definitions(model, *, audit=None, step='loads'):
    """Merge load definitions that are field-for-field identical.

    The companion to `unshared_definition`, and phylroy's design
    (2026-11-03): copy on write, then find the duplicates, keep one of each
    and reassign. It is what makes splitting affordable — fifty space types
    written to the same values become fifty definitions on the way through and
    one on the way out.

    **Why this is safe where reuse-by-name was not.** Reuse inferred equality
    from a NAME, BEFORE the writes, so fields outside the key were never
    compared and the merged object diverged afterwards — a caller's radiant
    fraction landing on another space type's definition. This measures every
    field AFTER the writes. Nothing can diverge later because there is no
    later.

    **Which is also its precondition: run it after the per-instance writes are
    finished.** Merge first and write afterwards and you have rebuilt exactly
    the defect, because the write lands on a definition other instances now
    share. That is a contract a caller can keep; the name key had no safe
    version at all.

    Definitions with no instances are left alone rather than merged or
    removed: an orphan is not this function's business, and deleting objects a
    caller may still hold is not a deduplication.

    :returns: the number of definitions removed.
    """
    collections = (
        ('Lights', model.getLightsDefinitions),
        ('ElectricEquipment', model.getElectricEquipmentDefinitions),
        ('GasEquipment', model.getGasEquipmentDefinitions),
        ('People', model.getPeopleDefinitions),
        ('InternalMass', model.getInternalMassDefinitions),
    )
    removed = 0
    for label, getter in collections:
        groups = {}
        for definition in getter():
            if not definition.instances():
                continue
            groups.setdefault(_definition_fingerprint(definition),
                              []).append(definition)
        for duplicates in groups.values():
            if len(duplicates) < 2:
                continue
            keeper, rest = duplicates[0], duplicates[1:]
            moved = 0
            for spare in rest:
                for instance in list(spare.instances()):
                    instance.setDefinition(keeper)
                    moved += 1
                spare.remove()
                removed += 1
            if audit is not None:
                audit.info(step,
                           f'{len(rest) + 1} identical {label} definitions '
                           'merged into one',
                           target=keeper.nameString(),
                           inputs={'removed': len(rest),
                                   'instances_reassigned': moved})
    return removed


def set_infiltration(space_type, *, design_flow_rate_si=None,
                     per_floor_area_si=None, per_exterior_area_si=None,
                     per_exterior_wall_area_si=None,
                     air_changes_per_hour=None, schedule=None, audit=None,
                     step='loads'):
    """Set space-type modelling infiltration, in SI, on ``space_type``.

    This is the SPACE-TYPE modelling quantity, not an envelope air-leakage
    rule — NECB keeps those in different domains (8.4.3.3 is the envelope
    one) and conflating them was worth a distinct name here.

    Every quantity is optional and only a non-``None``, non-zero value is
    applied, which preserves the NECB applier's behaviour: a record whose
    three infiltration columns are all zero leaves the model untouched rather
    than writing zeros.

    All FIVE of the SDK's calculation methods are reachable — the first draft
    offered three, and osruby's `ecm_infiltration` names
    `infiltration_design_flow_rate` and `infiltration_flow_per_space` as well,
    so a stock author needs them.

    :param design_flow_rate_si: m^3/s for the whole space (`Flow/Space`)
    :param per_floor_area_si: m^3/s per m^2 of floor (`Flow/Area`)
    :param per_exterior_area_si: m^3/s per m^2 of exterior surface
    :param per_exterior_wall_area_si: m^3/s per m^2 of exterior wall
    :param air_changes_per_hour: ACH, dimensionless
    :param schedule: an OpenStudio ``Schedule``, or None to leave it alone.
        A SCHEDULE OBJECT, not a name: resolving a name belongs to whoever
        owns the schedule library, which for NECB is
        `codes.necb.loads.schedules` and for stock work is the caller.
    :returns: the ``SpaceInfiltrationDesignFlowRate`` applied to, or None when
        every quantity was absent or zero.
    """
    import openstudio

    given = {'design_flow_rate_si': design_flow_rate_si,
             'per_floor_area_si': per_floor_area_si,
             'per_exterior_area_si': per_exterior_area_si,
             'per_exterior_wall_area_si': per_exterior_wall_area_si,
             'air_changes_per_hour': air_changes_per_hour}
    given = {k: v for k, v in given.items() if v}
    if not given:
        return None
    # The three are MUTUALLY EXCLUSIVE calculation methods, measured on
    # OpenStudio 3.11: each setter switches `designFlowRateCalculationMethod`
    # and CLEARS the other two, so applying several silently keeps only the
    # last. Refusing is the only honest option — a caller who passes two has a
    # misconception, and letting the last win would hide it in a model nobody
    # re-reads.
    #
    # The NECB applier has the same shape and is correct by DATA rather than by
    # design: 0 of 308 space-type rows in either edition sets more than one
    # infiltration column. This guard is what keeps that true if a row ever
    # gains a second.
    if len(given) > 1:
        raise ValueError(
            'SpaceInfiltrationDesignFlowRate carries ONE calculation method: '
            f"got {sorted(given)}. Each setter clears the others, so only "
            'the last would survive. Pass exactly one.')

    def create():
        infiltration = openstudio.model.SpaceInfiltrationDesignFlowRate(
            space_type.model())
        infiltration.setName(f"{space_type.nameString()} Infiltration")
        infiltration.setSpaceType(space_type)
        return infiltration

    instance = single_instance(
        space_type.spaceInfiltrationDesignFlowRates(), create, audit=audit,
        step=step)
    if design_flow_rate_si:
        instance.setDesignFlowRate(design_flow_rate_si)
    elif per_floor_area_si:
        instance.setFlowperSpaceFloorArea(per_floor_area_si)
    elif per_exterior_area_si:
        instance.setFlowperExteriorSurfaceArea(per_exterior_area_si)
    elif per_exterior_wall_area_si:
        instance.setFlowperExteriorWallArea(per_exterior_wall_area_si)
    elif air_changes_per_hour:
        instance.setAirChangesperHour(air_changes_per_hour)
    if schedule is not None:
        instance.setSchedule(schedule)
    return instance


def set_load_fractions(definition, *, latent=None, radiant=None, lost=None):
    """Latent / radiant / lost fractions on an equipment or lights definition.

    Only a non-``None``, non-zero fraction is applied, which is the NECB
    applier's behaviour: a zero in the table means "leave the SDK default"
    rather than "set zero". That distinction is load-bearing — the SDK's own
    defaults are not all zero.
    """
    if latent:
        definition.setFractionLatent(latent)
    if radiant:
        definition.setFractionRadiant(radiant)
    if lost:
        definition.setFractionLost(lost)


def set_electric_equipment(space_type, *, watts_per_area_si, latent=None,
                           radiant=None, lost=None, audit=None, step='loads'):
    """Plug load in W/m^2 of space floor area, with its heat-split fractions.

    :param watts_per_area_si: W/m^2. The NECB tables are W/ft^2 and that
        conversion stays on the NECB side.
    :returns: the ``ElectricEquipment`` applied to, or None for a zero load.
    """
    import openstudio

    if not watts_per_area_si:
        return None

    def create():
        definition = openstudio.model.ElectricEquipmentDefinition(
            space_type.model())
        definition.setName(f"{space_type.nameString()} Elec Equip Definition")
        equip = openstudio.model.ElectricEquipment(definition)
        equip.setName(f"{space_type.nameString()} Elec Equip")
        equip.setSpaceType(space_type)
        return equip

    instance = single_instance(space_type.electricEquipment(), create,
                               audit=audit, step=step)
    definition = opt(unshared_definition(
        instance, audit=audit, step=step).to_ElectricEquipmentDefinition())
    definition.setWattsperSpaceFloorArea(watts_per_area_si)
    set_load_fractions(definition, latent=latent, radiant=radiant, lost=lost)
    return instance


def set_gas_equipment(space_type, *, watts_per_area_si, latent=None,
                      radiant=None, lost=None, audit=None, step='loads'):
    """Gas equipment in W/m^2 of space floor area, with its fractions.

    SI like its electric sibling, so both read the same way here. The NECB
    table is Btu/hr*ft^2 and converts on the NECB side.

    :returns: the ``GasEquipment`` applied to, or None for a zero load.
    """
    import openstudio

    if not watts_per_area_si:
        return None

    def create():
        definition = openstudio.model.GasEquipmentDefinition(
            space_type.model())
        definition.setName(f"{space_type.nameString()} Gas Equip Definition")
        equip = openstudio.model.GasEquipment(definition)
        equip.setName(f"{space_type.nameString()} Gas Equip")
        equip.setSpaceType(space_type)
        return equip

    instance = single_instance(space_type.gasEquipment(), create, audit=audit,
                               step=step)
    definition = opt(unshared_definition(
        instance, audit=audit, step=step).to_GasEquipmentDefinition())
    definition.setWattsperSpaceFloorArea(watts_per_area_si)
    set_load_fractions(definition, latent=latent, radiant=radiant, lost=lost)
    return instance


def set_lighting(space_type, *, watts_per_area_si=None,
                 watts_per_person=None, return_air_fraction=None,
                 radiant=None, visible=None, name=None, audit=None,
                 step='loads'):
    """Lighting power and its heat-split fractions on ``space_type``.

    The NARROWEST of the three lifted primitives, deliberately. The NECB
    applier's lighting path is far more than this — an LED-vs-fluorescent
    branch, `_led_lpd_w_ft2`, a scaling factor, a space-type catalogue lookup
    and a schedule synthesis — and none of that is liftable, because all of it
    is the Code deciding what the power density should BE. What a stock author
    needs is the other half: create the Lights, attach them, and set a density
    and its fractions.

    So this creates a `Lights` + `LightsDefinition` pair if the space type has
    none, reuses the existing one if it does, and sets only what it is given.

    :param watts_per_area_si: W/m^2 of floor area. NECB's tables are W/ft^2
        and that conversion stays on the NECB side.
    :param watts_per_person: W per person, applied as given.
    :param return_air_fraction: `setReturnAirFraction`
    :param radiant: `setFractionRadiant`
    :param visible: `setFractionVisible`
    :param name: a name for a newly created pair; defaults to the space type's
        name plus " Lights".
    :returns: the ``Lights`` applied to, or None when given nothing to set.
    """
    import openstudio

    if not any(v for v in (watts_per_area_si, watts_per_person,
                           return_air_fraction, radiant, visible)
               if v is not None):
        return None

    # `Watts/Area` and `Watts/Person` are mutually exclusive, by the same
    # measurement: `setWattsperPerson` switches `designLevelCalculationMethod`
    # and clears the area value. REFUSE BEFORE TOUCHING THE MODEL — an earlier
    # version raised after `single_instance` and `unshared_definition` had
    # already run, so a refused call left a new instance, a split definition
    # and a split audit entry behind, while `set_people` and
    # `set_internal_mass` raised cleanly.
    if watts_per_area_si and watts_per_person:
        raise ValueError(
            'LightsDefinition carries ONE design-level calculation method: '
            'watts_per_area_si and watts_per_person are exclusive, and the '
            'second would clear the first. Pass one.')

    base = name or f"{space_type.nameString()} Lights"

    def create():
        definition = openstudio.model.LightsDefinition(space_type.model())
        definition.setName(f"{base} Definition")
        lights = openstudio.model.Lights(definition)
        lights.setName(base)
        lights.setSpaceType(space_type)
        return lights

    instance = single_instance(space_type.lights(), create, audit=audit,
                               step=step)
    definition = opt(unshared_definition(
        instance, audit=audit, step=step).to_LightsDefinition())
    if watts_per_area_si:
        definition.setWattsperSpaceFloorArea(watts_per_area_si)
    elif watts_per_person:
        definition.setWattsperPerson(watts_per_person)
    # Skip-on-zero, as `apply_lights._set_fraction` does: a zero in the table
    # means "leave the SDK default", and the SDK's defaults are not all zero.
    if return_air_fraction:
        definition.setReturnAirFraction(return_air_fraction)
    if radiant:
        definition.setFractionRadiant(radiant)
    if visible:
        definition.setFractionVisible(visible)
    return instance


def _scale_definitions(instances, read_definition, audit, step, factor, kind):
    """Scale each DISTINCT definition once, by handle.

    Several load instances can SHARE one definition, and scaling per instance
    then applies the factor once per sharer. Measured: two `Lights` on one
    `LightsDefinition` at 10 W/m^2, scaled x2 by a naive per-instance loop,
    come out at 40 W/m^2 rather than 20.

    FOUR of the 28 hand-built campus archetypes share one today, which an
    earlier version of this docstring denied on the strength of three
    Office-Small models: `FireHall_pre-1960` shares a `PeopleDefinition`, and
    all three `Hangar` vintages share a `LightsDefinition`, an
    `ElectricEquipmentDefinition` AND a `PeopleDefinition` between the
    `Shop-Machinery` and `Shop-Machinery-Hangar` space types.

    So sharing across space types is not hypothetical — it is how a library
    construction set or a copied space type ends up wired, and it is already
    in the corpus.

    Only a `Watts/Area` density is scaled. A definition using another
    calculation method is left alone and reported, rather than silently
    converted to a method the caller did not choose.
    """
    seen, scaled = set(), 0
    for instance in instances:
        definition = read_definition(instance)
        handle = str(definition.handle())
        if handle in seen:
            continue
        seen.add(handle)
        watts = definition.wattsperSpaceFloorArea()
        if not watts.is_initialized():
            if audit is not None:
                audit.info(step,
                           f"{kind} not scaled — its density is "
                           f"{definition.designLevelCalculationMethod()}, not "
                           'Watts/Area',
                           target=definition.nameString())
            continue
        definition.setWattsperSpaceFloorArea(watts.get() * factor)
        scaled += 1
    return scaled


def scale_electric_equipment(space_type, *, factor, audit=None, step='loads'):
    """Multiply every electric-equipment density on ``space_type`` by ``factor``.

    SETTING and SCALING are separate functions on purpose. They are different
    operations — a write versus a read-modify-write — and a single function
    taking both an absolute value and a factor has to decide what it means when
    given both, which is a question with no good answer. osruby made the same
    split: `ScaleLoads::scale_electrical_loads` beside the absolute setters,
    driven by its `elec_equipment_scaling_factor` column.

    Scaling is what stock and retrofit work usually wants: "this 1970s wing
    carries 1.3x the baseline plug load" is a claim about a RATIO, and it
    survives a later change to the baseline where a hard-coded W/m^2 would not.

    Only a `Watts/Area` density is scaled, because that is the method the
    appliers write. A definition using `EquipmentLevel` or `Watts/Person` is
    left alone and reported, rather than silently converted to a method the
    caller did not ask for.

    :param factor: multiplier; 1.0 is a no-op and is allowed.
    :returns: the number of definitions scaled.
    """
    if factor is None:
        return 0
    return _scale_definitions(
        space_type.electricEquipment(),
        lambda equip: equip.electricEquipmentDefinition(),
        audit, step, factor, 'electric equipment')


def scale_lighting(space_type, *, factor, audit=None, step='loads'):
    """Multiply every lighting density on ``space_type`` by ``factor``.

    The counterpart to `scale_electric_equipment`, and the same reasoning:
    osruby's `lighting_scaling_factor` column through
    `ScaleLoads::scale_lighting_loads`. The NECB lighting applier already has
    this concept internally as `lights_scale`.

    Only a `Watts/Area` density is scaled; `LightingLevel` and `Watts/Person`
    definitions are left alone and reported.

    :returns: the number of definitions scaled.
    """
    if factor is None:
        return 0
    return _scale_definitions(
        space_type.lights(), lambda lights: lights.lightsDefinition(),
        audit, step, factor, 'lighting')


def scale_lighting_in_model(model, *, factor, audit=None, step='loads'):
    """Scale every lighting density in ``model``, wherever the Lights hang.

    The model-wide form phylroy asked for: apply to everything that ALREADY
    has lighting, rather than per space type. `Lights` can attach to a
    `Space` or to a `SpaceType`, and this reaches both because it walks
    `model.getLightss()`.

    It does NOT create lighting where there is none — "all spaces that had
    lighting" is the question, and a space with no Lights object is left
    alone rather than given a density it never had.

    Deduplicating by DEFINITION is what makes this safe: sharing across space
    types is the natural result of a library construction set or a copied
    space type, and a per-instance loop would apply the factor once per
    sharer. See `_scale_definitions`.

    :returns: the number of distinct definitions scaled.
    """
    if factor is None:
        return 0
    return _scale_definitions(
        model.getLightss(), lambda lights: lights.lightsDefinition(),
        audit, step, factor, 'lighting')


def scale_electric_equipment_in_model(model, *, factor, audit=None,
                                      step='loads'):
    """Scale every electric-equipment density in ``model``.

    The counterpart to `scale_lighting_in_model`, same reasoning and the same
    per-definition deduplication.

    :returns: the number of distinct definitions scaled.
    """
    if factor is None:
        return 0
    return _scale_definitions(
        model.getElectricEquipments(),
        lambda equip: equip.electricEquipmentDefinition(),
        audit, step, factor, 'electric equipment')


def set_people(space_type, *, people_per_area_si=None, number_of_people=None,
               area_per_person_si=None, fraction_radiant=None, audit=None,
               step='loads'):
    """Occupant density on ``space_type``, by one of three methods.

    Lifted for #186: the `Hangar` archetypes share a `PeopleDefinition`
    between `Shop-Machinery` and `Shop-Machinery-Hangar`, so People was
    already implicated in the shared-definition defect before it had a
    primitive of its own.

    The three methods are MUTUALLY EXCLUSIVE, like infiltration's five and
    lighting's two: `PeopleDefinition` carries one
    `numberofPeopleCalculationMethod`, and each setter switches it. Passing
    more than one is refused rather than letting the last silently win.

    :param people_per_area_si: people per m^2 (`People/Area`). NECB's table is
        people per 1000 ft^2 and that conversion stays on the NECB side.
    :param number_of_people: an absolute count (`People`)
    :param area_per_person_si: m^2 per person (`Area/Person`)
    :param fraction_radiant: applied when given; NECB uses 0.3
    :returns: the ``People`` applied to, or None when given no density.
    """
    import openstudio

    given = {'people_per_area_si': people_per_area_si,
             'number_of_people': number_of_people,
             'area_per_person_si': area_per_person_si}
    given = {k: v for k, v in given.items() if v}
    if not given:
        return None
    if len(given) > 1:
        raise ValueError(
            'PeopleDefinition carries ONE numberofPeopleCalculationMethod: '
            f"got {sorted(given)}. Each setter clears the others, so only the "
            'last would survive. Pass exactly one.')

    base = f"{space_type.nameString()} People"

    def create():
        definition = openstudio.model.PeopleDefinition(space_type.model())
        definition.setName(f"{base} Definition")
        people = openstudio.model.People(definition)
        people.setName(base)
        people.setSpaceType(space_type)
        return people

    instance = single_instance(space_type.people(), create, audit=audit,
                               step=step)
    definition = opt(unshared_definition(
        instance, audit=audit, step=step).to_PeopleDefinition())
    if people_per_area_si:
        definition.setPeopleperSpaceFloorArea(people_per_area_si)
    elif number_of_people:
        definition.setNumberofPeople(number_of_people)
    elif area_per_person_si:
        definition.setSpaceFloorAreaperPerson(area_per_person_si)
    if fraction_radiant:
        definition.setFractionRadiant(fraction_radiant)
    return instance


def set_internal_mass(space_type, *, surface_area_si=None,
                      per_floor_area_si=None, per_person_si=None,
                      construction=None, audit=None, step='loads'):
    """Internal thermal mass on ``space_type``, by one of three methods.

    phylroy asked for this alongside People (2026-11-03). It matters more for
    stock work than for compliance: thermal mass is a large part of why a
    1940s masonry building behaves unlike a 2005 one, and NECB does not
    prescribe it, so nothing in `btap.codes` sets it.

    `InternalMassDefinition`'s three methods are mutually exclusive in the same
    way and refused in the same way.

    :param surface_area_si: m^2, absolute
    :param per_floor_area_si: m^2 of mass per m^2 of floor — the usual stock
        form, since it scales with the building
    :param per_person_si: m^2 of mass per person
    :param construction: the mass's `ConstructionBase`, or None to leave it.
        A construction OBJECT, not a name: building or choosing one belongs to
        `btap.modeling.envelope`, which already does it.
    :returns: the ``InternalMass`` applied to, or None when given no area.
    """
    import openstudio

    given = {'surface_area_si': surface_area_si,
             'per_floor_area_si': per_floor_area_si,
             'per_person_si': per_person_si}
    given = {k: v for k, v in given.items() if v}
    if not given:
        return None
    if len(given) > 1:
        raise ValueError(
            'InternalMassDefinition carries ONE surface-area calculation '
            f"method: got {sorted(given)}. Each setter clears the others, so "
            'only the last would survive. Pass exactly one.')

    base = f"{space_type.nameString()} Internal Mass"

    def create():
        definition = openstudio.model.InternalMassDefinition(
            space_type.model())
        definition.setName(f"{base} Definition")
        mass = openstudio.model.InternalMass(definition)
        mass.setName(base)
        mass.setSpaceType(space_type)
        return mass

    instance = single_instance(space_type.internalMass(), create, audit=audit,
                               step=step)
    definition = opt(unshared_definition(
        instance, audit=audit, step=step).to_InternalMassDefinition())
    if surface_area_si:
        definition.setSurfaceArea(surface_area_si)
    elif per_floor_area_si:
        definition.setSurfaceAreaperSpaceFloorArea(per_floor_area_si)
    elif per_person_si:
        definition.setSurfaceAreaperPerson(per_person_si)
    if construction is not None:
        definition.setConstruction(construction)
    return instance

