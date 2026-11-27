"""Equipment fingerprints: identify a zone's HVAC by what it IS (#256).

PROTOTYPE. `identify.py` scores catalogue rows against `classify`'s coarse
facts with hand-written expectations of what each row should look like. This
module instead reads a ROLE-BASED fingerprint straight from the equipment:

- **zone**: what serves the zone: zone equipment by object type, the air
  terminal, the coils inside both, and whether each coil is always available
  (a scheduled coil is seasonal changeover: a two-pipe fan coil);
- **ahu**: the air handler of every loop serving the zone: its supply
  components in order, the coils inside a unitary wrapper, the outdoor-air
  system, its economizer and exchangers, the sizing basis, and whether one
  loop serves one zone or several;
- **plant**: for every water coil above, the plant behind it: its source
  objects, boiler fuel, chiller condenser and heat rejection, setpoint
  manager kind and outdoor-reset endpoints.

The same extractor fingerprints the catalogue, by BUILDING each row (the way
the sizing sweep does), so nothing mirrors a builder by hand. Capacities,
efficiencies and sizes are deliberately not identity.

Fingerprints are sets of namespaced tokens; matching is weighted Jaccard per
stage. Two rows with the same fingerprint are reported as one equivalence
class rather than separated by a tie-break.
"""

from __future__ import annotations

from btap._compat import opt

#: Stage weights: what serves the zone matters most. `controls` holds what
#: third-party models legitimately do differently from our builders
#: (setpoint-manager kind, reset, economizer, fan object type): it still
#: separates rows that differ only in control, but cannot outweigh the
#: equipment. Measured on the 28 `models/` archetypes, those tokens were most
#: of every mismatch (618 zones on the plant reset alone).
STAGE_WEIGHTS = {'zone': 3.0, 'ahu': 2.0, 'plant': 2.0, 'controls': 0.5}

#: Zone equipment that is not the zone's HVAC SYSTEM.
_NOT_A_SYSTEM = frozenset({'Fan_ZoneExhaust'})

#: Pass-through plumbing that says nothing about the system.
_PLUMBING = frozenset({
    'OS_Node', 'OS_Connector_Mixer', 'OS_Connector_Splitter',
    'OS_Pipe_Adiabatic', 'OS_Pipe_Indoor', 'OS_Pipe_Outdoor',
    'OS_AirLoopHVAC_ZoneMixer', 'OS_AirLoopHVAC_ZoneSplitter',
    'OS_AirLoopHVAC_SupplyPlenum', 'OS_AirLoopHVAC_ReturnPlenum',
    'OS_Pump_VariableSpeed', 'OS_Pump_ConstantSpeed',
    'OS_HeaderedPumps_VariableSpeed', 'OS_HeaderedPumps_ConstantSpeed',
})


def _kind(obj):
    return obj.iddObjectType().valueName().replace('OS_', '', 1)


def _hvac(obj):
    return opt(obj.to_HVACComponent())


def _maybe(value):
    """An accessor's result, unwrapped only when it IS an optional: some
    accessors (`heatingCoil` on a baseboard or fan coil) return the object
    itself, and `opt` on one of those raises."""
    return opt(value) if hasattr(value, 'is_initialized') else value


def _children_by_container(model):
    """{container handle: [component]}: the coils and fans inside a unitary
    wrapper, a terminal or a piece of zone equipment."""
    out = {}
    for obj in model.getHVACComponents():
        for container in (opt(obj.containingHVACComponent()),
                          opt(obj.containingZoneHVACComponent())):
            if container is not None:
                out.setdefault(str(container.handle()), []).append(obj)
    return out


def _always_available(coil):
    """Whether a coil's availability schedule is the always-on one."""
    getter = getattr(coil, 'availabilitySchedule', None)
    if getter is None:
        return None
    try:
        schedule = getter()
    except TypeError:
        return None
    schedule = _maybe(schedule)
    if schedule is None:
        return None
    name = schedule.nameString().lower()
    return 'always on' in name


