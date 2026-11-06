"""Suggest catalogue systems for an unidentified zone group — as CANDIDATES.

phylroy asked to try identifying the system (2026-11-04), because without it a
recipe from a hand-built model cannot regenerate the building: HVAC drives
85.6% of site energy on `Office_pre-1960` — heating alone is 71.4% — and
`catalog_name` is null for every one of its 47 zone groups, so the reader
refuses all of them and the "round trip" rebuilds only the other 14%.

**This does not overturn the refusal rule; it supplies evidence to it.**
`classify.py` is right that structural identification cannot be made reliable:

    the facts a classifier needs here are DESTROYED by the time the coil scan
    runs [...] A real packaged unit and a field-erected built-up DX coil then
    both read as `loop_dx_cooling`, and nothing downstream can tell them
    apart.

So this never writes `catalog_name` and never makes a group `resolved`. It
returns a RANKED list of candidates, each with the facts that matched and the
facts that did not, and the caller decides. A candidate that is built is
audited as a candidate.

**The catalogue already contains six `origin: campus` systems** — "Hot water
unit heaters", "PSZ MAU Hot Water with water-heated PTAC", "Shared hot water
heating-only air handler", "Shared furnace with DX cooling and no outdoor
air", "Shared hot water air handler with water reheat" and "Recirculating CRAH
chilled water with humidity control". Someone curated those from the campus
project, and they map almost one-to-one onto the Office archetype's
signatures, which is why this is worth attempting at all rather than scoring
blind.
"""

from __future__ import annotations

from btap.modeling.hvac import catalog

#: `family_guess` from `classify.py` -> the catalogue families that could
#: realise it. Deliberately WIDE: narrowing happens on the facts below, and a
#: family omitted here can never be suggested, which is the worse error.
FAMILY_CANDIDATES = {
    'unconditioned': (),
    'zonal_heating_only': ('baseboards', 'unit_heaters'),
    'zonal_heat_cool': ('mau_ptac', 'fan_coils', 'vrf', 'wshp', 'doas_pthp',
                        'zone_terminal', 'composite'),
    'central_doas_or_cv': ('furnace', 'psz', 'doas', 'evap_cooler',
                           'composite'),
    'packaged_single_zone': ('psz', 'furnace', 'composite'),
    # 'furnace' belongs here: in this catalogue that family covers SHARED AIR
    # HANDLERS, and the campus row 'Shared hot water air handler with water
    # reheat' carries `reheat: 'Hot Water'` while sitting under `furnace`. A
    # mapping that admitted only `vav_reheat` excluded it by FAMILY before any
    # fact was scored — so the row built for a multizone reheat system could
    # never be proposed for one. My own test caught this.
    'multizone_vav': ('vav_reheat', 'dual_duct', 'furnace', 'composite'),
    # `composite` is on every shape that can be LAYERED, and the reason is
    # structural: a `composite` row is a LOOP PLUS ZONE EQUIPMENT on the same
    # zones, which is what 5 of the 47 groups in `Office_pre-1960` actually
    # are (a rooftop unit for ventilation and cooling, hot-water baseboards
    # under the windows). `build_system` has always built them correctly —
    # `teardown.remove_hvac_from_zones` runs ONCE at the top and each part
    # then layers on, because the recursive call does not pass
    # `remove_existing` — and all 12 shipped composites are exactly this shape
    # ('Residential AC with baseboard electric' is
    # `furnace(heating=False) + baseboards`).
    #
    # They were reachable from NO group shape, measured: 0 composite
    # candidates out of 27/25/32/25 for the four shapes above. The mechanism
    # that solves layering was built, tested and shipped, and the identifier
    # never offered it.
}

