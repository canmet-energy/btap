"""Equipment fingerprints: identify a zone's HVAC by what it IS (#256).

`identify.py` scores catalogue rows against `classify`'s coarse facts with
hand-written expectations of what each row should look like, and put the
right row first for 35 of 115 catalogue builds. This module reads the
equipment itself and matches it against fingerprints made by BUILDING every
catalogue row, so nothing mirrors a builder by hand. Nothing in the package
calls it yet; wiring it into the stock reader is a separate decision (#256).

Measured (scripts/fingerprint_eval/): every zone of every catalogue row
self-matches; leaving a row out never yields a wrong match; the NECB
reference builder's own assignments are named on 665 of 667 zones; and the
ASHRAE 90.1 Appendix G systems built by the OpenStudio SDK (NREL's
OpenStudio-resources, an author independent of openstudio-standards) land on
the rows an engineer would name, or on `none` where the catalogue has no such
row.

A zone is described as COMPONENTS (Fable's review of the first cut):

- one ``unit`` per piece of zone equipment (baseboard, PTAC, fan coil, unit
  heater, VRF terminal, ...);
- one ``air_loop`` per air loop serving the zone, together with the zone's
  terminal on it.

Each component carries two token sets:

- **identity**: object types, the air handler's components IN ORDER, the
  coils inside units, terminals and unitary wrappers (with whether each coil
  is always available, read from the schedule's VALUES: a scheduled coil is
  seasonal changeover), a small table of identity fields (a chilled beam's
  type), and the plants behind the component's water coils, followed through
  condenser and heat-exchanger loops;
- **controls**: what legitimately differs between authors and is reported as
  a difference, never used to decide a match: setpoint managers and resets,
  the economizer, fan object types, the sizing basis, whether a loop serves
  one zone or several (a fixture artefact: the catalogue is built on five
  zones), and equipment counts.

`explain` decides by components, not by a score: **match** (every component
covered), **partial** (a row covers some; the rest is listed), or **none**
(nearest row and what differs).
"""

from __future__ import annotations

from btap._compat import opt

#: Pass-through plumbing that says nothing about the system.
_PLUMBING = frozenset({
    'Node', 'Connector_Mixer', 'Connector_Splitter',
    'Pipe_Adiabatic', 'Pipe_Indoor', 'Pipe_Outdoor',
    'AirLoopHVAC_ZoneMixer', 'AirLoopHVAC_ZoneSplitter',
    'AirLoopHVAC_SupplyPlenum', 'AirLoopHVAC_ReturnPlenum',
    'Pump_VariableSpeed', 'Pump_ConstantSpeed',
    'HeaderedPumps_VariableSpeed', 'HeaderedPumps_ConstantSpeed',
})

#: Zone equipment that is not the zone's HVAC SYSTEM.
_NOT_A_SYSTEM = frozenset({'Fan_ZoneExhaust'})

#: Fields that are IDENTITY on some object types: two rows differing only in
#: one of these are different systems (the active and passive chilled-beam
#: rows collided without the beam type).
IDENTITY_FIELDS = {
    'AirTerminal_SingleDuct_ConstantVolume_CooledBeam': ('cooledBeamType',),
    'Boiler_HotWater': ('fuelType',),
    'Boiler_Steam': ('fuelType',),
    'Chiller_Electric_EIR': ('condenserType',),
    'Chiller_Electric_ReformulatedEIR': ('condenserType',),
    'HeatPump_PlantLoop_EIR_Heating': ('condenserType',),
    'HeatPump_PlantLoop_EIR_Cooling': ('condenserType',),
    'Coil_Heating_Gas': ('fuelType',),
    'Coil_Heating_Gas_MultiStage': ('fuelType',),
}

#: Equipment FAMILIES: stage counts and variants of one kind of equipment
#: are the same identity; the exact type is reported as a control
#: difference (measured: openstudio-standards models use two-speed DX where
#: the catalogue builds single-speed, and became no-match without this).
_FAMILY_PREFIXES = (
    ('Coil_Cooling_DX_', 'Coil_Cooling_DX'),
    ('Coil_Heating_DX_', 'Coil_Heating_DX'),
    ('Coil_Heating_Gas_MultiStage', 'Coil_Heating_Gas'),
    ('Coil_Heating_Electric_MultiStage', 'Coil_Heating_Electric'),
)

#: Owners on which a coil's AVAILABILITY is identity: a scheduled fan-coil
#: coil is seasonal changeover, the whole difference between a two-pipe and
#: a four-pipe system. Elsewhere a seasonal schedule is a control choice.
_AVAILABILITY_IS_IDENTITY = frozenset({'ZoneHVAC_FourPipeFanCoil'})


