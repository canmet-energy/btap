"""NECB 2025 — the modules that exist only in this edition.

- ``eui_archetypes``: the 8.4.4 Energy Use Intensity path (archetype mapping,
  applicability, the Table 8.4.4.2 conformance check and normalization, and
  the archetype building energy target).
- ``part11_ghg``: the Part 11 operational-GHG performance levels.

Both were carved out of ``btap.codes.necb.tiers`` unchanged; ``tiers`` keeps
only the Section 10 energy tiers, which are identical in 2020 and 2025 and are
therefore shared, not bound.

``data/necb2025/manifest.json`` binds these two under the behaviour names
``archetype_eui_path`` and ``part11_ghg``; ``compliance.py`` reaches them only
through :meth:`btap.codes.Ruleset.behaviour` and never imports this package.
"""
