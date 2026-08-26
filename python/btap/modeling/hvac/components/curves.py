"""Builds OpenStudio performance-curve objects from the gem's data/curves.json."""

from __future__ import annotations

import json
from pathlib import Path

import openstudio

DATA_PATH = Path(__file__).parent.parent / 'data' / 'curves.json'

_data = None


def data():
    global _data
    if _data is None:
        _data = json.loads(DATA_PATH.read_text(encoding='utf-8'))['curves']
    return _data


def defrost_eir_ft(model):
    """The defrost Energy Input Ratio modifier, f(T).

    EnergyPlus REQUIRES this field whenever Defrost Strategy is 'ReverseCycle'
    — on Coil:Heating:DX:SingleSpeed, Coil:Heating:DX:VariableSpeed and
    AirConditioner:VariableRefrigerantFlow alike:

      ** Severe ** ...required Defrost Energy Input Ratio Function of
                   Temperature Curve Name is blank.
                   ...field is required because Defrost Strategy is "ReverseCycle".

    and the SDK leaves it unset, because its own default strategy is
    'Resistive', which needs no curve. Setting the strategy without the curve
    therefore produces a model that looks fine to every in-process check and
    is rejected by EnergyPlus. Eight catalog systems shipped that way.

    The value is 1.0 — deliberately, not as a placeholder. The legacy oracle
    supplies a 22-point lookup table for this curve whose output is 1.0 at
    EVERY point (15.0-27.2 C indoor, -25 to +6 C outdoor), i.e. defrost EIR is
    not modified by temperature. A biquadratic with c1 = 1 and every other
    coefficient 0 is that same function, without importing the table.

    :return: openstudio.model.CurveBiquadratic, shared per model
    """
    name = 'DEFROST-EIR-FT'
    existing = next((c for c in model.getCurves() if c.nameString() == name), None)
    if existing is not None:
        return existing.to_CurveBiquadratic().get()

    curve = openstudio.model.CurveBiquadratic(model)
    curve.setName(name)
    curve.setCoefficient1Constant(1.0)
    for setter in (curve.setCoefficient2x, curve.setCoefficient3xPOW2,
                   curve.setCoefficient4y, curve.setCoefficient5yPOW2,
                   curve.setCoefficient6xTIMESY):
        setter(0.0)
    # The oracle table's own independent-variable span; outside it EnergyPlus
    # clamps, which for a constant function changes nothing.
    curve.setMinimumValueofx(15.0)
    curve.setMaximumValueofx(27.2)
    curve.setMinimumValueofy(-25.0)
    curve.setMaximumValueofy(6.0)
    return curve


def build(model, name):
    """Build (or fetch, if already present in the model) a named curve.

    :param model: openstudio.model.Model
    :param name: a curve name from data/curves.json
    :return: openstudio.model.Curve
    """
    existing = next((c for c in model.getCurves() if c.nameString() == name), None)
    if existing is not None:
        return existing

    spec = data().get(name)
    if spec is None:
        raise ValueError(f"unknown curve '{name}'")

    curve_type = spec['type']
    if curve_type == 'biquadratic':
        curve = build_biquadratic(model, spec)
    elif curve_type == 'quadratic':
        curve = build_quadratic(model, spec)
    elif curve_type == 'cubic':
        curve = build_cubic(model, spec)
    elif curve_type == 'quadlinear':
        curve = build_quadlinear(model, spec)
    else:
        raise ValueError(f"unknown curve type '{curve_type}' for '{name}'")
    curve.setName(name)
    return curve


def build_biquadratic(model, spec):
    curve = openstudio.model.CurveBiquadratic(model)
    curve.setCoefficient1Constant(spec['coeff_1_constant'])
    curve.setCoefficient2x(spec['coeff_2_x'])
    curve.setCoefficient3xPOW2(spec['coeff_3_x2'])
    curve.setCoefficient4y(spec['coeff_4_y'])
    curve.setCoefficient5yPOW2(spec['coeff_5_y2'])
    curve.setCoefficient6xTIMESY(spec['coeff_6_xy'])
    curve.setMinimumValueofx(spec['min_x'])
    curve.setMaximumValueofx(spec['max_x'])
    curve.setMinimumValueofy(spec['min_y'])
    curve.setMaximumValueofy(spec['max_y'])
    if spec.get('min_out') is not None:
        curve.setMinimumCurveOutput(spec['min_out'])
    if spec.get('max_out') is not None:
        curve.setMaximumCurveOutput(spec['max_out'])
    return curve


def build_quadlinear(model, spec):
    curve = openstudio.model.CurveQuadLinear(model)
    curve.setCoefficient1Constant(spec['coeff_1'])
    curve.setCoefficient2w(spec['coeff_2'])
    curve.setCoefficient3x(spec['coeff_3'])
    curve.setCoefficient4y(spec['coeff_4'])
    curve.setCoefficient5z(spec['coeff_5'])
    curve.setMinimumValueofw(spec['min_w'])
    curve.setMaximumValueofw(spec['max_w'])
    curve.setMinimumValueofx(spec['min_x'])
    curve.setMaximumValueofx(spec['max_x'])
    curve.setMinimumValueofy(spec['min_y'])
    curve.setMaximumValueofy(spec['max_y'])
    curve.setMinimumValueofz(spec['min_z'])
    curve.setMaximumValueofz(spec['max_z'])
    return curve


def build_quadratic(model, spec):
    curve = openstudio.model.CurveQuadratic(model)
    curve.setCoefficient1Constant(spec['coeff_1_constant'])
    curve.setCoefficient2x(spec['coeff_2_x'])
    curve.setCoefficient3xPOW2(spec['coeff_3_x2'])
    curve.setMinimumValueofx(spec['min_x'])
    curve.setMaximumValueofx(spec['max_x'])
    return curve


def build_cubic(model, spec):
    curve = openstudio.model.CurveCubic(model)
    curve.setCoefficient1Constant(spec['coeff_1_constant'])
    curve.setCoefficient2x(spec['coeff_2_x'])
    curve.setCoefficient3xPOW2(spec['coeff_3_x2'])
    curve.setCoefficient4xPOW3(spec['coeff_4_x3'])
    curve.setMinimumValueofx(spec['min_x'])
    curve.setMaximumValueofx(spec['max_x'])
    return curve