def _family(kind):
    for prefix, family in _FAMILY_PREFIXES:
        if kind.startswith(prefix):
            return family
    return kind


#: Wrappers that PACKAGE coils (to stage them, or as a unitary product).
#: Their coils are the air handler's own; the wrapper is reported as a
#: control. Measured: the NECB reference builds `psz-gas-hwbb-gasboiler` with
#: `staged_coils`, which wraps the same coils in a unitary system, and 391
#: reference zones whose equipment equalled that build were not named.
_WRAPPERS = frozenset({
    'AirLoopHVAC_UnitarySystem', 'AirLoopHVAC_UnitaryHeatPump_AirToAir',
    'AirLoopHVAC_UnitaryHeatPump_AirToAir_MultiSpeed',
})


#: Supply-air setpoint managers that make a unit follow ONE zone's load. The
#: humidity ones are not in it: they set a humidity, not the unit's role
#: (they matched by name prefix before).
_FOLLOWS_A_ZONE = frozenset({
    'SetpointManager_SingleZone_Reheat', 'SetpointManager_SingleZone_Heating',
    'SetpointManager_SingleZone_Cooling', 'SetpointManager_SingleZone_OneStageHeating',
    'SetpointManager_SingleZone_OneStageCooling',
})


#: Identity fields a type FIXES rather than stores. EnergyPlus 25.2's
#: `Coil:Heating:Gas:MultiStage` has no fuel field at all (its 20 fields carry
#: none), so it is natural gas; without this the staged NECB reference build
#: lost its fuel and stopped matching its own row.
IMPLIED_FIELDS = {'Coil_Heating_Gas_MultiStage': ('fuelType=NaturalGas',)}


#: Object types with no SDK cast found: recorded, never silently skipped.
UNCAST = set()


def _kind(obj):
    return obj.iddObjectType().valueName().replace('OS_', '', 1)


_CASTS = None


def _cast_table():
    """{IDD type name: the SDK `to<Class>` function}, built once from every
    model class's own `iddObjectType()`. Name-mangling the IDD name missed
    the classes the SDK abbreviates (`ZoneHVACLowTempRadiantVarFlow`)."""
    global _CASTS
    if _CASTS is None:
        import openstudio
        _CASTS = {}
        for name in dir(openstudio.model):
            cls = getattr(openstudio.model, name)
            idd = getattr(cls, 'iddObjectType', None)
            cast = getattr(openstudio.model, f'to{name}', None)
            if not (isinstance(cls, type) and callable(idd) and callable(cast)):
                continue
            try:
                _CASTS.setdefault(idd().valueName().replace('OS_', '', 1), cast)
            except TypeError:
                continue        # an instance method on a base class, not static
    return _CASTS


def _concrete(obj):
    cast = _cast_table().get(_kind(obj))
    if cast is None:
        UNCAST.add(_kind(obj))     # explain() reports these as notes
        return obj
    value = opt(cast(obj))
    return value if value is not None else obj


def _maybe(value):
    """Unwrap only a real optional: some accessors return the object."""
    return opt(value) if hasattr(value, 'is_initialized') else value


def _hvac(obj):
    return opt(obj.to_HVACComponent())


def _schedule_is_always_on(schedule):
    """Whether a schedule is 1 at every hour, read from its VALUES (the
    names vary: `Always On Discrete`, `Always_On`)."""
    constant = opt(schedule.to_ScheduleConstant())
    if constant is not None:
        return constant.value() == 1.0
    ruleset = opt(schedule.to_ScheduleRuleset())
    if ruleset is not None:
        days = [ruleset.defaultDaySchedule()] + [r.daySchedule() for r in ruleset.scheduleRules()]
        return all(all(v == 1.0 for v in day.values()) for day in days)
    compact = opt(schedule.to_ScheduleCompact())
    if compact is not None:
        # every numeric field is a value ("Until: 24:00, 1"); the rest are
        # "Through:", "For:" and "Until:" labels
        values = []
        for i in range(compact.numFields()):
            text = compact.getString(i)
            text = text.get() if text.is_initialized() else ''
            try:
                values.append(float(text))
            except ValueError:
                continue
        return bool(values) and all(v == 1.0 for v in values)
    return None     # not read: neither "always" nor "scheduled" is known


