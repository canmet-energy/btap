#!/usr/bin/env python3
"""Regenerate the reference DX part-load refit study (docs/necb_dx_plf_refit.md).

Open work: the product does not ship these polynomials. Everything here is
DERIVED from the Article cubics and the shipped curves, so the study is
reproducible rather than transcribed — which is why D-102 carries none of it.

Stdlib only, and no `btap` import: this runs from a bare checkout.
"""
from __future__ import annotations

import argparse
import json
import pathlib

#: Article sentence (5) EIR_FPLR cubics, a + b*PLR + c*PLR^2 + d*PLR^3.
ARTICLE = {"heating": (0.0856522, 0.9388137, -0.1834361, 0.1589702),
           "cooling": (0.2012301, -0.0312175, 1.9504979, -1.1205105)}
CURVE = {"heating": "DXHEAT-REF-PLFFPLR", "cooling": "DXCOOL-REF-COOLPLFFPLR"}
CARRIER_LO, CARRIER_HI = 0.7, 1.0
DATA = (pathlib.Path(__file__).resolve().parents[2] / "python" / "btap"
        / "codes" / "necb" / "data")


def cubic(coef, x):
    return sum(k * x ** i for i, k in enumerate(coef))


def exact(kind, plr):
    """The transformed Article target, PLF = PLR / EIR_FPLR."""
    return plr / cubic(ARTICLE[kind], plr)


def root(kind, target, lo, hi):
    """Where the exact target crosses `target`, by bisection."""
    for _ in range(300):
        mid = (lo + hi) / 2
        if (exact(kind, mid) < target) == (exact(kind, lo) < target):
            lo = mid
        else:
            hi = mid
    return hi


def shipped(kind, edition="necb2020"):
    data = json.loads((DATA / edition / "efficiencies.json")
                      .read_text(encoding="utf-8"))
    row = next(c for c in data["curves"]
               if isinstance(c, dict) and c.get("name") == CURVE[kind])
    return [row["coeff_1"], row["coeff_2"], row["coeff_3"], row["coeff_4"]]


def fit(kind, xs):
    """Least-squares cubic by normal equations, over the given sample points."""
    n = 4
    m = [[0.0] * (n + 1) for _ in range(n)]
    for x in xs:
        basis, y = [1.0, x, x * x, x ** 3], exact(kind, x)
        for r in range(n):
            for c in range(n):
                m[r][c] += basis[r] * basis[c]
            m[r][n] += basis[r] * y
    for col in range(n):
        piv = max(range(col, n), key=lambda r: abs(m[r][col]))
        m[col], m[piv] = m[piv], m[col]
        for r in range(n):
            if r != col and m[col][col]:
                f = m[r][col] / m[col][col]
                for c in range(col, n + 1):
                    m[r][c] -= f * m[col][c]
    return [m[r][n] / m[r][r] for r in range(n)]


def worst(kind, coef, xs):
    """Maximum relative error AS APPLIED, i.e. after the output clamps."""
    out = 0.0
    for x in xs:
        want = exact(kind, x)
        got = max(CARRIER_LO, min(CARRIER_HI, cubic(coef, x)))
        out = max(out, abs(got - want) / want * 100.0)
    return out


def grid(lo, hi, intervals):
    return [lo + (hi - lo) * i / intervals for i in range(intervals + 1)]


def study():
    out = {}
    for kind in ("heating", "cooling"):
        lo = root(kind, CARRIER_LO, 0.05, 0.5)
        hi = root(kind, CARRIER_HI, 0.5, 0.95) if kind == "heating" else 1.0
        rec = {"lower_root": lo, "upper_root": hi if kind == "heating" else None,
               "shipped_worst": worst(kind, shipped(kind), grid(lo, hi, 100_000)),
               "progression": {}}
        for n in (200, 400, 20_000, 100_000):
            xs = grid(lo, hi, n)
            rec["progression"][n] = worst(kind, fit(kind, xs), xs)
        xs = grid(lo, hi, 100_000)
        a1 = fit(kind, xs)
        rec["account_1"] = {"coefficients": a1, "max_as_applied": worst(kind, a1, xs),
                            "raw_at_full_load": cubic(a1, 1.0)}
        if kind == "heating":
            a2 = fit(kind, xs + [1.0])
            rec["account_2"] = {"coefficients": a2,
                                "max_as_applied": worst(kind, a2, xs + [1.0]),
                                "raw_at_full_load": cubic(a2, 1.0)}
        out[kind] = rec
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    data = study()
    if args.json:
        print(json.dumps(data, indent=2))
        return 0
    for kind, rec in data.items():
        print(f"\n=== {kind}")
        print(f"  lower root                {rec['lower_root']!r}")
        if rec["upper_root"]:
            print(f"  upper root                {rec['upper_root']!r}")
        print(f"  SHIPPED worst as applied  {rec['shipped_worst']:.6f}%")
        domain = ("primary interval" if rec["upper_root"]
                  else "representable region")
        # Account 1 fits heating's PRIMARY INTERVAL, not its whole
        # (disconnected) set — calling it "the representable set" repeats the
        # conflation D-102 was corrected for.
        print(f"  refit over the {domain}, by sample density:")
        for n, w in rec["progression"].items():
            print(f"    {n:>7} intervals        {w:.6f}%")
        for name in ("account_1", "account_2"):
            acc = rec.get(name)
            if not acc:
                continue
            print(f"  {name}: max as applied {acc['max_as_applied']:.6f}%, "
                  f"raw at full load {acc['raw_at_full_load']:.6f}")
    print("\nOpen work: the product ships none of these. See "
          "docs/necb_dx_plf_refit.md.")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
