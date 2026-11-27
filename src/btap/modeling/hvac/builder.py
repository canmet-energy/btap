"""The public facade."""

from __future__ import annotations

import importlib
from dataclasses import dataclass

from btap.modeling.hvac import catalog, performance, teardown, validation

# family -> (systems module basename, class name). Resolved LAZILY at build
# time so an unported system module never blocks importing this module or
# building the families that do exist.
FAMILIES = {
    'psz': ('psz', 'PSZ'),
    'vav_reheat': ('vav_reheat', 'VAVReheat'),
    'fan_coils': ('fan_coils', 'FanCoils'),
    'mau_ptac': ('mau_ptac', 'MauPtac'),
    'baseboards': ('baseboards_only', 'BaseboardsOnly'),
    'doas_pthp': ('doas_pthp', 'DoasPthp'),
    'ecm_ashp_baseboard': ('ashp_baseboard', 'AshpBaseboard'),
    'ecm_doas_vrf': ('doas_vrf', 'DoasVrf'),
    'ecm_hp_fancoils': ('hp_plant_fancoils', 'HpPlantFanCoils'),
    'zone_terminal': ('zone_terminal', 'ZoneTerminal'),
    'unit_heaters': ('unit_heaters', 'UnitHeaters'),
    'furnace': ('furnace', 'Furnace'),
    'evap_cooler': ('evap_cooler', 'EvapCooler'),
    'wshp': ('wshp', 'Wshp'),
    'doas': ('doas', 'Doas'),
    'vrf': ('vrf', 'Vrf'),
    'zone_ervs': ('zone_ervs', 'ZoneErvs'),
    'chilled_beams': ('chilled_beams', 'ChilledBeams'),
    'dual_duct': ('dual_duct', 'DualDuctVAV'),
    'crah': ('crah', 'Crah'),
}


@dataclass
class Result:
    system_name: str
    family: str
    air_loops: list
    control_zone: object
    #: Structured evidence a builder chose to record about a grouping decision,
    #: or None. The generic layer produces it and names no code family; a
    #: code layer interprets it. Sol's `127` required this handoff because the
    #: deciding method lives here and may not learn NECB ids.
    grouping_evidence: object = None


def _system_class(family):
    """Import the family's system-builder class, lazily. Returns None for an
    unregistered family; raises a clear ImportError naming the module when the
    family is registered but its module has not been ported yet."""
    entry = FAMILIES.get(family)
    if entry is None:
        return None
    module_name, class_name = entry
    qualified = f"btap.modeling.hvac.systems.{module_name}"
    try:
        module = importlib.import_module(qualified)
    except ModuleNotFoundError as error:
        if error.name == qualified:
            raise ImportError(
                f"system family '{family}' needs the module {qualified}, "
                "which is not ported yet") from error
        raise
    return getattr(module, class_name)


#: Hot-water plant options a caller may pass to ANY row with a hot-water plant.
_PLANT_SOURCE_KEYS = ('hw_source', 'hw_supply', 'hw_controls')

# ---------------------------------------------------------------------------
# Which caller `config` keys a COMPOSITE row accepts, and where they go.
#
# A composite builds each part with that part's own `config`, so before #244
# every caller key except the hot-water plant options was silently dropped:
# `config={'per_zone': True}` on a split-system composite built one shared
# unit, and a typo built the default. The rule now:
#
#   1. a key a part ACCEPTS reaches that part, and only that part, with the
#      caller's value winning over the part's own `config`;
#   2. a key NO part accepts is REFUSED, before preflight and so before any
#      teardown — never dropped;
#   3. identity and plant-STRUCTURE keys are refused outright: a part's id,
#      family or whether it builds a plant is what the composite IS, so
#      overriding one is choosing a different catalogue row;
#   4. `needs_zone_erv` is applied ONCE, by the composite, to its zones. Sent
#      to every part it would build one zone ERV per part per zone.
#
# "Accepts" means what the part's BUILDER READS, not what the catalogue rows
# of that family happen to carry. The per-family row allowlist in
# tests/modeling/test_catalog_schema.py (`FAMILY_KEYS`) was checked as the
# source and is the wrong one in both directions: builders read keys it does
# not list (`staged_coils` for psz, `mau` and `heating` for fan_coils,
# `heat_rejection` for wshp — the last two arrive through composite parts'
# own `config`), and it lists keys the family's class never reads (`boiler_fuel` on
# baseboards is read by the PLANT builder, only when the row needs a boiler).
# So the table below is declared from the builders and the plant rules, and
# tests/modeling/test_composite_config.py records every key each family's
# class actually reads while building every catalogue row, plus a source scan
# of each family module, and fails when a builder reads a key not declared
# here — the case that would silently drop it again.
# ---------------------------------------------------------------------------