def _all_outdoor_air(controller, sizing, loop=None, notes=None):
    """Whether an air loop RUNS on 100% outdoor air.

    - a minimum outdoor-air fraction that is 1 at every hour; or
    - minimum and maximum outdoor-air flows fixed, equal to each other AND
      to the loop's design supply flow (equal flows alone are FIXED outdoor
      air: Fable, final review, a rooftop unit at 0.2 of 1.0 m3/s was read
      as 100%); a supply that is autosized cannot be compared and says so
      in `notes`; or
    - both autosized, with 100% outdoor air declared in sizing AND the supply
      sized on the ventilation requirement: the supply is then sized to the
      outdoor air, so the two autosized flows come out equal. This is how a
      DOAS is usually authored, ours included.

    The sizing flags ALONE are not evidence: the SDK's Appendix G System 5 and
    7 VAV set them, size on the sensible load, and run on mixed air.
    """
    minimum = opt(controller.minimumFractionofOutdoorAirSchedule())
    if minimum is not None and _schedule_is_always_on(minimum):
        return True
    if controller.isMinimumOutdoorAirFlowRateAutosized() and controller.isMaximumOutdoorAirFlowRateAutosized():
        return (sizing.allOutdoorAirinCooling() and sizing.allOutdoorAirinHeating()
                and sizing.typeofLoadtoSizeOn() == 'VentilationRequirement')
    low = opt(controller.minimumOutdoorAirFlowRate())
    high = opt(controller.maximumOutdoorAirFlowRate())
    if low is None or high is None or low <= 0 or abs(low - high) > 0.01 * max(low, high):
        return False
    supply = opt(loop.designSupplyAirFlowRate()) if loop is not None else None
    if supply is None:
        if notes is not None:
            notes.add('100% outdoor air not determined: fixed outdoor-air flows, '
                      'autosized supply')
        return False
    return low >= 0.99 * supply


def _schedule_max(schedule):
    """A schedule's highest value: constant, ruleset (every day schedule) or
    compact (every numeric field). None when the type is not read."""
    constant = opt(schedule.to_ScheduleConstant())
    if constant is not None:
        return constant.value()
    ruleset = opt(schedule.to_ScheduleRuleset())
    if ruleset is not None:
        days = [ruleset.defaultDaySchedule()] + [r.daySchedule() for r in ruleset.scheduleRules()]
        values = [v for day in days for v in day.values()]
        return max(values) if values else None
    compact = opt(schedule.to_ScheduleCompact())
    if compact is not None:
        values = []
        for i in range(compact.numFields()):
            text = compact.getString(i)
            try:
                values.append(float(text.get() if text.is_initialized() else ''))
            except ValueError:
                continue
        return max(values) if values else None
    return None


def _hottest_setpoint(node):
    """``(hottest temperature, unread)``: the highest temperature a node's
    setpoint managers ask for, C, and the kinds of manager that could not be
    read. Every manager is either read or named: a ruleset-scheduled or
    outdoor-following boiler-lift loop was read as low-temperature and
    MATCHED the wrong row silently (Fable, final review)."""
    values, unread = [], []
    for spm in node.setpointManagers():
        reset = opt(spm.to_SetpointManagerOutdoorAirReset())
        if reset is not None:
            values.append(max(reset.setpointatOutdoorLowTemperature(),
                              reset.setpointatOutdoorHighTemperature()))
            continue
        scheduled = opt(spm.to_SetpointManagerScheduled())
        if scheduled is not None:
            top = _schedule_max(scheduled.schedule())
            if top is not None:
                values.append(top)
                continue
        unread.append(_kind(spm))
    return (max(values) if values else None), unread


def _availability(coil):
    getter = getattr(coil, 'availabilitySchedule', None)
    if not callable(getter):
        return None
    try:
        schedule = _maybe(getter())
    except TypeError:
        return None
    if schedule is None:
        return None
    always = _schedule_is_always_on(schedule)
    if always is None:
        return 'unknown'
    return 'always' if always else 'scheduled'


def _token(kind, concrete):
    """The identity token of one object: its equipment family plus its
    identity fields."""
    family = _family(kind)
    fields = []
    for field in IDENTITY_FIELDS.get(kind, ()):
        getter = getattr(concrete, field, None)
        if callable(getter):
            fields.append(f'{field}={getter()}')
    fields.extend(IMPLIED_FIELDS.get(kind, ()))
    return family + (f"[{','.join(fields)}]" if fields else '')


def _children_by_container(model):
    out = {}
    for obj in model.getHVACComponents():
        for container in (opt(obj.containingHVACComponent()),
                          opt(obj.containingZoneHVACComponent())):
            if container is not None:
                out.setdefault(str(container.handle()), []).append(obj)
    return out


