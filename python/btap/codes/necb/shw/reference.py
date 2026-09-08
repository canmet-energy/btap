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
from btap.codes import Ruleset
from btap.codes.necb.shw import efficiency as Efficiency


def reference_shw(model, *, vintage="2020", audit=None):
    return _reference_shw(model, Ruleset.from_edition(vintage), audit=audit)


def _reference_shw(model, ruleset, audit=None):
    """The 8.4.x.20 SHW reference against ONE resolved edition (Stage 6)."""
    audit = audit if audit is not None else AuditLog()
    prefix = ruleset.article("reference_subsection")
    heaters = sorted_by_name(model.getWaterHeaterMixeds())
    audit.info("shw_reference",
               "reference SWH storage capacity, power input and energy type identical to "
               "proposed by construction (clone; no transform touches SWH sizing or fuel)",
               inputs={"water_heaters": len(heaters)}, article=f"{prefix}.20.(1)")
    for heater in heaters:
        Efficiency._apply_efficiency(heater, ruleset, audit=audit)
    # Table 6.2.2.1 solar-thermal + pool-heater rows (D-63): apply-when-present.
    Efficiency._apply_solar_pool_minimums(model, ruleset, audit=audit)
    _emit_article_coverage(ruleset, audit)
    return audit


def _emit_article_coverage(ruleset, audit):
    emit_coverage(ruleset.rules("shw")["article_coverage"], audit)