#: Identity and plant-structure keys: refused on a composite (rule 3).
_COMPOSITE_REFUSED_KEYS = frozenset({
    'id', 'legacy_name', 'aliases', 'family', 'parts', 'origin', 'comment',
    'display', 'needs_boiler', 'needs_chiller'})

#: Read by `build_system` itself, for any part that builds a hot-water plant.
_HW_PLANT_KEYS = frozenset({
    'hw_source', 'hw_supply', 'hw_controls', 'boiler_fuel', 'boiler_part_load_curve_class',
    'hot_water_profile'})

#: Read by `build_system` itself, for any part that builds a chilled-water plant.
_CHW_PLANT_KEYS = frozenset({'chiller_type', 'chw_source', 'chilled_water_profile'})

#: The exchanger parameters `energy_recovery.resolve_energy_recovery` reads.
_ERV_FIELD_KEYS = frozenset({
    'erv_profile', 'erv_bypass_control_type',
    'erv_defrost_time_fraction_increase_rate', 'erv_economizer_lockout',
    'erv_frost_control_type', 'erv_frost_threshold_temperature',
    'erv_heat_exchanger_type', 'erv_initial_defrost_time_fraction',
    'erv_latent_effectiveness', 'erv_nominal_electric_power',
    'erv_sensible_effectiveness', 'erv_supply_air_outlet_temperature_control'})

#: Central recovery: `BaseSystem.attach_oa_system` reads `needs_erv`, so the
#: families that build an outdoor-air system through it take these.
_CENTRAL_ERV_KEYS = _ERV_FIELD_KEYS | {'needs_erv'}

#: Keys each family's builder class reads from its config (rule 1). `id` is
#: read by most and is identity, so it is not listed.
FAMILY_CONFIG_KEYS = {
    'baseboards': frozenset({'baseboard_type'}),
    'chilled_beams': frozenset({
        'baseboard_type', 'beam_design_inlet_water_temperature',
        'beam_design_outlet_water_temperature', 'beam_type',
        'chilled_water_profile', 'chw_source', 'dewpoint_margin',
        'doas_maximum_humidity_ratio', 'doas_supply_air_temperature',
        'needs_boiler', 'needs_chiller', 'sizing', 'sys_abbr'}) | _CENTRAL_ERV_KEYS,
    # crah.py calls BaseSystem.add_oa_system when `ventilation` is set, which
    # reads the central-ERV keys (Fable, review of #248).
    'crah': frozenset({
        'cooling_type', 'crah_maximum_humidity_ratio',
        'crah_supply_air_temperature', 'sizing', 'sys_abbr', 'ventilation'}) | _CENTRAL_ERV_KEYS,
    'doas': frozenset({'heating_type', 'sizing'}) | _CENTRAL_ERV_KEYS,
    'doas_pthp': frozenset({'sizing', 'supp_htg_fuel', 'sys_abbr'}) | _CENTRAL_ERV_KEYS,
    'dual_duct': frozenset({
        'needs_boiler', 'needs_chiller', 'sizing', 'sys_abbr'}) | _CENTRAL_ERV_KEYS,
    'ecm_ashp_baseboard': frozenset({
        'air_eqpt', 'baseboard_type', 'sizing', 'supp_htg_fuel', 'sys_abbr',
        'vent_type'}),
    'ecm_doas_vrf': frozenset({'air_eqpt', 'sizing', 'supp_htg_fuel', 'sys_abbr'}),
    'ecm_hp_fancoils': frozenset({
        'air_eqpt', 'boiler_fuel', 'plant_type', 'sizing', 'supp_htg_fuel',
        'sys_abbr'}),
    'evap_cooler': _CENTRAL_ERV_KEYS,
    'fan_coils': frozenset({
        'fan_coil_type', 'heating', 'mau', 'mau_cooling_type',
        'mau_heating_coil_type', 'sizing', 'sys_abbr'}) | _CENTRAL_ERV_KEYS,
    'furnace': frozenset({
        'cooling', 'equipment_class', 'heating', 'heating_type', 'per_zone',
        'reheat', 'sizing', 'ventilation'}) | _CENTRAL_ERV_KEYS,
    'mau_ptac': frozenset({
        'baseboard_type', 'mau_heating_coil_type', 'ptac_heating_type',
        'reference_hp', 'sizing', 'supp_htg_fuel', 'sys_abbr'}) | _CENTRAL_ERV_KEYS,
    'psz': frozenset({
        'baseboard_type', 'heat_source', 'heating_coil_type', 'per_zone',
        'sizing', 'staged_coils', 'supp_htg_fuel', 'sys_abbr'}) | _CENTRAL_ERV_KEYS,
    'unit_heaters': frozenset({'heating_type'}),
    'vav_reheat': frozenset({
        'baseboard_type', 'cooling_type', 'heating_coil_type', 'sizing',
        'sys_abbr'}) | _CENTRAL_ERV_KEYS,
    'vrf': frozenset({'zone_ventilation'}),
    'wshp': frozenset({'boiler_fuel', 'heat_rejection', 'sizing', 'ventilation'}),
    'zone_ervs': _ERV_FIELD_KEYS,
    'zone_terminal': frozenset({'baseboard_type', 'heating_type', 'sizing', 'unit_type'}),
}