class Component:
    """One thing serving a zone: identity tokens decide, controls inform."""

    #: How many loops away from a coil the walk follows. Deeper loops are
    #: not read, and say so in `notes`.
    MAX_DEPTH = 3

    def __init__(self, role):
        self.role = role
        self.identity = set()
        self.controls = set()
        #: what the reader could NOT read here: absent, never silently skipped
        self.notes = set()
        self._plants = set()

    def plant(self, coil):
        """The plant behind a water coil, and the loops it rejects to."""
        hvac = _hvac(coil)
        loop = opt(hvac.plantLoop()) if hvac is not None else None
        if loop is not None:
            self._walk(loop, 0)

    def _walk(self, loop, depth):
        # A loop is named by its OWN type (heating, cooling, condenser), never
        # by the path that first reached it: a condenser loop shared by a
        # chiller and a heating heat pump was `cooling>condenser` or
        # `heating>condenser` by whichever coil the walk met first, and that
        # order is the SDK's hash order (Fable, review of the prototype: 1 of
        # 30 zones of one row, the transient self-match failure).
        key = str(loop.handle())
        if key in self._plants:
            return
        if depth > self.MAX_DEPTH:
            self.notes.add(f'plant walk stopped {self.MAX_DEPTH} loops from the coil')
            return
        self._plants.add(key)
        role = loop.sizingPlant().loopType().lower()
        heat_pump_tops, unread_setpoints = [], []
        counts = {}
        for comp in loop.supplyComponents():
            kind = _kind(comp)
            if kind in _PLUMBING:
                continue
            self.identity.add(f'plant:{role}:{_token(kind, _concrete(comp))}')
            counts[kind] = counts.get(kind, 0) + 1
            # whatever this rejects to or draws from: a chiller's condenser
            # loop, a heat exchanger's other side, a heat pump's source
            # (and a heat-recovery chiller's TERTIARY loop)
            w2w = opt(comp.to_WaterToWaterComponent()) if hasattr(comp, 'to_WaterToWaterComponent') else None
            if w2w is not None and kind == 'HeatPump_PlantLoop_EIR_Heating':
                outlet = opt(w2w.supplyOutletModelObject())
                node = opt(outlet.to_Node()) if outlet is not None else None
                if node is not None:
                    top, unread = _hottest_setpoint(node)
                    heat_pump_tops.append(top)
                    unread_setpoints.extend(unread)
            if w2w is not None:
                for other in (opt(w2w.plantLoop()), opt(w2w.secondaryPlantLoop()),
                              opt(w2w.tertiaryPlantLoop())):
                    if other is not None and str(other.handle()) != key:
                        self._walk(other, depth + 1)
        for kind, n in counts.items():
            if n > 1:
                self.controls.add(f'plant:{role}:{kind}:count={n}')
        # BOILER LIFT is identity (phylroy, 2026-11-28): the loop is held
        # hotter than its heat pump's own outlet setpoint, so a boiler lifts
        # what the heat pump cannot reach. Same equipment as a low-temperature
        # plant; measured 39% against 92% heat-pump share.
        loop_top, unread = _hottest_setpoint(loop.supplyOutletNode())
        unread_setpoints.extend(unread)
        tops = [h for h in heat_pump_tops if h is not None]
        if heat_pump_tops and (unread_setpoints or loop_top is None or not tops):
            self.notes.add(f'{role} plant: boiler lift not determined; setpoint managers '
                           f'not read: {sorted(set(unread_setpoints)) or ["none present"]}')
        elif loop_top is not None and tops and loop_top > max(tops) + 0.5:
            self.identity.add(f'plant:{role}:boiler_lifts_above_heat_pump')
        for spm in loop.supplyOutletNode().setpointManagers():
            self.controls.add(f'plant:{role}:spm:{_kind(spm)}')
            reset = opt(spm.to_SetpointManagerOutdoorAirReset())
            if reset is not None:
                self.controls.add(f'plant:{role}:reset:'
                                  f'{round(reset.setpointatOutdoorLowTemperature())}/'
                                  f'{round(reset.setpointatOutdoorHighTemperature())}')

    def frozen(self):
        return (self.role, tuple(sorted(self.identity)))

    def as_dict(self):
        return {'role': self.role, 'identity': sorted(self.identity),
                'controls': sorted(self.controls), 'notes': sorted(self.notes)}

    @classmethod
    def from_dict(cls, data):
        c = cls(data['role'])
        c.identity, c.controls = set(data['identity']), set(data['controls'])
        c.notes = set(data.get('notes', ()))
        return c


