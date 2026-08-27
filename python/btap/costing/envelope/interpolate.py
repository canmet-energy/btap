"""Exact port of BTAP::LinearRegression.interpolate — the cost-vs-RSI
interpolator legacy envelope costing keys on. Semantics preserved verbatim:
±2% clamp bands beyond the data return the CLAMPED bound (±2% of the
boundary y), in-band out-of-range extrapolates linearly from the two nearest
points, in-range interpolates piecewise-linearly.

DELIBERATE DEVIATION from legacy: exceeding the upper clamp does NOT add the
legacy $10^12 "revolutionary engineering technology fudge factor" to the
total — the condition surfaces as ``upper_bound_exceeded`` on the result and
the caller writes a LOUD audit warning + report flag instead.
"""

from __future__ import annotations

from dataclasses import dataclass

from btap._compat import ruby_round, ruby_str


@dataclass
class Result:
    value: float
    note: str
    upper_bound_exceeded: bool


def interpolate(*, x_y_array, x2, extrapolation_range=0.02) -> Result:
    """x_y_array: sequence of (x, y) pairs; x2: where to evaluate;
    extrapolation_range: clamp band, fraction (legacy 0.02)."""
    note = "OK"
    # Ruby: array.uniq.sort { |a, b| a[0] <=> b[0] } — dedupe exact pairs,
    # then sort by x only.
    seen = set()
    array = []
    for pair in x_y_array:
        key = tuple(pair)
        if key in seen:
            continue
        seen.add(key)
        array.append(list(pair))
    array.sort(key=lambda pair: pair[0])
    pct = extrapolation_range * 100

    if not array:
        return Result(value=0.0,
                      note="empty array given for interpolation, returning zero",
                      upper_bound_exceeded=False)
    if len(array) == 1:
        return Result(value=float(array[0][1]), note=note,
                      upper_bound_exceeded=False)

    x_lo = (1.0 - extrapolation_range) * array[0][0]
    x_hi = (1.0 + extrapolation_range) * array[-1][0]
    y_lo = (1.0 - extrapolation_range) * array[0][1]
    y_hi = (1.0 + extrapolation_range) * array[-1][1]

    if x2 < x_lo:
        return Result(
            value=y_lo, upper_bound_exceeded=False,
            note=(f"x {ruby_str(ruby_round(x2, 4))} precedes the lower bound "
                  f"({ruby_str(ruby_round(x_lo, 4))}) for the {ruby_str(pct)}% "
                  "range; returning the lower bound"))
    if x2 > x_hi:
        return Result(
            value=y_hi, upper_bound_exceeded=True,
            note=(f"x {ruby_str(ruby_round(x2, 4))} exceeds the upper bound "
                  f"({ruby_str(ruby_round(x_hi, 4))}) for the {ruby_str(pct)}% "
                  "range; returning the upper bound"))
    if x2 < float(array[0][0]):
        return Result(value=linear(array[0], array[1], x2), note=note,
                      upper_bound_exceeded=False)
    if x2 > float(array[-1][0]):
        return Result(value=linear(array[-2], array[-1], x2), note=note,
                      upper_bound_exceeded=False)

    for (x0, y0), (x1, y1) in zip(array, array[1:]):
        if x2 < x0 or x2 > x1:
            continue

        value = float(y0)
        if (x1 - x0) > 0.0:
            value = float(y0) + (float(y1 - y0) * float(x2 - x0) / float(x1 - x0))
        return Result(value=value, note=note, upper_bound_exceeded=False)
    return Result(value=float(array[-1][1]),
                  note="fell through interpolation; returning last point",
                  upper_bound_exceeded=False)


def linear(p0, p1, x2) -> float:
    x0, y0 = (float(v) for v in p0)
    x1, y1 = (float(v) for v in p1)
    slope = (y1 - y0) / (x1 - x0)
    return y0 + slope * (x2 - x0)
