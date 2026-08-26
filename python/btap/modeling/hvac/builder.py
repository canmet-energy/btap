"""The public facade."""

from __future__ import annotations

import importlib
from dataclasses import dataclass

from btap.modeling.hvac import catalog, teardown, validation

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
}


@dataclass
class Result:
    system_name: str
    family: str
    air_loops: list
    control_zone: object


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


def build_system(model, system_name, zones, control_zone=None, remove_existing=False,
                 namer='default', config=None):
    """Build a complete HVAC system topology on a set of thermal zones by
    descriptive name.

    Topology only: run your sizing and code-efficiency passes afterwards (e.g. with
    openstudio-standards, whose efficiency application is data-driven and applies to
    any topology, including systems built by this package).

    :param model: openstudio.model.Model
    :param system_name: a catalog name (see btap.modeling.systems)
    :param zones: list of openstudio.model.ThermalZone to serve
    :param control_zone: control zone for single-zone systems (default: zones[0])
    :param remove_existing: tear down HVAC serving these zones first, so the new
        system replaces rather than stacks (zone-scoped; other zones untouched)
    :param namer: 'default' or 'necb_pipe_name'
    :param config: per-call overrides merged over the catalog row (dict or None)
    :return: Result(system_name, family, air_loops, control_zone)
    """
    validation.require_zones(zones)
    validation.require_thermostats(zones)
    if control_zone is None:
        control_zone = zones[0]
    validation.require_control_zone(zones, control_zone)

    resolved = catalog.resolve(system_name)
    if config:
        resolved = {**resolved, **{str(k): v for k, v in config.items()}}

    if remove_existing:
        teardown.remove_hvac_from_zones(model, zones)

    # Composite: a name that builds several catalog parts on the same zones
    # (e.g. 'DOAS with fan coil chiller with boiler' = DOAS part + no-MAU fan-coil part).
    if resolved['family'] == 'composite':
        air_loops = []
        for part in resolved['parts']:
            air_loops.extend(
                build_system(model, part['name'], zones,
                             control_zone=control_zone, namer=namer,
                             config=part.get('config')).air_loops)
        return Result(system_name=system_name, family='composite',
                      air_loops=air_loops, control_zone=control_zone)

    system_class = _system_class(resolved['family'])
    if system_class is None:
        raise ValueError(f"no builder registered for family '{resolved['family']}'")

    from btap.modeling.hvac.systems import plant_loops

    hw_loop = None
    if resolved.get('needs_boiler'):
        hw_loop = plant_loops.hot_water(model,
                                        fuel=resolved.get('boiler_fuel', 'NaturalGas'),
                                        source=resolved.get('hw_source', 'boiler'))
    chw_loop = None
    if resolved.get('needs_chiller'):
        chw_loop = plant_loops.chilled_water(model,
                                             chiller_type=resolved.get('chiller_type', 'Scroll'),
                                             source=resolved.get('chw_source', 'water_cooled'))

    air_loops = system_class(resolved).build(model, zones,
                                             control_zone=control_zone,
                                             namer=namer,
                                             hw_loop=hw_loop,
                                             chw_loop=chw_loop)

    return Result(system_name=system_name, family=resolved['family'],
                  air_loops=air_loops, control_zone=control_zone)
