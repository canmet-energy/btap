"""HVAC builder performance-profile defaults and validation.

The mapping is deliberately a per-call authoring input, not a vintage
resolver. Callers choose concrete values; ``btap.modeling`` knows no vintage
or code family.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from types import MappingProxyType

from btap.modeling.hvac.components import curves

DEFAULT_PERFORMANCE_PROFILE = MappingProxyType({
    'dx_cooling_capacity_temperature_curve': 'DXCOOL-REF-CAPFT',
    'dx_cooling_capacity_flow_curve': 'DXCOOL-REF-CAPFFLOW',
    'dx_cooling_eir_temperature_curve': 'DXCOOL-REF-COOLEIRFT',
    'dx_cooling_eir_flow_curve': 'DXCOOL-REF-EIRFFLOW',
    'dx_cooling_part_load_fraction_curve': 'DXCOOL-REF-COOLPLFFPLR',
    'dx_heating_capacity_temperature_curve': 'DXHEAT-REF-CAPFT',
    'dx_heating_capacity_flow_curve': 'DXHEAT-REF-CAPFFLOW',
    'dx_heating_eir_temperature_curve': 'DXHEAT-REF-EIRFT',
    'dx_heating_eir_flow_curve': 'DXHEAT-REF-EIRFFLOW',
    'dx_heating_part_load_fraction_curve': 'DXHEAT-REF-PLFFPLR',
    'vrf_rated_heating_cop': 4.0,
    'vrf_gross_rated_cooling_cop': 4.0,
    'window_ac_eer_btu_per_w_h': 8.5,
    'evaporative_cooler_design_effectiveness': 0.9,
    'plant_heating_heat_pump_minimum_part_load_ratio': 0.2,
    'plant_cooling_heat_pump_minimum_part_load_ratio': 0.2,
    'ptac_fan_pressure_rise_pa': 640.0,
})

_CURVE_TYPES = {
    'dx_cooling_capacity_temperature_curve': 'biquadratic',
    'dx_cooling_capacity_flow_curve': 'quadratic',
    'dx_cooling_eir_temperature_curve': 'biquadratic',
    'dx_cooling_eir_flow_curve': 'quadratic',
    'dx_cooling_part_load_fraction_curve': 'cubic',
    'dx_heating_capacity_temperature_curve': 'cubic',
    'dx_heating_capacity_flow_curve': 'cubic',
    'dx_heating_eir_temperature_curve': 'cubic',
    'dx_heating_eir_flow_curve': 'quadratic',
    'dx_heating_part_load_fraction_curve': 'cubic',
}
_POSITIVE = {
    'vrf_rated_heating_cop',
    'vrf_gross_rated_cooling_cop',
    'window_ac_eer_btu_per_w_h',
    'ptac_fan_pressure_rise_pa',
}
_FRACTIONS = {
    'evaporative_cooler_design_effectiveness',
    'plant_heating_heat_pump_minimum_part_load_ratio',
    'plant_cooling_heat_pump_minimum_part_load_ratio',
}


def resolve(profile=None):
    """Merge a partial profile over the current builder defaults.

    Validation happens before builders mutate a model. Curve values name
    entries in ``hvac/data/curves.json``; this function does not resolve a
    vintage, recipe, or external data source.
    """
    if profile is None:
        return DEFAULT_PERFORMANCE_PROFILE
    if not isinstance(profile, Mapping):
        raise TypeError('performance_profile must be a mapping or None')
    if any(not isinstance(key, str) for key in profile):
        raise TypeError('performance_profile keys must be strings')

    unknown = sorted(set(profile) - set(DEFAULT_PERFORMANCE_PROFILE))
    if unknown:
        raise ValueError(
            'unknown performance_profile key(s): ' + ', '.join(unknown))

    resolved = dict(DEFAULT_PERFORMANCE_PROFILE)
    resolved.update(profile)
    curve_data = curves.data()
    for key, expected_type in _CURVE_TYPES.items():
        name = resolved[key]
        if not isinstance(name, str) or not name:
            raise ValueError(f'performance_profile {key!r} must be a curve name')
        spec = curve_data.get(name)
        if spec is None:
            raise ValueError(
                f"performance_profile {key!r} names unknown curve {name!r}")
        if spec.get('type') != expected_type:
            raise ValueError(
                f"performance_profile {key!r} must name a {expected_type} "
                f"curve, but {name!r} is {spec.get('type')!r}")

    for key in _POSITIVE | _FRACTIONS:
        value = resolved[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(
                f'performance_profile {key!r} must be a finite number')
        value = float(value)
        if not math.isfinite(value):
            raise ValueError(
                f'performance_profile {key!r} must be a finite number')
        if key in _POSITIVE and value <= 0.0:
            raise ValueError(
                f'performance_profile {key!r} must be greater than zero')
        if key in _FRACTIONS and not 0.0 <= value <= 1.0:
            raise ValueError(
                f'performance_profile {key!r} must be between zero and one')
        resolved[key] = value
    return MappingProxyType(resolved)
