"""RETIRED: the generated "canonical name" grammar.

The HVAC taxonomy (docs/plans/HVAC_TAXONOMY_PLAN.md) replaced it. Each row now
has a stable `id` and a facet-generated display name (`taxonomy.display`). The
canonical names this module used to generate are frozen into each row's
`aliases`, so they still RESOLVE; nothing generates new ones.

Its per-family branches were deleted rather than kept beside the taxonomy:
two grammars describing the same rows is the drift the taxonomy exists to end,
and one of them was wrong (it called the reference heat-pump System 1 rows
"100% OA make-up air"; the builder makes a mixed-air air handler).
"""

from __future__ import annotations


def name(row):
    """The plain-English display name — `taxonomy.display`, kept under the old
    function name so a caller of the retired grammar gets the current one."""
    from btap.modeling.hvac import taxonomy
    return taxonomy.display(row)