#: ENERGY STAR "Cold Climate" (ASHP specification v6.x, EPA key product
#: criteria, read 2026-11-28): COP at 5 F >= 1.75 AND heating capacity at
#: 5 F >= 70% of the capacity at 47 F. Chosen as identity because both are
#: performance values a model's coil holds (phylroy, #257). NEEP ccASHP v4.0
#: (variable capacity: >= 3 speeds or continuous, AND COP at 5 F >= 1.75 at
#: maximum capacity) is reported alongside, not used to decide.
COLD_CLIMATE_COP_5F = 1.75
COLD_CLIMATE_CAPACITY_RATIO_5F = 0.70
NEEP_MIN_SPEEDS = 3
_5F_C = -15.0
_47F_C = 8.33
_INDOOR_C = 21.1


def _at(curve, outdoor_c):
    """A performance curve at an outdoor temperature: f(outdoor) or
    f(indoor 21.1 C, outdoor), as the heating-coil curves are defined."""
    n = curve.numVariables()
    if n == 1:
        return curve.evaluate(outdoor_c)
    if n == 2:
        return curve.evaluate(_INDOOR_C, outdoor_c)
    return None


def heating_performance_at_5f(concrete, kind):
    """``(speeds, COP at 5 F, capacity at 5 F / capacity at 47 F)`` at
    maximum capacity, from the coil's own rated values and curves, or None
    when the coil is not a DX heating coil or a curve is unreadable."""
    try:
        if kind == 'Coil_Heating_DX_SingleSpeed':
            speeds, cop = 1, concrete.ratedCOP()
            lockout = concrete.minimumOutdoorDryBulbTemperatureforCompressorOperation()
            cap_curve = concrete.totalHeatingCapacityFunctionofTemperatureCurve()
            eir_curve = concrete.energyInputRatioFunctionofTemperatureCurve()
        elif kind == 'Coil_Heating_DX_VariableSpeed':
            levels = list(concrete.speeds())
            if not levels:
                return None
            top = levels[-1]
            speeds, cop = len(levels), top.referenceUnitGrossRatedHeatingCOP()
            lockout = concrete.minimumOutdoorDryBulbTemperatureforCompressorOperation()
            cap_curve = top.heatingCapacityFunctionofTemperatureCurve()
            eir_curve = top.energyInputRatioFunctionofTemperatureCurve()
        else:
            return None
        cap_5, cap_47 = _at(cap_curve, _5F_C), _at(cap_curve, _47F_C)
        eir_5, eir_47 = _at(eir_curve, _5F_C), _at(eir_curve, _47F_C)
    except (TypeError, RuntimeError):
        return None
    if None in (cap_5, cap_47, eir_5, eir_47) or cap_47 <= 0 or eir_5 <= 0:
        return None
    if lockout > _5F_C:
        # the compressor is OFF at 5 F: no capacity, whatever the curve says
        # (Fable, final review: a flat curve locked out at -5 C was tagged
        # cold-climate)
        return speeds, 0.0, 0.0
    return speeds, cop * eir_47 / eir_5, cap_5 / cap_47


#: DX HEATING coils the cold-climate test does not read yet: named in notes,
#: never silently skipped (Fable, final review).
_COLD_CLIMATE_UNREAD = ('Coil_Heating_DX_MultiSpeed', 'Coil_Heating_DX_VariableRefrigerantFlow',
                        'Coil_Heating_DX_VariableRefrigerantFlow_FluidTemperatureControl')


def _cold_climate(component, prefix, kind, concrete):
    if kind in _COLD_CLIMATE_UNREAD:
        component.notes.add(f'cold-climate test not read for {kind}')
        return
    performance = heating_performance_at_5f(concrete, kind)
    if performance is None:
        if kind.startswith('Coil_Heating_DX'):
            component.notes.add(f'cold-climate test not read for {kind}')
        return
    speeds, cop_5f, ratio = performance
    component.controls.add(f'{prefix}:{kind}:at 5F: COP {cop_5f:.2f}, capacity {ratio:.0%}, '
                           f'{speeds} speed(s)')
    if cop_5f >= COLD_CLIMATE_COP_5F and ratio >= COLD_CLIMATE_CAPACITY_RATIO_5F:
        component.identity.add(f'{prefix}:{_family(kind)}:cold_climate[ENERGY STAR]')
    neep = speeds >= NEEP_MIN_SPEEDS and cop_5f >= COLD_CLIMATE_COP_5F
    component.controls.add(f'{prefix}:{kind}:NEEP ccASHP v4.0 {"met" if neep else "not met"}')


def _add_coil(component, prefix, owner_kind, coil):
    kind = _kind(coil)
    concrete = _concrete(coil)
    availability = _availability(concrete)
    token = f'{prefix}:coil:{_token(kind, concrete)}'
    if availability and owner_kind in _AVAILABILITY_IS_IDENTITY:
        token += f'({availability})'
    elif availability:
        component.controls.add(f'{prefix}:coil:{kind}:{availability}')
    component.identity.add(token)
    if _family(kind) != kind:
        component.controls.add(f'{prefix}:coil:{kind}')
    _cold_climate(component, prefix, kind, concrete)
    component.plant(coil)


