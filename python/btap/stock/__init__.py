"""Derive a stock recipe from an existing model — the recipe WRITER (#196).

phylroy's ask: generate recipes from the existing files, so the 28 hand-built
campus archetypes can seed a recipe library instead of it being authored from
guesses. The scope is the UNION of two external ECM field sets — all the
values for all the ECMs in `canmet-energy/campus` and the items in
`canmet-energy/osruby` — enumerated in
`docs/reference/ecm_field_inventory.json` and derived by
`scripts/fetch_ecm_field_inventory.py` rather than transcribed.

Four rules hold across every section, and they are what make the output
trustworthy rather than merely plausible:

**GENERIC, not exhaustive.** phylroy's constraint: "average wall R-value
rather than capturing all the surface R-values". A recipe is a build
SPECIFICATION — an exhaustive per-surface dump is a second copy of the model
and cannot be applied to different geometry, which defeats the purpose. So one
value per assembly class, per space type, per plant.

**ABSENT, never defaulted.** A value the writer cannot read is omitted and
listed under the section's `unreadable`. A recipe that quietly fills in a
plausible number is worse than one that says it does not know, because the
reader cannot tell the two apart. This is why the section readers here do NOT
reuse `envelope.constructions.fenestration_solar_transmittance`, which falls
back to 0.60 — correct when APPLYING a construction, a fabrication when
reading one.

**Every aggregate carries its SPREAD.** A single number summarising a wide
distribution is trusted more than it deserves, so each aggregated field
records how many objects it came from, their total area, and the min/max
ratio. A reader can then see that a 1.00x spread makes the average exact and
a 3.4x spread makes it a lossy summary.

**Nothing is INVENTED, above all not a system name.**
`hvac/classify.py::characterize` leaves `catalog_name` null for a model it
does not recognise — measured on the campus archetypes, null for all 25 zone
groups — and that is the classifier being correct: it resolves the air loop's
NAME against the catalogue, and structural identification cannot substitute
because, in its own words, "the facts a classifier needs here are DESTROYED by
the time the coil scan runs". A recipe naming a catalogue system the source
model is not would build something that silently differs from the original.
Unresolved systems are emitted as unresolved.
"""

from __future__ import annotations

from btap.stock.controls import controls_section
from btap.stock.envelope import envelope_section
from btap.stock.equipment import equipment_section
from btap.stock.hvac import hvac_section
from btap.stock.identify import identify_candidates, suggest
from btap.stock.loads import loads_section
from btap.stock.reader import RecipeError, build_from_recipe
from btap.stock.space_types import space_types_section
from btap.stock.writer import write_recipe

__all__ = ['RecipeError', 'build_from_recipe',
           'identify_candidates', 'suggest',
           'controls_section', 'envelope_section', 'equipment_section',
           'hvac_section', 'loads_section', 'space_types_section',
           'write_recipe']