def accepted_config_keys(part_resolved):
    """The caller keys one resolved, non-composite row's build reads: its
    family's own keys, plus the plant keys when it builds that plant."""
    keys = set(FAMILY_CONFIG_KEYS.get(part_resolved['family'], ()))
    if part_resolved.get('needs_boiler'):
        keys |= _HW_PLANT_KEYS
    if part_resolved.get('needs_chiller'):
        keys |= _CHW_PLANT_KEYS
    return keys


def _route_composite_config(resolved, config):
    """Apply a caller's `config` to a composite under the rule above, or refuse.

    Runs before preflight, so a refusal never follows a teardown.
    """
    config = {str(k): v for k, v in config.items()}
    refused = sorted(set(config) & _COMPOSITE_REFUSED_KEYS)
    if refused:
        raise ValueError(
            f"'{resolved['id']}' is a composite; {refused} name what its parts "
            'are and cannot be overridden per call. Choose the catalogue row '
            'that builds what you want instead.')

    # Rule 4: the composite itself takes the zone-ERV option, and with it the
    # exchanger fields that configure that device.
    composite_level = set()
    if 'needs_zone_erv' in config:
        composite_level.add('needs_zone_erv')
        if config['needs_zone_erv']:
            composite_level |= _ERV_FIELD_KEYS & set(config)

    parts, taken = [], set()
    for part in resolved['parts']:
        own = part.get('config') or {}
        part_resolved = {**catalog.resolve(part['id']),
                         **{str(k): v for k, v in own.items()}}
        accepts = accepted_config_keys(part_resolved) - {'needs_zone_erv'}
        routed = {k: v for k, v in config.items() if k in accepts}
        taken |= set(routed)
        parts.append({**part, 'config': {**own, **routed}} if routed else part)

    unaccepted = sorted(set(config) - taken - composite_level)
    if unaccepted:
        if set(unaccepted) & set(_PLANT_SOURCE_KEYS):
            raise ValueError(f"'{resolved['id']}' builds no hot-water plant; "
                             f'{unaccepted} do not apply')
        raise ValueError(
            f"'{resolved['id']}' is a composite of "
            f"{[p['id'] for p in resolved['parts']]} and none of its parts "
            f'reads {unaccepted}; refused rather than silently dropped')
    return {**resolved, **{k: config[k] for k in composite_level},
            'parts': parts}


