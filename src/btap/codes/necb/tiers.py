"""Post-comparison scoring (port of btap-necb's tiers.rb): Section 10 energy
performance tiers (Table 10.1.2.1, verified IDENTICAL in 2020 and 2025).

The two 2025-only halves of the original module now live beside the edition
they belong to: the 8.4.4 archetype-EUI building energy target in
``btap.codes.necb.editions.necb2025.eui_archetypes`` and the Part 11
operational-GHG performance levels in
``btap.codes.necb.editions.necb2025.part11_ghg``."""

from __future__ import annotations

from btap._compat import NullAudit, ruby_div, ruby_round


def energy_tier(proposed_kwh, target_kwh, audit=None):
    """Table 10.1.2.1: Tier 1 <= 100%, Tier 2 <= 75%, Tier 3 <= 50%,
    Tier 4 < 40% of the building energy target.
    :return: {'percent_of_target':, 'tier': int|None}"""
    audit = audit or NullAudit()
    percent = ruby_div(100.0 * proposed_kwh, target_kwh)
    if percent < 40.0:
        tier = 4
    elif percent <= 50.0:
        tier = 3
    elif percent <= 75.0:
        tier = 2
    elif percent <= 100.0:
        tier = 1
    else:
        tier = None
    audit.decision(
        "compliance",
        f"energy performance Tier {tier} achieved" if tier
        else "no energy performance tier achieved (over the target)",
        inputs={"percent_of_target": ruby_round(percent, 1),
                "improvement_percent": ruby_round(100.0 - percent, 1)},
        article="10.1.2.1. (Table verified identical 2020/2025)")
    return {"percent_of_target": ruby_round(percent, 1), "tier": tier}
