"""Assemble the sections into one recipe."""

from __future__ import annotations

from btap.modeling.recipe.controls import controls_section
from btap.modeling.recipe.envelope import envelope_section
from btap.modeling.recipe.equipment import equipment_section
from btap.modeling.recipe.hvac import hvac_section
from btap.modeling.recipe.loads import loads_section
from btap.modeling.recipe.space_types import space_types_section

SCHEMA = 1


def write_recipe(model, *, building_type=None, vintage=None, source=None,
                 audit=None):
    """A recipe derived from ``model``.

    :param building_type: the recipe's building type, e.g. 'Office'. Carried
        as given — NOT inferred from the model, because a model does not
        record what building type its author meant and guessing one would put
        an invented label on real values.
    :param vintage: likewise, e.g. 'pre-1960'.
    :param source: where the values came from, normally the OSM path. A
        recipe without this cannot be checked against its origin.
    """
    recipe = {
        'schema': SCHEMA,
        'building_type': building_type,
        'vintage': vintage,
        'source': source,
        'space_types': space_types_section(model, audit=audit),
        'envelope': envelope_section(model, audit=audit),
        'loads': loads_section(model, audit=audit),
        'controls': controls_section(model, audit=audit),
        'equipment': equipment_section(model, audit=audit),
        'hvac': hvac_section(model, audit=audit),
    }
    if audit is not None:
        audit.info('recipe', 'recipe written',
                   inputs={'building_type': building_type,
                           'vintage': vintage, 'source': source,
                           'sections': sorted(
                               k for k in recipe
                               if k not in ('schema', 'building_type',
                                            'vintage', 'source'))})
    return recipe