def _route_plant_options(resolved, config):
    """Refuse hot-water plant options on a non-composite row with no plant.

    A row with no hot-water plant accepted `hw_source` and built nothing
    (Fable, PR #243). Runs before preflight, so a refusal never follows a
    teardown. Composites go through `_route_composite_config` instead.
    """
    if (not resolved.get('needs_boiler')
            and any(k in config for k in _PLANT_SOURCE_KEYS)):
        raise ValueError(f"'{resolved['id']}' builds no hot-water plant of its own; "
                         "hw_source, hw_supply and hw_controls do not apply")
    return resolved


def _preflight_resolved(model, resolved, zones, control_zone, namer,
                        remove_existing, performance_profile):
    """Validate a resolved row, including every composite part, without mutation."""
    if resolved['family'] == 'composite':
        for part in resolved['parts']:
            part_resolved = catalog.resolve(part['id'])
            if part.get('config'):
                part_resolved = {
                    **part_resolved,
                    **{str(k): v for k, v in part['config'].items()},
                }
            _preflight_resolved(
                model, part_resolved, zones, control_zone, namer,
                remove_existing, performance_profile)
        return

    from btap.modeling.hvac.systems import plant_loops

    plant_loops.validate_plant_config(resolved)
    system_class = _system_class(resolved['family'])
    if system_class is None:
        raise ValueError(f"no builder registered for family '{resolved['family']}'")
    system_class(resolved, performance_profile).preflight(
        model, zones, control_zone=control_zone, namer=namer,
        remove_existing=remove_existing)