def _inner(component, owner, children, prefix):
    """The coils (identity) and fans (controls) inside `owner`, recursively."""
    for child in children.get(str(owner.handle()), []):
        kind = _kind(child)
        if 'Coil' in kind:
            _add_coil(component, prefix, _kind(owner), child)
        elif 'Fan' in kind:
            component.controls.add(f'{prefix}:fan:{kind}')
        _inner(component, child, children, prefix)


def zone_components(model, zone, children=None):
    """The components serving one thermal zone (see the module docstring)."""
    children = children if children is not None else _children_by_container(model)
    components = []
    terminals = {str(t.handle()): t for t in zone.airLoopHVACTerminals()}

    for equipment in zone.equipment():
        kind = _kind(equipment)
        if str(equipment.handle()) in terminals or kind in _NOT_A_SYSTEM:
            continue
        unit = Component('unit')
        concrete = _concrete(equipment)
        unit.identity.add(f'unit:{_token(kind, concrete)}')
        if children.get(str(equipment.handle())):
            _inner(unit, equipment, children, 'unit')
        else:
            # a baseboard's coil is its own, not "contained"
            coil = _maybe(concrete.heatingCoil()) if hasattr(concrete, 'heatingCoil') else None
            if coil is not None:
                _add_coil(unit, 'unit', kind, coil)
        components.append(unit)

    terminal_of = {}
    for terminal in terminals.values():
        concrete = _concrete(terminal)
        owner = opt(concrete.airLoopHVAC()) if hasattr(concrete, 'airLoopHVAC') else None
        if owner is not None:
            terminal_of[str(owner.handle())] = terminal
    for loop in zone.airLoopHVACs():
        part = Component('air_loop')
        terminal = terminal_of.get(str(loop.handle()))
        if terminal is not None:
            part.identity.add(f'terminal:{_token(_kind(terminal), _concrete(terminal))}')
            _inner(part, terminal, children, 'terminal')
        else:
            part.identity.add('terminal:none')
        sequence = []
        for comp in loop.supplyComponents():
            kind = _kind(comp)
            if kind in _PLUMBING:
                continue
            if kind.startswith('Fan'):
                part.controls.add(f'ahu:fan:{kind}')
                continue
            if kind == 'AirLoopHVAC_OutdoorAirSystem':
                sequence.append('OutdoorAir')
                oa = opt(loop.airLoopHVACOutdoorAirSystem())
                if oa is not None:
                    controller = oa.getControllerOutdoorAir()
                    part.controls.add(
                        f'ahu:economizer:{controller.getEconomizerControlType()}')
                    # 100% outdoor air is IDENTITY (a DOAS or make-up air
                    # unit), read from how the controller OPERATES: a minimum
                    # fraction that is 1 at every hour, or minimum and maximum
                    # flows set and equal. Not the sizing flags: EnergyPlus
                    # uses those for sizing only, and the SDK's own Appendix G
                    # System 5 and 7 VAV set them while running on mixed air,
                    # which made every independent VAV model a non-match
                    # (OpenStudio-resources, 2026-11-28).
                    if _all_outdoor_air(controller, loop.sizingSystem(), loop, part.notes):
                        part.identity.add('ahu:all_outdoor_air')
                    for oac in oa.components():
                        okind = _kind(oac)
                        if okind in _PLUMBING or okind.startswith('Fan'):
                            continue
                        # a preheat coil here has a fuel and a plant like any
                        # other (it got a bare type token before)
                        part.identity.add(f'ahu:oa:{_token(okind, _concrete(oac))}')
                        if 'Coil' in okind:
                            part.plant(oac)
                continue
            if kind in _WRAPPERS:
                part.controls.add(f'ahu:wrapper:{kind}')
                concrete = _concrete(comp)
                getter = getattr(concrete, 'controllingZoneorThermostatLocation', None)
                if callable(getter) and _maybe(getter()) is not None:
                    part.identity.add('ahu:follows_a_zone')
                stack = list(children.get(str(comp.handle()), []))
                while stack:
                    child = stack.pop(0)
                    ckind = _kind(child)
                    if 'Coil' in ckind and not ckind.startswith('CoilSystem'):
                        sequence.append(_token(ckind, _concrete(child)))
                        _cold_climate(part, 'ahu', ckind, _concrete(child))
                        if _family(ckind) != ckind:
                            part.controls.add(f'ahu:component:{ckind}')
                        part.plant(child)
                    elif 'Fan' in ckind:
                        part.controls.add(f'ahu:fan:{ckind}')
                    # nested: a CoilSystem's own coil (it was lost before)
                    stack.extend(children.get(str(child.handle()), []))
                continue
            sequence.append(_token(kind, _concrete(comp)))
            _cold_climate(part, 'ahu', kind, _concrete(comp))
            if _family(kind) != kind:
                part.controls.add(f'ahu:component:{kind}')
            if 'Coil' in kind:
                part.plant(comp)
            else:
                owner = _hvac(comp)
                if owner is not None:
                    _inner(part, owner, children, f'ahu:{kind}')
        # WHAT the air handler holds is identity; the ORDER is an arrangement
        # detail authors differ on (heating before or after the DX coil), so
        # it is reported, not matched.
        part.identity.add('ahu:components:' + '+'.join(sorted(sequence)))
        part.controls.add('ahu:order:' + '>'.join(sequence))
        zones = len(loop.thermalZones())
        part.controls.add(f'ahu:scope:{"one zone" if zones == 1 else "several zones"}')
        part.controls.add(f'ahu:sizing:{loop.sizingSystem().typeofLoadtoSizeOn()}')
        for spm in loop.supplyOutletNode().setpointManagers():
            part.controls.add(f'ahu:spm:{_kind(spm)}')
            # Whether the unit FOLLOWS A ZONE is its role, and identity: a
            # 100%-outdoor-air DOAS (scheduled supply temperature) and a
            # 100%-outdoor-air rooftop unit (single-zone reheat) were one
            # class without it. The exact manager stays a control: authors
            # pick Warmest or Scheduled for the same VAV.
            if _kind(spm) in _FOLLOWS_A_ZONE:
                part.identity.add('ahu:follows_a_zone')
        components.append(part)
    return components