def _plant_tokens(loop, role, seen):
    """(equipment tokens, control tokens) for the plant behind a coil."""
    key = (str(loop.handle()), role)
    if key in seen:
        return set(), set()
    seen.add(key)
    tokens, controls = set(), set()
    for comp in loop.supplyComponents():
        kind = _kind(comp)
        if 'OS_' + kind in _PLUMBING:
            continue
        tokens.add(f'plant:{role}:{kind}')
        concrete = _concrete(comp)
        fuel = getattr(concrete, 'fuelType', None)
        if callable(fuel) and kind.startswith('Boiler'):
            tokens.add(f'plant:{role}:{kind}:fuel={fuel()}')
        condenser = getattr(concrete, 'condenserType', None)
        if callable(condenser) and kind.startswith('Chiller'):
            tokens.add(f'plant:{role}:{kind}:condenser={condenser()}')
            secondary = _maybe(concrete.secondaryPlantLoop()) if hasattr(concrete, 'secondaryPlantLoop') else None
            if secondary is not None:
                for sc in secondary.supplyComponents():
                    if 'OS_' + _kind(sc) not in _PLUMBING:
                        tokens.add(f'plant:{role}:rejection:{_kind(sc)}')
        source = getattr(concrete, 'condenserType', None)
        if kind.startswith('HeatPumpPlantLoopEIR') and callable(source):
            tokens.add(f'plant:{role}:{kind}:source={source()}')
    for spm in loop.supplyOutletNode().setpointManagers():
        kind = _kind(spm)
        controls.add(f'controls:{role}_plant:spm:{kind}')
        reset = opt(spm.to_SetpointManagerOutdoorAirReset())
        if reset is not None:
            controls.add(f'controls:{role}_plant:reset:'
                         f'{round(reset.setpointatOutdoorLowTemperature())}'
                         f'/{round(reset.setpointatOutdoorHighTemperature())}')
    return tokens, controls


def _concrete(obj):
    """The concrete SDK type of a ModelObject, via its `to_<Type>` cast."""
    import openstudio
    name = _kind(obj).replace('_', '')
    cast = getattr(openstudio.model, f'to{name}', None)
    if cast is None:
        return obj
    value = opt(cast(obj))
    return value if value is not None else obj


def _coil_tokens(stage, owner_kind, coil, seen_plants):
    """Tokens for one coil: its type, availability, and its plant."""
    kind = _kind(coil)
    tokens = {f'{stage}:{owner_kind}:coil:{kind}'}
    concrete = _concrete(coil)
    available = _always_available(concrete)
    if available is not None:
        tokens.add(f'{stage}:{owner_kind}:coil:{kind}:'
                   f'{"always" if available else "scheduled"}')
    plant_tokens = (set(), set())
    hvac = _hvac(coil)
    loop = opt(hvac.plantLoop()) if hvac is not None else None
    if loop is not None:
        role = 'cooling' if 'Cooling' in kind else 'heating'
        plant_tokens = _plant_tokens(loop, role, seen_plants)
    return tokens, plant_tokens