def build_system(model, system_name, zones, control_zone=None, remove_existing=False,
                 namer='default', config=None, exclude_plants=None,
                 performance_profile=None, _probe=False):
    """Build a complete HVAC system on a set of thermal zones by descriptive
    name.

    ``exclude_plants`` names plant-loop handles this build must NOT adopt even
    when they match. The NECB reference path uses it to keep a reference system
    off ANY proposed plant that survived its teardown pass, whatever retained
    it — a `copy_proposed` block, process or service water on a
    ``WaterUseConnections``, or another non-zone demand. The retaining demand
    keeps the plant; a replaced block does not join it (D-101). It applies to
    hot-water, chilled-water and district loops alike, and travels into
    composite parts. The default adopts as before.

    The builder applies the selected ``performance_profile`` while creating
    equipment. With no profile, the current builder defaults are reproduced
    exactly. Run code-efficiency passes afterwards when building a compliance
    reference.

    :param model: openstudio.model.Model
    :param system_name: a catalog name (see btap.modeling.systems)
    :param zones: list of openstudio.model.ThermalZone to serve
    :param control_zone: the zone a shared single-zone unit follows. A
        ThermalZone is the user's choice and final. Omitted, or one of
        ``"heating"`` (the default rule) or ``"cooling"``, the
        unit follows zones[0] PROVISIONALLY and its loop is marked with the
        rule, which ``btap.modeling.elect_control_zones`` carries out after a
        sizing run (see ``btap.modeling.hvac.control_zones``).
    :param remove_existing: tear down HVAC serving these zones first, so the new
        system replaces rather than stacks (zone-scoped; other zones untouched)
    :param namer: 'default' or 'necb_pipe_name'
    :param config: per-call overrides merged over the catalog row (dict or None)
    :param performance_profile: partial mapping of performance overrides,
        merged over the current builder defaults
    :return: Result(system_name, family, air_loops, control_zone)
    """
    performance_profile = performance.resolve(performance_profile)
    validation.require_zones(zones)
    validation.require_thermostats(zones)
    from btap.modeling.hvac import control_zones
    rule = control_zones.LARGEST_HEATING_LOAD
    if isinstance(control_zone, str):
        rule = control_zones.rule_of(control_zone)
        control_zone = None
    elect = control_zone is None
    if elect:
        control_zone = zones[0]
    validation.require_control_zone(zones, control_zone)

    resolved = catalog.resolve(system_name)
    if config and resolved['family'] == 'composite':
        resolved = _route_composite_config(resolved, config)
    elif config:
        resolved = {**resolved, **{str(k): v for k, v in config.items()}}
        resolved = _route_plant_options(resolved, config)

    _preflight_resolved(
        model, resolved, zones, control_zone, namer, remove_existing,
        performance_profile)
    if resolved.get('needs_zone_erv') and not _probe:
        _probe_zone_ervs(model, system_name, zones, None if elect else control_zone,
                         remove_existing, namer, config, exclude_plants,
                         performance_profile)

    if remove_existing:
        teardown.remove_hvac_from_zones(model, zones)

    # Composite: a name that builds several catalog parts on the same zones
    # (e.g. 'DOAS with fan coil chiller with boiler' = DOAS part + no-MAU fan-coil part).
    if resolved['family'] == 'composite':
        air_loops = []
        for part in resolved['parts']:
            # The exclusion travels into the parts. A composite is where the
            # plants actually get built for several families at once, so
            # dropping it here left the documented contract unmet for exactly
            # the systems that need it most (Sol, `145`).
            air_loops.extend(
                build_system(model, part['id'], zones,
                             control_zone=control_zone, namer=namer,
                             config=part.get('config'),
                             exclude_plants=exclude_plants,
                             performance_profile=performance_profile).air_loops)
        if resolved.get('needs_zone_erv'):
            _add_zone_ervs(model, system_name, zones, air_loops, resolved)
        if elect:
            _mark_shared_loops(air_loops, rule)
        return Result(system_name=system_name, family='composite',
                      air_loops=air_loops, control_zone=control_zone)

    system_class = _system_class(resolved['family'])
    if system_class is None:
        raise ValueError(f"no builder registered for family '{resolved['family']}'")

    from btap.modeling.hvac.systems import plant_loops

    system = system_class(resolved, performance_profile)
    hw_loop = None
    if resolved.get('needs_boiler'):
        hw_loop = plant_loops.hot_water(model,
                                        fuel=resolved.get('boiler_fuel', 'NaturalGas'),
                                        source=resolved.get('hw_source', 'boiler'),
                                        part_load_curve_class=resolved.get(
                                            'boiler_part_load_curve_class'),
                                        profile=resolved.get('hot_water_profile'),
                                        supply=resolved.get('hw_supply', 'low_temperature'),
                                        controls=resolved.get('hw_controls'),
                                        minimum_part_load_ratio=performance_profile[
                                            'plant_heating_heat_pump_minimum_part_load_ratio'],
                                        exclude=exclude_plants or ())
    chw_loop = None
    if resolved.get('needs_chiller'):
        chw_loop = plant_loops.chilled_water(model,
                                             chiller_type=resolved.get('chiller_type', 'Scroll'),
                                             source=resolved.get('chw_source', 'water_cooled'),
                                             profile=resolved.get('chilled_water_profile'),
                                             exclude=exclude_plants or ())

    # The INSTANCE is kept, not discarded: a builder may record structured
    # evidence about a decision only it can see.
    air_loops = system.build(model, zones,
                             control_zone=control_zone,
                             namer=namer,
                             hw_loop=hw_loop,
                             chw_loop=chw_loop)

    # #217, phylroy: "we can apply an ERV to any system, right?" — nearly, and
    # it takes TWO devices. `BaseSystem.attach_oa_system` puts an exchanger on
    # an air loop's outdoor-air stream, which the eleven OA-bearing families
    # reach. The other twelve build no outdoor air at all, and for those the
    # device is a per-zone ERV with its own fans.
    #
    # Hooked HERE, at the single place a family's `build` is called, rather
    # than in each family: a zone ERV attaches to a ThermalZone and needs
    # nothing from the family that conditions it, so nine near-identical edits
    # would buy nothing. An earlier attempt to migrate ten call sites by regex
    # broke two files, which is the other reason to prefer one hook.
    #
    # `needs_zone_erv` is SEPARATE from `needs_erv` deliberately: they are
    # different devices with different parameters, and reusing the flag would
    # silently change what the two shipped `needs_erv` rows build.
    if resolved.get('needs_zone_erv'):
        _add_zone_ervs(model, system_name, zones, air_loops, resolved)

    if elect:
        _mark_shared_loops(air_loops, rule)
    return Result(system_name=system_name, family=resolved['family'],
                  air_loops=air_loops, control_zone=control_zone,
                  grouping_evidence=getattr(system, 'grouping_evidence', None))