def model_components(model):
    """``[(zone name, [Component])]`` for every zone, in name order."""
    children = _children_by_container(model)
    zones = sorted(model.getThermalZones(), key=lambda z: z.nameString())
    return [(z.nameString(), zone_components(model, z, children)) for z in zones]


def collapse(components):
    """Identical components as ONE, with the count as a control.

    phylroy (2026-11-28): how many identical units serve a zone is a sizing
    choice, not a different system. Two identical baseboards match the
    one-baseboard row, and "2 units" is reported as a difference; before,
    the zone was "composed" from the same row twice.
    """
    seen = {}
    for c in components:
        seen.setdefault(c.frozen(), []).append(c)
    out = []
    for group in seen.values():
        c = group[0]
        if len(group) > 1:
            merged = Component(c.role)
            merged.identity = set(c.identity)
            # every duplicate's controls and notes: two units identical in
            # identity may still differ in control (Fable, final review)
            merged.notes = set().union(*(g.notes for g in group))
            # name the unit by its own type token (`unit:ZoneHVAC_...`,
            # `terminal:...`), not by whichever token sorts first
            own = sorted(x for x in c.identity
                         if x.split(':')[0] in ('unit', 'terminal') and ':coil:' not in x)
            what = (own or sorted(c.identity) or [c.role])[0]
            merged.controls = set().union(*(g.controls for g in group)) | {
                f'{c.role}:count={len(group)}:{what}'}
            c = merged
        out.append(c)
    return out


def signature(components):
    """A zone's HVAC identity: its components' identities as a sorted
    multiset, identical components collapsed (see `collapse`). Equal
    signatures are one equivalence class."""
    return tuple(sorted(c.frozen() for c in collapse(components)))


def _jaccard(a, b):
    return len(a & b) / len(a | b) if (a or b) else 1.0


def _covers(row, remaining):
    """The zone components `row` covers exactly, or None if any of the row's
    own components is absent from `remaining`."""
    left = list(remaining)
    for rc in (c.frozen() for c in row):
        if rc not in left:
            return None
        left.remove(rc)
    return left


