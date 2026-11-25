# btap.stock

Describe an existing building as a **recipe**, then build a model from that
recipe on any geometry. It's meant for stock and retrofit work on buildings
that may never see a compliance run.

A recipe is JSON-serializable data with one value per assembly class, per
space type and per plant. It doesn't copy the model surface by surface. That
is what lets it be applied to different geometry, and it means a rebuilt model
is *representative* of its source, not a reproduction of it.

## A round trip

```python
from btap import modeling, stock
from btap.codes.necb import lighting, loads


def office(model):
    """Geometry the recipe will be applied to, with NECB space types and loads."""
    loads.assign_space_types(
        model, {s.nameString(): ["Space Function", "Office enclosed > 25 m2"]
                for s in model.getSpaces()}, code="necb2020")
    modeling.seed_constructions(model)
    loads.apply_loads(model, code="necb2020")       # also the schedules
    lighting.apply_lights(model, code="necb2020")
    return model


source = office(modeling.create(shape="l", length=40.0, width=30.0, storeys=2))
modeling.build_system(source, "psz-gas-perzone", list(source.getThermalZones()))

recipe = stock.write_recipe(source, building_type="Office")

target = office(modeling.create(shape="l", length=40.0, width=30.0, storeys=2))
account = stock.build_from_recipe(recipe, target)
account["applied"]    # what reached the model
account["skipped"]    # what did not, and why
account["refused"]    # what the reader would not do, and why
```

**Read the account.** Everything `build_from_recipe` couldn't apply is listed
in `skipped` or `refused`. When you pass `audit=`, the account is also
summarized as a warning.

## What the target must supply

The recipe holds values, not a building. The geometry is always the target's.
So is anything the recipe doesn't carry:

- **Constructions.** The envelope section adjusts an existing assembly to the
  recipe's U-value. A surface with no construction is skipped.
- **Load schedules.** The recipe carries densities, not schedules. A load
  that lands with no schedule is named in `skipped`, because EnergyPlus will
  refuse it. Give the target a schedule set first, for example with the NECB
  loads above.
- **Zone names**, for HVAC. Each HVAC group is matched to the target's thermal
  zones by name. A group whose zones aren't in the target is refused.

## HVAC: identified, or a candidate

The writer names a zone group's catalogue system only when it can identify
it, as it can for any system built with `btap.modeling.build_system`. Those
groups are rebuilt with `remove_existing=True`.

For a hand-built model it usually can't identify the system. It then records
no name, and with `suggest_systems=True` it records ranked *candidates*. The
reader refuses those groups unless you pass `accept_candidates=True`, and it
audits every system built from a candidate as a guess.

## Limits

- A rebuilt model is representative of its source for loads, envelope and
  equipment performance, and only approximately for HVAC.
- Fan pressure rise isn't captured (#202).
- Exhaust fans the source kept are orphaned when its HVAC is torn down
  (#201), so count Severe errors against the source before you trust a
  rebuilt run.
- Every aggregate in a recipe records its spread. An exact U-value match after
  a round trip shows that the averaging is stable, not that nothing was lost.

Contributor notes, and the reasoning behind each rule, are in
[`CLAUDE.md`](CLAUDE.md).