def _probe_zone_ervs(model, system_name, zones, control_zone, remove_existing,
                     namer, config, exclude_plants, performance_profile):
    """Refuse `needs_zone_erv` BEFORE the real model is touched (#244).

    Whether a system ventilates centrally is known only once its families
    have built: ten builders add an outdoor-air system, each under its own
    conditions (a `ventilation` flag, the `mau` part, an else-branch). So the
    refusal ran after `remove_existing` had torn the old system down, and a
    refused rebuild left the zones with neither. Predicting it from the
    config would copy all ten conditions and drift; instead the same build
    runs, refusal included, on a throwaway clone. Only rows asking for zone
    ERVs pay for it.
    """
    from btap._compat import opt

    probe = model.clone(True).to_Model()
    probe_zones = [opt(probe.getThermalZone(zone.handle())) for zone in zones]
    if any(zone is None for zone in probe_zones):
        raise RuntimeError('a zone did not survive cloning the model')
    probe_control = None
    if control_zone is not None:
        probe_control = opt(probe.getThermalZone(control_zone.handle()))
    import warnings
    with warnings.catch_warnings():
        # the real build says it again; the probe must not say it twice
        warnings.simplefilter('ignore')
        build_system(probe, system_name, probe_zones, control_zone=probe_control,
                     remove_existing=remove_existing,
                     namer=namer if isinstance(namer, str) else 'default',
                     config=config, exclude_plants=exclude_plants,
                     performance_profile=performance_profile, _probe=True)


def _mark_shared_loops(air_loops, rule):
    """Mark every loop that serves several zones FROM ONE control zone, so its
    control zone can be elected after sizing. A multi-zone system with no
    single-zone control (VAV, DOAS) has nothing to elect and is not marked."""
    from btap.modeling.hvac import control_zones
    for loop in air_loops:
        if len(loop.thermalZones()) > 1 and control_zones.controls(loop):
            control_zones.mark_for_election(loop, rule)


def _add_zone_ervs(model, system_name, zones, air_loops, resolved):
    """One zone ERV per zone, refused where the system already ventilates.

    Called once per BUILD: by a plain row after its family builds, and by a
    composite after ALL its parts build, with every part's air loops — so a
    composite never gets one device per part per zone (#244).
    """
    from btap._compat import sorted_by_name
    from btap.modeling.hvac import energy_recovery

    # A zone ERV is that zone's VENTILATION SOURCE, with its own supply
    # and exhaust fans — not an accessory. So a family that already
    # ventilates centrally does not benefit from one, it DOUBLE-ventilates.
    # Measured before this guard: `psz`, `doas` and `vav_reheat` each
    # built a central outdoor-air system AND five zone ERVs, silently.
    #
    # Refused rather than warned, because the result is a model that
    # simulates and reports plausible numbers while moving roughly twice
    # the outdoor air the building asked for. Use `needs_erv` for a
    # central exchanger on those families.
    ventilating = [
        loop.nameString() for loop in air_loops
        if loop.airLoopHVACOutdoorAirSystem().is_initialized()
    ]
    if ventilating:
        raise ValueError(
            f"{system_name!r} cannot take `needs_zone_erv`: it already "
            f'ventilates centrally through '
            f"{', '.join(sorted(ventilating))}, and a zone ERV brings its "
            'own outdoor air, so the result would ventilate twice. Use '
            '`needs_erv` for an exchanger on the central outdoor-air '
            'stream instead.')

    # The OPTION resolves a profile, exactly as the central path does, so
    # `needs_zone_erv` cannot quietly inherit the SDK's defaults —
    # sensible 0.76, latent 0.68 and `frostControlType 'None'`, which
    # leaves an exchanger with no frost protection in a climate reaching
    # -40 C. The standalone "Zone ERVs" catalogue row still builds on
    # those defaults; migrating it changes its output and needs the
    # catalogue's gates.
    recovery = energy_recovery.resolve_energy_recovery(resolved)
    for zone in sorted_by_name(zones):
        energy_recovery.add_zone_energy_recovery(model, zone, recovery)
