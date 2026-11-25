"""Facts about a catalogue ROW, read from its config and its builder's defaults.

Moved down from `btap.stock.identify` so the modeling layer's taxonomy can use
them: `btap.modeling` may not import `btap.stock`. `identify` re-imports them.

Unlike their first home, these RAISE on a composite part that does not
resolve or on runaway nesting. They feed catalogue naming now, and a fact that
silently dropped a part would name a system for equipment it does not build
(Astra, HVAC taxonomy review finding 5).
"""

from __future__ import annotations

from btap.modeling.hvac import catalog


class CatalogFactError(ValueError):
    """A catalogue row whose facts cannot be read — a defect in the catalogue."""


def _resolve_part(part):
    # Composite parts reference rows by `id` since the HVAC taxonomy; `name` is
    # accepted for a config written before it.
    key = part.get('id') or part.get('name')
    try:
        return catalog.resolve(key)
    except (KeyError, ValueError, TypeError) as exc:
        raise CatalogFactError(
            f"composite part {key!r} does not resolve: {exc}") from exc


#: The COMPLETE `zonal_units` vocabulary `classify.py` can emit, mapped to the
#: catalogue family that builds it. Complete on purpose: `_ZONAL_FAMILY` above
#: covers three of the ten kinds, and using it to judge a composite's parts
#: silently under-credited every DOAS+fan-coil, DOAS+VRF and DOAS+WSHP row —
#: 10 of the 12 shipped composites — because their zone equipment mapped to
#: nothing. Mapped to `None` where the catalogue genuinely has no family:
#: a radiant panel, a unit ventilator and a zone ERV are not buildable from a
#: row today, so claiming a family for them would be a guess.
#: Kinds come from the `'kind'` field of classify's zone-equipment table;
#: `tests/stock/test_identify.py` re-reads that table and fails if a kind is
#: added without being mapped here.
ZONAL_UNIT_FAMILY = {
    'baseboard': 'baseboards',
    'evap_cooler': 'evap_cooler',
    'fan_coil': 'fan_coils',
    'ptac': 'mau_ptac',
    'pthp': 'doas_pthp',
    'radiant': None,
    'unit_heater': 'unit_heaters',
    'unit_ventilator': None,
    'vrf_terminal': 'vrf',
    'wshp': 'wshp',
}


# A row that OMITS its coil field is NOT silent when its builder supplies a
# default. `furnace.py` is `self.config.get('heating_type', 'Gas')`, so a
# furnace row with no `heating_type` BUILDS a combustion coil — reading it as
# "no claim" let the medium substitution this guards against back in one field
# over, which is how 'Shared furnace with DX cooling and no outdoor air'
# escaped the check on first measurement.
#
# Mirrored from the builders and pinned by
# `test_identify.py::test_the_builder_coil_defaults_match_this_table`, which
# re-reads each builder's source and FAILS if a default moves. `psz` and
# `vav_reheat` take no default, so silence there is genuine silence.
BUILDER_COIL_DEFAULTS = {
    'furnace': 'Gas',
    'unit_heaters': 'Gas',
    'fan_coils': 'Gas',
    'doas': 'Electric',
    'mau_ptac': 'Electric',
    'zone_terminal': 'None',
}


def composite_shape(row, _depth=0):
    """A composite's `(part families, zone-equipment kinds)`.

    Zone-equipment kinds are named in the VOCABULARY `classify` uses for
    `zonal_units` ('baseboard', 'ptac', 'unit_heater'), so the two can be
    compared directly. A part is zone equipment when its family maps to one of
    those, or when it carries a `baseboard_type` that is not 'None' — a PSZ
    part bundling baseboards serves the zones just as a separate baseboard
    part does, and reading only the family would miss it.
    """
    if _depth > 3:
        raise CatalogFactError(
            f"composite {row.get('id') or row.get('name')!r} nests more than 3 levels deep")
    families, zonal = set(), set()
    for part in row.get('parts') or ():
        base = dict(_resolve_part(part))
        base.update(part.get('config') or {})
        family = str(base.get('family') or '')
        families.add(family)
        if family == 'composite':
            sub_f, sub_z = composite_shape(base, _depth + 1)
            families |= sub_f
            zonal |= sub_z
            continue
        for unit, unit_family in ZONAL_UNIT_FAMILY.items():
            if unit_family is not None and family == unit_family:
                zonal.add(unit)
        bb = base.get('baseboard_type')
        if bb is not None and str(bb) != 'None':
            zonal.add('baseboard')
    return frozenset(families), frozenset(zonal)


def row_heating_media(row, _depth=0):
    """The set of MEDIA a row's air-handler heating would use.

    A set, not one value, because a `composite` row delegates to `parts` and
    can bring more than one. Empty means the row makes no claim about medium —
    which is NOT the same as "heats with nothing", and is why the three
    non-obvious sources below are read rather than assumed:

    - a BUILDER DEFAULT, when the row omits the field (`furnace.py` defaults
      `heating_type` to 'Gas', so a silent furnace row builds combustion);
    - `heat_source`, which 8 heat-pump rows carry INSTEAD of a coil type — a
      heat-pump coil heats with refrigerant, and reading only coil fields let
      every one of them escape the medium check;
    - `parts`, for the 12 composite rows, whose own air handler may not heat
      at all (`Residential AC with baseboard electric` has `heating: False`),
      in which case the empty set is the right answer.

    Measured when this was written: of 109 catalogue rows, 24 combustion,
    22 electric, 20 hydronic, 15 refrigerant, and the remainder genuinely
    silent.
    """
    if _depth > 3:        # a malformed self-referential composite
        raise CatalogFactError(
            f"composite {row.get('id') or row.get('name')!r} nests more than 3 levels deep")

    if row.get('family') == 'composite' and row.get('parts'):
        media = set()
        for part in row['parts']:
            base = dict(_resolve_part(part))
            base.update(part.get('config') or {})
            if base.get('heating') is False:
                continue      # this part's air handler does not heat
            media |= row_heating_media(base, _depth + 1)
        return frozenset(media)

    # A heat-pump coil heats with refrigerant whatever fuel backs it up, so
    # this is tested BEFORE the coil fields: a row carrying both `heat_source`
    # and `supp_htg_fuel: 'Gas'` is a heat pump, not a gas furnace.
    if row.get('heat_source'):
        return frozenset({'refrigerant'})

    name = (row.get('heating_coil_type') or row.get('heating_type')
            or row.get('mau_heating_coil_type'))
    if name is None:
        name = BUILDER_COIL_DEFAULTS.get(str(row.get('family') or ''))
    text = str(name or '').strip().lower()
    if not text or text == 'none':
        return frozenset()
    if 'hot water' in text or 'hydronic' in text:
        return frozenset({'hydronic'})
    if 'electric' in text:
        return frozenset({'electric'})
    # ASHP/heat-pump before gas, or 'ASHP with Gas' reads as combustion.
    if 'ashp' in text or 'heat pump' in text or 'dx' in text:
        return frozenset({'refrigerant'})
    if 'gas' in text or 'furnace' in text or 'combustion' in text:
        return frozenset({'combustion'})
    return frozenset()