def explain(components, catalogue):
    """Explain one zone against the catalogue, by components.

    - ``match``: one row (or one equivalence class) builds exactly this;
    - ``composed``: several rows build it between them, one per part (a
      rooftop unit's row plus a unit-heater row), the exact cover that
      explains the most components with the fewest rows;
    - ``partial``: rows build some parts; ``uncovered`` lists the rest;
    - ``none``: no row builds any part; the nearest row and the differences;
    - ``unserved``: nothing serves the zone.

    :param catalogue: ``{row id: [Component]}``
    """
    if not components:
        return {'outcome': 'unserved', 'systems': []}
    components = collapse(components)
    # rows collapse the same way, or a row {a, a} could never cover (Fable)
    catalogue = {row_id: collapse(row) for row_id, row in catalogue.items()}
    zone = [c.frozen() for c in components]
    by_signature = {}
    for row_id, row in catalogue.items():
        by_signature.setdefault(signature(row), []).append(row_id)

    exact = by_signature.get(tuple(sorted(zone)))
    if exact:
        row = catalogue[exact[0]]
        return {'outcome': 'match', 'systems': sorted(exact),
                'control_differences': _control_diff(components, row),
                'notes': sorted(set().union(*(c.notes for c in components)))}

    parts, remaining, alternatives = _best_cover(zone, catalogue, by_signature)
    notes = sorted(set().union(*(c.notes for c in components)))
    if parts:
        return {'outcome': 'partial' if remaining else 'composed',
                'systems': [p['systems'] for p in parts],
                # other covers exactly as good: reported, not hidden behind
                # the catalogue's order (Fable, final review)
                'alternatives': alternatives,
                'parts': [{'systems': p['systems'], 'covers': [{'role': r, 'identity': list(i)}
                                                               for r, i in p['covers']]}
                          for p in parts],
                'uncovered': [{'role': r, 'identity': list(i)} for r, i in remaining],
                'notes': notes}
    result = _nearest(components, catalogue)
    result['notes'] = notes
    return result


def _best_cover(zone, catalogue, by_signature):
    """The decomposition of `zone` into catalogue classes that covers the
    MOST components, then uses the FEWEST rows. Exhaustive: a zone has a
    handful of components and only classes that fit are searched, where a
    greedy pick reported `partial` for a zone two rows explain exactly
    (Fable, review of the prototype: {a,b,c} with rows {a,b}, {b,c}, {a})."""
    fitting = []
    for ids in by_signature.values():
        if _covers(catalogue[ids[0]], zone) is not None:
            fitting.append(sorted(ids))
    fitting.sort()
    best, ties = ([], list(zone)), []

    def score(chosen, remaining):
        return (len(remaining), len(chosen))

    def name(chosen):
        return sorted(tuple(p['systems']) for p in chosen)

    def search(start, chosen, remaining):
        nonlocal best, ties
        if score(chosen, remaining) < score(*best):
            best, ties = (list(chosen), list(remaining)), []
        elif chosen and score(chosen, remaining) == score(*best) and name(chosen) != name(best[0]):
            ties.append(list(chosen))
        for k in range(start, len(fitting)):
            left = _covers(catalogue[fitting[k][0]], remaining)
            if left is None or len(left) == len(remaining):
                continue
            covered = _covered(remaining, left)
            chosen.append({'systems': fitting[k], 'covers': covered})
            search(k, chosen, left)
            chosen.pop()

    search(0, [], list(zone))
    # the lexically first of the equal covers, the others as alternatives
    covers = sorted([best[0]] + ties, key=name)
    chosen = covers[0]
    remaining = list(zone)
    for p in chosen:
        remaining = _covers(catalogue[p['systems'][0]], remaining)
    alternatives = [[list(s) for s in name(c)] for c in covers[1:] if name(c) != name(chosen)]
    return chosen, remaining, alternatives


def _covered(remaining, left):
    """`remaining` minus `left`, as multisets."""
    out = list(remaining)
    for item in left:
        out.remove(item)
    return out


def _control_diff(components, row):
    zone_controls = set().union(*(c.controls for c in components))
    row_controls = set().union(*(c.controls for c in row))
    return {'model_only': sorted(zone_controls - row_controls),
            'row_only': sorted(row_controls - zone_controls)}


def _nearest(components, catalogue):
    scored = []
    for row_id, row in catalogue.items():
        score, diffs, unused = 0.0, [], list(components)
        for rc in row:
            candidates = [zc for zc in unused if zc.role == rc.role]
            if not candidates:
                diffs.append({'row_has': sorted(rc.identity)})
                continue
            zc = max(candidates, key=lambda c: _jaccard(c.identity, rc.identity))
            unused.remove(zc)
            score += _jaccard(zc.identity, rc.identity)
            if zc.identity != rc.identity:
                diffs.append({'row_has': sorted(rc.identity - zc.identity),
                              'model_has': sorted(zc.identity - rc.identity)})
        diffs.extend({'model_has': sorted(zc.identity)} for zc in unused)
        scored.append((score / max(len(row), len(components)), row_id, diffs))
    scored.sort(key=lambda s: (-s[0], s[1]))
    similarity, row_id, diffs = scored[0]
    return {'outcome': 'none', 'systems': [row_id], 'similarity': round(similarity, 3),
            'nearest_differences': diffs}