def zone_fingerprint(model, zone, children=None):
    """``{'zone': set, 'ahu': set, 'plant': set}`` for one thermal zone."""
    children = children if children is not None else _children_by_container(model)
    out = {'zone': set(), 'ahu': set(), 'plant': set(), 'controls': set()}
    seen_plants = set()

    def add_coils(stage, owner):
        for child in children.get(str(owner.handle()), []):
            kind = _kind(child)
            if 'Coil' in kind:
                tokens, plant = _coil_tokens(stage, _kind(owner), child, seen_plants)
                out[stage] |= tokens
                out['plant'] |= plant[0]
                out['controls'] |= plant[1]
            elif 'Fan' in kind:
                out['controls'].add(f'controls:{stage}:{_kind(owner)}:fan:{kind}')
            add_coils(stage, child)          # nested: a terminal unit's coils

    terminal = opt(zone.airLoopHVACTerminal())
    for equipment in zone.equipment():
        if terminal is not None and str(equipment.handle()) == str(terminal.handle()):
            continue
        if _kind(equipment) in _NOT_A_SYSTEM:
            continue
        out['zone'].add(f'zone:equipment:{_kind(equipment)}')
        # a baseboard's coil is not "contained": it is the baseboard's own
        concrete = _concrete(equipment)
        coil = _maybe(concrete.heatingCoil()) if hasattr(concrete, 'heatingCoil') else None
        if coil is not None and not children.get(str(equipment.handle())):
            tokens, plant = _coil_tokens('zone', _kind(equipment), coil, seen_plants)
            out['zone'] |= tokens
            out['plant'] |= plant[0]
            out['controls'] |= plant[1]
        add_coils('zone', equipment)
    if terminal is not None:
        out['zone'].add(f'zone:terminal:{_kind(terminal)}')
        add_coils('zone', terminal)

    for loop in zone.airLoopHVACs():
        zones = len(loop.thermalZones())
        out['ahu'].add(f'ahu:scope:{"one zone" if zones == 1 else "several zones"}')
        out['ahu'].add(f'ahu:sizing:{loop.sizingSystem().typeofLoadtoSizeOn()}')
        for comp in loop.supplyComponents():
            kind = _kind(comp)
            if 'OS_' + kind in _PLUMBING:
                continue
            if kind == 'AirLoopHVAC_OutdoorAirSystem':
                oa = opt(loop.airLoopHVACOutdoorAirSystem())
                out['ahu'].add('ahu:outdoor_air')
                if oa is not None:
                    controller = oa.getControllerOutdoorAir()
                    out['controls'].add(
                        f'controls:economizer:{controller.getEconomizerControlType()}')
                    for oac in oa.components():
                        if 'OS_' + _kind(oac) not in _PLUMBING:
                            out['ahu'].add(f'ahu:oa:{_kind(oac)}')
                continue
            if 'Coil' in kind:
                tokens, plant = _coil_tokens('ahu', 'loop', comp, seen_plants)
                out['ahu'] |= tokens
                out['plant'] |= plant[0]
                out['controls'] |= plant[1]
            elif kind.startswith('Fan'):
                out['controls'].add(f'controls:ahu:fan:{kind}')
            else:
                out['ahu'].add(f'ahu:component:{kind}')
                owner = _hvac(comp)
                if owner is not None:
                    add_coils('ahu', owner)
    return out


def model_fingerprints(model):
    """``[(zone name, fingerprint)]`` for every zone, in name order."""
    children = _children_by_container(model)
    zones = sorted(model.getThermalZones(), key=lambda z: z.nameString())
    return [(z.nameString(), zone_fingerprint(model, z, children)) for z in zones]


def similarity(a, b):
    """Weighted Jaccard over the stages: 1.0 identical, 0.0 disjoint."""
    total = weight = 0.0
    for stage, w in STAGE_WEIGHTS.items():
        sa, sb = a.get(stage, set()), b.get(stage, set())
        if not sa and not sb:
            continue
        total += w * len(sa & sb) / len(sa | sb)
        weight += w
    return total / weight if weight else 0.0


def frozen(fp):
    """A hashable, order-free form of a fingerprint (for equivalence)."""
    return tuple(sorted((stage, tuple(sorted(tokens))) for stage, tokens in fp.items()))


def rank(fp, catalogue, limit=3):
    """Rank catalogue rows against one zone fingerprint.

    :param catalogue: ``{row id: fingerprint}``
    :returns: ``[{'systems': [ids with this fingerprint], 'similarity',
        'matched', 'missing', 'extra'}]`` best first, rows with IDENTICAL
        fingerprints grouped as one candidate.
    """
    classes = {}
    for row_id, row_fp in catalogue.items():
        classes.setdefault(frozen(row_fp), (row_fp, []))[1].append(row_id)
    ranked = []
    for row_fp, ids in classes.values():
        tokens_a = set().union(*fp.values())
        tokens_b = set().union(*row_fp.values())
        ranked.append({'systems': sorted(ids), 'similarity': round(similarity(fp, row_fp), 4),
                       'matched': sorted(tokens_a & tokens_b),
                       'missing': sorted(tokens_b - tokens_a),
                       'extra': sorted(tokens_a - tokens_b)})
    ranked.sort(key=lambda c: (-c['similarity'], c['systems']))
    return ranked[:limit]
