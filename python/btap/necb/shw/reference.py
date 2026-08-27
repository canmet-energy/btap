"""Reference-building SWH — NECB 2020 8.4.4.20 (2025: 8.4.5.20):

  (1) storage capacity, power input and energy type identical to proposed —
      satisfied by construction in the umbrella (the reference is a clone and
      no transform touches SWH plant sizing or fuel)
  (2) HP-source SWH -> air-source HP: vacuous until HP SWH is modeled
  (3)-(4) not machine-retrievable (extraction gap) — treated as Part 6
      minimums by re-applying the Table 6.2.2.1 performance on the
      reference's (identical) heaters.
"""

from __future__ import annotations

from btap._compat import sorted_by_name
from btap.audit import AuditLog, emit_coverage
from btap.necb import shw as SHW
from btap.necb.shw import efficiency as Efficiency


def reference_shw(model, *, vintage="2020", audit=None):
    audit = audit if audit is not None else AuditLog()
    prefix = "8.4.5" if str(vintage) == "2025" else "8.4.4"
    heaters = sorted_by_name(model.getWaterHeaterMixeds())
    audit.info("shw_reference",
               "reference SWH storage capacity, power input and energy type identical to "
               "proposed by construction (clone; no transform touches SWH sizing or fuel)",
               inputs={"water_heaters": len(heaters)}, article=f"{prefix}.20.(1)")
    for heater in heaters:
        Efficiency.apply_efficiency(heater, vintage=vintage, audit=audit)
    # Table 6.2.2.1 solar-thermal + pool-heater rows (D-63): apply-when-present.
    Efficiency.apply_solar_pool_minimums(model, vintage=vintage, audit=audit)
    _emit_article_coverage(vintage, audit)
    return audit


def _emit_article_coverage(vintage, audit):
    emit_coverage(SHW.rules(vintage)["article_coverage"], audit)