#: A zonal unit the classifier saw -> the catalogue family or attribute it
#: implies. `None` means the kind is carried as an ATTRIBUTE of a bigger row
#: (`baseboard_type`) rather than by a family of its own.
_ZONAL_FAMILY = {'unit_heater': 'unit_heaters', 'ptac': 'mau_ptac',
                 'baseboard': None}

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
_ZONAL_UNIT_FAMILY = {
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


def _fuel_tokens(energy_types):
    """Normalise `['NaturalGas']` to the words catalogue fields use."""
    out = set()
    for fuel in energy_types or ():
        lowered = str(fuel).lower()
        if 'gas' in lowered or 'propane' in lowered:
            out.add('gas')
        elif 'electric' in lowered:
            out.add('electric')
        elif 'district' in lowered or 'steam' in lowered:
            out.add('district')
        elif 'oil' in lowered or 'diesel' in lowered:
            out.add('oil')
    return out


def facts_terminal(group):
    """The group's terminal type, from either a raw or wrapped fact dict."""
    return group.get('terminal_type')



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
_BUILDER_COIL_DEFAULTS = {
    'furnace': 'Gas',
    'unit_heaters': 'Gas',
    'fan_coils': 'Gas',
    'doas': 'Electric',
    'mau_ptac': 'Electric',
    'zone_terminal': 'None',
}




def _composite_shape(row, _depth=0):
    """A composite's `(part families, zone-equipment kinds)`.

    Zone-equipment kinds are named in the VOCABULARY `classify` uses for
    `zonal_units` ('baseboard', 'ptac', 'unit_heater'), so the two can be
    compared directly. A part is zone equipment when its family maps to one of
    those, or when it carries a `baseboard_type` that is not 'None' — a PSZ
    part bundling baseboards serves the zones just as a separate baseboard
    part does, and reading only the family would miss it.
    """
    if _depth > 3:
        return frozenset(), frozenset()
    families, zonal = set(), set()
    for part in row.get('parts') or ():
        try:
            base = dict(catalog.resolve(part['name']))
        except (KeyError, ValueError):
            continue
        base.update(part.get('config') or {})
        family = str(base.get('family') or '')
        families.add(family)
        if family == 'composite':
            sub_f, sub_z = _composite_shape(base, _depth + 1)
            families |= sub_f
            zonal |= sub_z
            continue
        for unit, unit_family in _ZONAL_UNIT_FAMILY.items():
            if unit_family is not None and family == unit_family:
                zonal.add(unit)
        bb = base.get('baseboard_type')
        if bb is not None and str(bb) != 'None':
            zonal.add('baseboard')
    return frozenset(families), frozenset(zonal)

def _row_heating_media(row, _depth=0):
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
        return frozenset()

    if row.get('family') == 'composite' and row.get('parts'):
        media = set()
        for part in row['parts']:
            try:
                base = dict(catalog.resolve(part['name']))
            except (KeyError, ValueError):
                continue
            base.update(part.get('config') or {})
            if base.get('heating') is False:
                continue      # this part's air handler does not heat
            media |= _row_heating_media(base, _depth + 1)
        return frozenset(media)

    # A heat-pump coil heats with refrigerant whatever fuel backs it up, so
    # this is tested BEFORE the coil fields: a row carrying both `heat_source`
    # and `supp_htg_fuel: 'Gas'` is a heat pump, not a gas furnace.
    if row.get('heat_source'):
        return frozenset({'refrigerant'})

    name = (row.get('heating_coil_type') or row.get('heating_type')
            or row.get('mau_heating_coil_type'))
    if name is None:
        name = _BUILDER_COIL_DEFAULTS.get(str(row.get('family') or ''))
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

def _score(row, group):
    """Score one catalogue row against one zone group's facts.

    Returns ``(score, matched, against)`` where `matched` are the facts that
    agreed and `against` the facts that did not. A disagreement does NOT
    disqualify — it lowers the score and is reported, because the facts
    themselves are partly structural guesses and a hard filter on a guess
    would silently discard the right answer.
    """
    matched, against = [], []
    score = 0.0

    heat = _fuel_tokens(group.get('heating_energy_types'))
    cool = _fuel_tokens(group.get('cooling_energy_types'))
    zonal = set(group.get('zonal_units') or ())
    family = row.get('family')

    # The family is the strongest single signal, and it is already filtered by
    # the caller, so agreement here is assumed rather than scored.

    for unit in zonal:
        implied = _ZONAL_FAMILY.get(unit)
        if implied is None:
            continue
        if family == implied:
            score += 3.0
            matched.append(f'zonal unit {unit!r} implies family {implied!r}')

    # TWO FIELD VOCABULARIES, and reading only one made the campus rows
    # unreachable. The NECB-shaped rows describe an air handler by
    # `heating_coil_type` and `baseboard_type`; the six `origin: campus` rows —
    # added by #152 explicitly "for reconstructing the Campus models" — use
    # `heating`, `cooling`, `heating_type`, `cooling_type`, `ventilation`,
    # `reheat`, `per_zone`, `mau_heating_coil_type` and `ptac_heating_type`
    # instead, and carry NO `baseboard_type` at all because in that
    # reconstruction the baseboards are separate zone equipment with their own
    # catalogue row.
    #
    # A scorer that read only the NECB names therefore saw nothing informative
    # on a campus row and then PENALISED it for the missing baseboard field —
    # so 'Shared furnace with DX cooling and no outdoor air', the row built for
    # exactly this group, did not reach the top eight while
    # 'PSZ RTU Gas and DX Coils and Hot Water Baseboard' led at 6.00.
    uses_baseboard_field = 'baseboard_type' in row
    if 'baseboard' in zonal:
        baseboard = row.get('baseboard_type')
        if baseboard in ('Hot Water', 'Electric'):
            score += 2.0
            matched.append(f'baseboard present; row has {baseboard!r}')
            if baseboard == 'Hot Water' and 'gas' in heat:
                score += 1.0
                matched.append('hot-water baseboard with gas heating')
            elif baseboard == 'Electric' and 'electric' in heat:
                score += 1.0
                matched.append('electric baseboard with electric heating')
        elif baseboard == 'None':
            score -= 1.5
            against.append('baseboard present but row has none')
        elif not uses_baseboard_field:
            # MY RATIONALE HERE WAS FALSE. I wrote that silence was not
            # disagreement "because the group's baseboards come from their own
            # row" — but `reader._build_hvac` builds exactly ONE system per
            # group with `remove_existing=True`, and nothing builds the
            # baseboards afterwards. So picking a row that carries none DROPS
            # them silently. Until the reader can build a second row for the
            # zonal equipment, a row without baseboards is a real loss for a
            # group that has them, and it is scored as one.
            score -= 1.0
            against.append(
                'this row carries no baseboards and the reader builds ONE '
                'system per group, so the group\'s baseboards would be '
                'dropped — not merely unmodelled by this row')
    elif row.get('baseboard_type') in ('Hot Water', 'Electric'):
        score -= 1.0
        against.append(f"row has {row['baseboard_type']!r} baseboard, "
                       'none seen in the group')

    # The campus vocabulary's own facts.
    if row.get('heating') is True and heat:
        score += 1.0
        matched.append('row heats; group heats')
    elif row.get('heating') is False and heat:
        score -= 2.0
        against.append(f'row does NOT heat but the group heats with '
                       f'{sorted(heat)}')
    loop_cools = group.get('loop_dx_cooling') is True
    zonal_cools = bool(cool) and not loop_cools
    row_cools = bool(row.get('cooling') is True
                     or row.get('cooling_type')
                     or row.get('needs_chiller')
                     or row.get('chiller_type')
                     or 'psz' in str(row.get('family') or '')
                     or 'DX' in str(row.get('name') or ''))
    if zonal_cools and row_cools and not row.get('ptac_heating_type'):
        score -= 2.5
        against.append(
            'the GROUP is cooled only by zonal equipment '
            f'({", ".join(sorted(zonal)) or "zone units"}) — its loop has no '
            'cooling coil — but this row puts cooling on the air handler')
    elif loop_cools and row_cools:
        score += 1.0
        matched.append('the loop cools and this row cools the loop')
    elif loop_cools and not row_cools:
        score -= 2.0
        against.append('the loop has DX cooling; this row does not cool the '
                       'air handler')

    # The same union problem on the other branch: a row that does NOT cool is
    # CORRECT for a group whose cooling is zonal, and penalising it there was
    # how `Shared hot water heating-only air handler` — the right air handler
    # for the four-zone loop — scored 2.25 and never reached the top eight.
    if row.get('cooling') is True:
        if loop_cools:
            score += 1.5
            matched.append('row cools; the loop cools')
        elif zonal_cools:
            pass        # already scored by the loop/zonal test above
        else:
            score -= 1.0
            against.append('row cools but the group is not cooled')
    elif row.get('cooling') is False:
        if loop_cools:
            score -= 2.0
            against.append('row does NOT cool but the loop has DX cooling')
        elif zonal_cools:
            score += 2.0
            matched.append(
                'row does not cool the air handler, and neither does the '
                'group — its cooling is zonal')

    if row.get('reheat'):
        if facts_terminal(group) == 'vav_reheat':
            score += 2.5
            matched.append(f"row has {row['reheat']!r} reheat terminals; "
                           'group terminal is vav_reheat')
        else:
            score -= 1.0
            against.append(f"row has reheat terminals; group terminal is "
                           f'{facts_terminal(group)!r}')
    # FIX: `ventilation_sized` does NOT mean "has outdoor air". Confirmed
    # independently by two agents: it is true only when `SizingSystem` is
    # `VentilationRequirement` with all-OA sizing — i.e. "this is a DOAS whose
    # coil tempers make-up air". The fact that encodes OA PRESENCE is
    # `system_outdoor_air_method`: a string when an OA controller exists, None
    # when none does. The old test therefore penalised a no-OA row only
    # against a DOAS, never against an ordinary mixed-air loop — so
    # 'Shared furnace with DX cooling and no outdoor air' was never marked
    # down for the Gagetown loops, which all carry real ventilating OA with
    # autosized DSOA minimums and an economizer. Building it would DELETE both,
    # and the reader cannot restore the economizer because
    # `set_economizer_in_model` skips a loop with no controller.
    group_has_oa = group.get('system_outdoor_air_method') is not None
    if row.get('ventilation') is False:
        if group_has_oa:
            score -= 3.0
            against.append(
                'this row builds NO outdoor-air system, but the group has one '
                f"({group['system_outdoor_air_method']}) — building it would "
                'delete the ventilation and the economizer with it')
        else:
            score += 1.0
            matched.append('neither the row nor the group has outdoor air')
    elif row.get('ventilation') is True and not group_has_oa:
        score -= 1.0
        against.append('row builds an outdoor-air system; the group has none')

    if group.get('ventilation_sized') and row.get('family') in (
            'doas', 'doas_pthp', 'mau_ptac'):
        score += 1.0
        matched.append('group is ventilation-sized; row is a DOAS/MAU family')

    # A COIL MEDIUM IS NOT A FUEL, and conflating them inverted this test.
    # Measured: the `vav_reheat` family has NO gas coil at all — 12 rows are
    # 'Hot Water' and 8 'Electric' — because a reheat coil is hydronic or
    # electric and gas reaches it THROUGH A BOILER. A first version asked
    # whether the coil string contained the fuel word, so for a gas-heated
    # building the correct hot-water rows were penalised exactly like the wrong
    # electric ones, and electric won on name order. A hot-water coil fed by a
    # gas boiler is a gas-heated system.
    # One medium, three spellings across the two vocabularies.
    coil_name = (row.get('heating_coil_type') or row.get('heating_type')
                 or row.get('mau_heating_coil_type'))
    coil = str(coil_name or '').lower()
    # Fuels that can fire a boiler, and therefore agree with a hydronic coil.
    boiler_fuels = {'gas', 'oil', 'district'}
    if coil and heat:
        if 'electric' in coil:
            if 'electric' in heat:
                score += 2.0
                matched.append("electric heating coil matches electric "
                               "heating")
            else:
                score -= 1.5
                against.append(f'electric heating coil against {sorted(heat)} '
                               '— no boiler can feed it')
        elif 'water' in coil or 'steam' in coil:
            if heat & boiler_fuels:
                score += 2.0
                matched.append(f'{coil_name!r} coil fed by a '
                               f'{sorted(heat & boiler_fuels)} boiler')
            elif 'electric' in heat:
                # An electric boiler is legal but unusual; mildly against.
                score -= 0.5
                against.append(f'{coil_name!r} coil with '
                               'electric-only heating implies an electric '
                               'boiler')
        elif 'gas' in coil:
            if 'gas' in heat:
                score += 2.0
                matched.append('gas heating coil matches gas heating')
            else:
                score -= 1.5
                against.append(f'gas heating coil against {sorted(heat)}')

    # THE BOILER'S OWN FUEL, which is the field that breaks the tie that cost
    # 75,600 kWh. 'Baseboard gas boiler' and 'Baseboard district hot water'
    # both scored 3.50 on baseboard medium alone, so the alphabetical sort
    # picked DISTRICT for a NaturalGas building — and the generated model
    # carried 75,600 kWh of district heating the original does not use at all.
    # Nine catalogue rows declare `boiler_fuel` and one declares
    # `hw_source: district`; both were being ignored.
    boiler_fuel = _fuel_tokens([row.get('boiler_fuel')]
                               if row.get('boiler_fuel') else [])
    if boiler_fuel and heat:
        if boiler_fuel & heat:
            score += 2.5
            matched.append(f"boiler fuel {row['boiler_fuel']!r} matches "
                           f'{sorted(heat)}')
        else:
            score -= 2.0
            against.append(f"boiler fuel {row['boiler_fuel']!r} against "
                           f'{sorted(heat)}')

    # A district source is a different PLANT, not a different efficiency, so
    # proposing one for a building that fires its own boiler introduces an
    # energy stream the original has none of.
    if row.get('hw_source') == 'district':
        if 'district' in heat:
            score += 2.5
            matched.append('district hot water matches district heating')
        else:
            score -= 3.0
            against.append(
                f'row is DISTRICT hot water but the group heats with '
                f'{sorted(heat) or "nothing"} — this would introduce a '
                'purchased-heat stream the building does not have')
    if row.get('chw_source') == 'district' and 'district' not in cool:
        score -= 3.0
        against.append('row is district chilled water; the group is not')

    if row.get('needs_boiler') and heat & {'gas', 'oil', 'district'}:
        score += 0.5
        matched.append(f'row needs a boiler; group heats with {sorted(heat)}')
    elif row.get('needs_boiler') and heat:
        score -= 0.5
        against.append(f'row needs a boiler; group heats with {sorted(heat)}')

    # FIX: `cooled` is a UNION of loop and zonal cooling, and treating it as
    # loop cooling gave a DX rooftop to a loop with no cooling coil at all.
    # Measured on `Office_pre-1960`'s four-zone loop: supply path is OA system
    # -> Coil:Heating:Water -> CV fan, NO cooling coil, and its
    # `cooling_energy_types: ['Electricity']` comes from two zonal PTACs.
    # `loop_dx_cooling` is the fact that says whether the LOOP cools, and the
    # scorer never read it.
    # THE PRIMARY ERROR, named independently by two agent reads (2026-11-04).
    # `heating_energy_types` is the fuel resolved THROUGH the plant, so every
    # Gagetown central loop reads ['NaturalGas'] while its coil is a
    # `Coil:Heating:Water` — measured, all four loops: fuel=['NaturalGas'],
    # media=['hydronic']. Scoring the fuel alone let a direct-gas burner take
    # +2.0 for "gas coil matches gas heating" on a hydronic model, which is how
    # a row that substitutes the heating MEDIUM could win.
    media = set(group.get('supply_heating_media') or ())
    row_media = _row_heating_media(row)
    if media and row_media:
        shared = media & row_media
        if shared:
            score += 2.0
            matched.append('the loop heats with a '
                           f"{'/'.join(sorted(shared))} coil and so does "
                           'this row')
        else:
            score -= 2.5
            against.append(
                f"the loop's own heating coil is {'/'.join(sorted(media))}, "
                'but this row heats the air handler with '
                f"{'/'.join(sorted(row_media))} — that substitutes the "
                'heating MEDIUM, not just the equipment')

    # A composite carries almost no fields of its own: its behaviour is in
    # `parts`. Scoring it on absent fields would mark it down for every fact
    # it delegates, so the parts are inspected for the two that decide
    # layering — does anything cool, and does anything serve the zones.
    #
    # MERGING the parts' fields into one effective row was tried and REVERTED
    # (2026-11-04). It works mechanically — nine fields gained — but the
    # catalogue keeps loop-side and zone-side coils in one namespace
    # (`mau_heating_coil_type` beside `heating_type` and `fan_coil_type`), so
    # a merged row cannot say WHICH SIDE a coil is on. The scorer then read
    # the fan coils' cooling as cooling on the air handler and the two parts'
    # coils as one confused medium, and `DOAS with fan coil chiller with
    # boiler` scored -3.5 against a group that IS a DOAS loop with fan coils,
    # on three objections that were all false.
    #
    # Scoring a composite on its parts therefore needs the facts and the row
    # fields SPLIT by side — loop coil vs zone coil — which is a change to the
    # scoring model, not a merge. Until then a composite earns the layering
    # credit below and nothing from the field checks, so it is reachable and
    # honestly ranked rather than confidently wrong.
    if row.get('family') == 'composite' and row.get('parts'):
        part_families, part_zonal = _composite_shape(row)
        if zonal and part_zonal:
            shared_zonal = zonal & part_zonal
            if shared_zonal:
                score += 2.5
                matched.append(
                    'the group is served by '
                    f"{'/'.join(sorted(shared_zonal))} at the zone AND this "
                    'row builds it as a part, so it is not dropped')
            else:
                score -= 1.0
                against.append(
                    f"the group has {'/'.join(sorted(zonal))} at the zone; "
                    f"this row's parts build {'/'.join(sorted(part_zonal))}")
        elif zonal and not part_zonal:
            score -= 1.0
            against.append('this row builds no zone equipment, so the '
                           f"group's {'/'.join(sorted(zonal))} would be "
                           'dropped')
        if loop_cools and 'evap_cooler' in part_families:
            score -= 1.5
            against.append('the loop has DX cooling; this row cools '
                           'evaporatively, which is a different machine')

    # Heat recovery, #214. Two rows can differ ONLY by this
    # (`PVAV with gas boiler reheat` and `... and plate HRV`), so a scorer
    # blind to it picks by tie-break — and it picked the HRV variant for a
    # loop carrying no heat exchanger, adding a device worth 48.64 GJ/yr of
    # recovery to a building that has none.
    #
    # Asymmetric deliberately. Building recovery a loop has no evidence of
    # adds equipment to the model, so it is marked down. The reverse —
    # omitting recovery the loop HAS — is a smaller fidelity loss and the
    # catalogue may carry no equivalent row with it, so it is reported rather
    # than punished as hard.
    row_recovers = bool(row.get('needs_erv'))
    group_recovers = group.get('loop_heat_recovery') is True
    if row_recovers and not group_recovers:
        score -= 2.5
        against.append('this row builds HEAT RECOVERY, but the loop carries '
                       'no air-to-air heat exchanger — that adds a device the '
                       'building does not have')
    elif row_recovers and group_recovers:
        score += 2.0
        matched.append('the loop recovers heat and so does this row')
    elif group_recovers and not row_recovers:
        score -= 1.0
        against.append('the loop recovers heat; this row does not')

    cooling_medium = str(row.get('cooling_type') or '').lower()
    if cool and cooling_medium:
        score += 1.0
        matched.append(f'row cooling type {row["cooling_type"]!r}')
    if cool:
        if row.get('needs_chiller') or row.get('chiller_type'):
            score += 0.5
            matched.append('group is cooled; row carries a chiller')
        elif 'electric' in cool:
            score += 0.5
            matched.append('group cools electrically; row is DX-capable')
    elif row.get('needs_chiller'):
        score -= 1.0
        against.append('row needs a chiller; group is not cooled')

    # Provenance, as a TIEBREAK and nothing more. Six rows carry
    # `origin: campus` and were curated from the project these archetypes come
    # from, so they are a better first guess for a campus model — but a
    # provenance tag is not evidence about the equipment, so it cannot
    # outweigh a fact.
    if row.get('origin') == 'campus':
        score += 0.25
        matched.append("row origin is 'campus' (tiebreak only)")

    return score, matched, against


def identify_candidates(group, *, limit=3):
    """Ranked catalogue candidates for one zone group's descriptive facts.

    :param group: a zone group from `hvac_section`, resolved or not. A group
        that is already resolved returns no candidates — there is nothing to
        guess.
    :returns: a list of ``{'system', 'family', 'score', 'matched',
        'against'}``, best first, or ``[]`` when the group is unconditioned or
        no family could be proposed.
    """
    if group.get('resolved'):
        return []
    facts = group.get('descriptive') or group
    guess = facts.get('family_guess')
    families = FAMILY_CANDIDATES.get(guess)
    if not families:
        return []

    scored = []
    for row in catalog.rows():
        if row.get('family') not in families:
            continue
        score, matched, against = _score(row, facts)
        scored.append({'system': row.get('name'), 'family': row.get('family'),
                       'origin': row.get('origin'), 'score': round(score, 2),
                       'matched': matched, 'against': against})
    scored.sort(key=lambda c: (-c['score'], c['system'] or ''))
    return scored[:limit]


def suggest(section, *, limit=3):
    """Add `candidates` to every unresolved group of an `hvac_section`.

    The section is returned CHANGED IN PLACE for convenience, but nothing is
    marked resolved and no `system` key is written: a candidate stays a
    candidate until something outside this module accepts it.
    """
    for group in section.get('zone_groups', []):
        if group.get('resolved'):
            continue
        candidates = identify_candidates(group, limit=limit)
        group['candidates'] = candidates
        group['candidate_note'] = (
            'RANKED GUESSES, not identifications. classify.py establishes '
            'that structural identification cannot be made reliable because '
            'the facts needed are destroyed before the coil scan runs. Each '
            'candidate carries what matched and what did not; a caller must '
            'accept one explicitly, and building from it is audited as a '
            'candidate.' if candidates else
            'no candidate: the group is unconditioned, or its family_guess '
            'proposes no catalogue family.')
    return section
