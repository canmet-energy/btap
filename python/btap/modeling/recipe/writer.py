"""Assemble the sections into one recipe."""

from __future__ import annotations

from btap.modeling.recipe.controls import controls_section
from btap.modeling.recipe.envelope import envelope_section
from btap.modeling.recipe.equipment import equipment_section
from btap.modeling.recipe.hvac import hvac_section
from btap.modeling.recipe.loads import loads_section
from btap.modeling.recipe.space_types import space_types_section

SCHEMA = 1


def write_recipe(model, *, building_type=None, vintage_name=None,
                 source=None, suggest_systems=False, audit=None):
    """A recipe derived from ``model``.

    :param building_type: the recipe's building type, e.g. 'Office'. Carried
        as given — NOT inferred from the model, because a model does not
        record what building type its author meant and guessing one would put
        an invented label on real values.
    :param vintage_name: likewise, e.g. 'pre-1960'.

        NOT `vintage=`. CLAUDE.md retires `vintage` as a parameter name
        everywhere and `tests/test_no_vintage_parameter.py` enforces it: that
        spelling was the pre-D-87 name for the NECB EDITION selector, which is
        now `code=`/`edition=`. A stock recipe's vintage is a different thing
        — a building AGE cohort — so neither of those is the right rename, and
        the gate's own message says to rename rather than allowlist.
        `vintage_name` is osruby's own column name for exactly this quantity,
        so it disambiguates and matches upstream.
    :param source: where the values came from, normally the OSM path. A
        recipe without this cannot be checked against its origin.
    :param suggest_systems: add ranked catalogue CANDIDATES to each unresolved
        HVAC group. Off by default — see the note at the call site.
    """
    recipe = {
        'schema': SCHEMA,
        'building_type': building_type,
        'vintage_name': vintage_name,
        'source': source,
        'space_types': space_types_section(model, audit=audit),
        'envelope': envelope_section(model, audit=audit),
        'loads': loads_section(model, audit=audit),
        'controls': controls_section(model, audit=audit),
        'equipment': equipment_section(model, audit=audit),
        'hvac': hvac_section(model, audit=audit),
    }
    if suggest_systems:
        # OFF by default, deliberately. A default recipe carries no system
        # candidates, so the reader's refusal of an unresolved group stands
        # unless a caller explicitly asks for guesses and explicitly accepts
        # one. Turning this on by default would make a guess look like a
        # finding to anyone who did not read the flag.
        from btap.modeling.recipe.identify import suggest
        suggest(recipe['hvac'])
    if audit is not None:
        audit.info('recipe', 'recipe written',
                   inputs={'building_type': building_type,
                           'vintage_name': vintage_name,
                           'source': source,
                           'sections': sorted(
                               k for k in recipe
                               if k not in ('schema', 'building_type',
                                            'vintage_name', 'source'))})
    return recipe
