"""Daylighting controls. ONE knob selects who gets a sensor — ``placement=``
(the older ``option=`` is a deprecated alias for it, mapped and audited in
``resolve_placement``):

  'all' (DEFAULT for add_controls) — every space with exterior
    fenestration gets a sensor regardless of any threshold (the legacy
    'add_daylighting_controls' blanket option). ReferenceDaylighting.apply
    defaults to 'necb2020' instead, because the reference building must be
    built to the code rule.

  'necb2020' — NECB 2020/2025 Article 4.2.2.1., sentences
    (10)-(15): photocontrols where the Table 4.2.1.6. column for the space
    type requires them AND the general-lighting input POWER inside the
    daylighted areas crosses 150 W / 300 W (sidelighting) or 150 W
    (toplighting), the two tested INDEPENDENTLY, with the (12)/(15)
    exceptions honoured. Areas come from DaylightedAreas (unioned polygons,
    4.2.2.3./4.2.2.4./4.2.2.5.), the requirement from
    DaylightControlRequirement. See D-57.

  'necb2011' — the legacy-exact port of model_add_daylighting_controls'
    'NECB_Default' selection, mirroring legacy AS FIXED BY #2119 (merged
    2026-07-15, in tree since the origin/nrcan merge), kept reachable so
    test_daylighting_parity.rb can still prove the port faithful. It
    applies NECB 2011 criteria (areas and effective apertures, ANDed
    within the fenestration type a space actually has) and is WRONG for
    2020/2025 — that is L-26. What is left between the two is a RULE
    difference between the editions, not a defect.
    ('necb_default' is an accepted alias.)

Sensor hardware, all paths: ONE DaylightingControl at the centre of the
space's lowest floor bounding box, 0.8 m above the floor, illuminance
setpoint from the space-type target_illuminance_setpoint, wired as the
zone's primary control. Stepped control with 3 steps on the 'necb2020' path
(4.2.2.1.(11)(a)(i) and (14)(a)(i) want one intermediate level at 50-70% of
design power, another at 20-40%, and a point that turns the lighting off;
E+ 3-step control gives exactly 67% / 33% / off), 2 steps on the legacy
paths (the NECB 2011 minimum, kept for parity).

CITATION HYGIENE: the legacy method's docstrings cite 4.2.2.7. through
4.2.2.10. Subsection 4.2.2 of NECB 2020/2025 ENDS AT ARTICLE 4.2.2.6.
("Special Applications"), so those articles DO NOT EXIST in either edition;
they were NECB 2011 numbers. Where the legacy behaviour is described below
the 2011 numbers are named as such, and the live 2020/2025 articles are
4.2.2.1. (controls), 4.2.2.3. (sidelighted areas), 4.2.2.4. (roof monitors)
and 4.2.2.5. (skylights).
"""

from __future__ import annotations

import re

import openstudio

from btap._compat import ruby_div, ruby_round, ruby_str, sorted_by_name
from btap.audit import AuditLog
from btap.necb.lighting import daylight_control_requirement as DaylightControlRequirement
from btap.necb.lighting import daylighted_areas as DaylightedAreas

# MOVED: the legacy NECB 2011 daylighted-area math (pinned to legacy as
# fixed by #2119) — sidelighting_parameters / skylight_parameters + the dist /
# triangle_height / wall_point_distance helpers — now lives in
# _legacy_2011.py. In Ruby that file REOPENS this module; Python cannot have
# two files contribute to one module, so it is RE-EXPORTED here instead and
# every constant path (``Daylighting.sidelighting_parameters``) is unchanged.
# The quarantine is the file name and that module's header — do NOT merge it
# back in.
from btap.necb.lighting._legacy_2011 import (  # noqa: F401
    costing_area_provider,
    dist,
    sidelighting_parameters,
    skylight_parameters,
    triangle_height,
    wall_point_distance,
)

STEPPED_STEPS = 2       # legacy paths: the NECB 2011 minimum
STEPPED_STEPS_2020 = 3  # 4.2.2.1.(11)(a)(i) / (14)(a)(i): 67% / 33% / off

PLACEMENTS = ['all', 'necb2020', 'necb2011']


def add_controls(model, vintage='2020', placement=None, option=None,
                 office_match='legacy', unknown_control_requirement='required', audit=None):
    """:param placement: 'all' | 'necb2020' | 'necb2011' — THE selection knob,
        which spaces get a sensor. 'all' (DEFAULT) = every space with exterior
        fenestration, no threshold (the legacy blanket option); 'necb2020' =
        Article 4.2.2.1.(10)-(15) on unioned daylighted areas (D-57);
        'necb2011' (alias 'necb_default') = the legacy-exact 2011 port, defects
        included, kept reachable for the parity gate
    :param option: 'all' | 'NECB_Default' | None — DEPRECATED alias for
        ``placement``, kept so existing callers keep working: 'all' forces
        placement 'all'; 'NECB_Default' selects the code rule, i.e. the given
        ``placement`` when it names one ('necb2011'), else 'necb2020'. Passing
        it logs an audit info entry. Prefer ``placement`` alone.
    :param office_match: 'legacy' | 'any_enclosed_office' — 'necb2011' ONLY —
        the >=25 m2 office exemption matcher. Both values now BEHAVE
        IDENTICALLY: #2119 replaced legacy's exact ``== 'Office - enclosed'``
        (a 2011-era name that never matched the NECB2015+/2020 'Office enclosed
        <= 25 m2' / '> 25 m2' names) with /office\\s*-?\\s*enclosed/i, which is
        what 'any_enclosed_office' already meant. Both stay accepted; 'legacy'
        is the value pinned to whatever legacy does, so if legacy's matcher
        moves again only 'legacy' follows it.
    :param unknown_control_requirement: 'required' | 'not_required' —
        'necb2020' ONLY — what to assume when the Table 4.2.1.6. column cannot
        be resolved for a space type. Always warns; see
        DaylightControlRequirement.evaluate
    :return: number of controls created
    """
    from btap.necb import loads

    audit = audit if audit is not None else AuditLog()
    placement = resolve_placement(placement, option, audit)
    data_vintage = loads.data_vintage(vintage)
    created = 0
    fractions = {}

    if placement == 'necb2011':
        eligible = _necb_default_spaces(model, office_match, audit)
        rule = 'NECB 2011 (legacy-exact)'
    elif placement == 'necb2020':
        eligible, fractions = _necb2020_spaces(model, audit, unknown_control_requirement)
        rule = 'NECB 2020/2025 4.2.2.1.(10)-(15)'
    else:
        eligible = [s for s in sorted_by_name(model.getSpaces()) if _is_daylighted(s)]
        rule = 'all daylighted spaces'
    steps = STEPPED_STEPS if not fractions else STEPPED_STEPS_2020

    for space in eligible:
        if not space.thermalZone().is_initialized():
            continue

        zone = space.thermalZone().get()
        if zone.primaryDaylightingControl().is_initialized():
            continue

        setpoint = _illuminance_setpoint(space, data_vintage)
        if setpoint is None:
            audit.warn('daylighting',
                       'no target_illuminance_setpoint for this space type — no sensor placed',
                       target=space.nameString())
            continue

        bounds = _lowest_floor_bounds(space)
        if bounds is None:
            continue

        # 4.2.2.1.(10)/(13) control the general lighting IN THE DAYLIGHTED
        # AREAS, not the whole room, so the zone fraction under control is the
        # daylighted share of the zone floor area — not 1.0 (which is what the
        # legacy paths use, and what makes their reference over-credit).
        fraction = (_zone_fraction(space, zone, fractions[space.nameString()])
                    if space.nameString() in fractions else 1.0)
        if fraction <= 0.0:
            continue

        sensor = openstudio.model.DaylightingControl(model)
        sensor.setName(f"{space.nameString()} daylighting control")
        sensor.setSpace(space)
        sensor.setIlluminanceSetpoint(setpoint)
        sensor.setLightingControlType('Stepped')
        sensor.setNumberofSteppedControlSteps(steps)
        sensor.setPosition(openstudio.Point3d((bounds['xmin'] + bounds['xmax']) / 2.0,
                                              (bounds['ymin'] + bounds['ymax']) / 2.0,
                                              bounds['zmin'] + 0.8))
        zone.setPrimaryDaylightingControl(sensor)
        zone.setFractionofZoneControlledbyPrimaryDaylightingControl(fraction)
        created += 1
        sensor_article = ('4.2.2.1. (sensor hardware)' if not fractions
                          else '4.2.2.1.(10); 4.2.2.1.(11); 4.2.2.1.(13); 4.2.2.1.(14)')
        audit.info('daylighting', f"daylighting control placed ({rule})",
                   target=space.nameString(),
                   inputs={'illuminance_lux': setpoint, 'control': f"Stepped x{steps}",
                           'zone_fraction': ruby_round(fraction, 4)},
                   article=sensor_article,
                   ruling='D-57')

    # D-57 governs WHICH rule this method just used — including the choice to
    # keep the legacy 2011 path reachable — so every path cites it.
    audit.decision('daylighting', f"daylighting controls added by the {rule} rule",
                   inputs={'controls': created, 'placement': placement},
                   article='4.2.2.1.',
                   ruling='D-57')
    return created


def resolve_placement(placement, option, audit):
    """ONE selector. ``placement`` is it; ``option`` is the deprecated alias that
    used to share the job (and used to win, silently ignoring ``placement``).
    The mapping reproduces the old truth table exactly:
      option 'all'          -> 'all'                (whatever placement said)
      option 'NECB_Default' -> 'necb2011' if placement named it, else 'necb2020'
      option None           -> placement, defaulting to 'all'

    :return: one of PLACEMENTS"""
    given = None if placement is None else normalize_placement(placement)
    if option is None:
        return given or 'all'

    if str(option) == 'NECB_Default':
        resolved = 'necb2011' if given == 'necb2011' else 'necb2020'
    else:
        resolved = 'all'  # 'all', and anything unrecognized, as the legacy branch did
    if audit is not None:
        audit.info('daylighting',
                   "the `option:` argument is DEPRECATED — `placement:` is now the single selector; "
                   f"option: {_str_inspect(option)} was read as placement: {_sym(resolved)}",
                   inputs={'option': option, 'placement_given': placement,
                           'placement_used': resolved},
                   article='4.2.2.1.',
                   ruling='D-57')
    return resolved


def normalize_placement(placement):
    """PUBLIC (deliberately): the one place that knows the placement vocabulary,
    so callers that must branch on the rule (ReferenceDaylighting) resolve the
    'necb_default' alias here instead of keeping a second copy of the mapping.

    :return: 'all' | 'necb2020' | 'necb2011'"""
    value = str(placement)
    if value == 'necb_default':
        value = 'necb2011'
    if value not in PLACEMENTS:
        raise ValueError(
            f"unknown placement: {_sym(placement)} (expected one of "
            f"{', '.join(_sym(p) for p in PLACEMENTS)}, or :necb_default for :necb2011)")

    return value


def _sym(value):
    """Ruby ``Symbol#inspect`` — the placements are Ruby symbols there and
    plain strings here; the audit text keeps the Ruby rendering."""
    return f":{value}"


def _str_inspect(value):
    return 'nil' if value is None else f'"{value}"'


def _zone_fraction(space, zone, controlled_area_m2):
    """The daylighted share of the ZONE's floor area that this space's control
    governs. E+ applies the fraction zone-wide, so a space's daylighted area
    is divided by the zone floor area, not the space's."""
    denominator = zone.floorArea()
    if denominator is None or denominator <= 0.0:
        denominator = space.floorArea()
    if denominator is None or denominator <= 0.0:
        return 0.0

    return max(min(controlled_area_m2 / denominator, 1.0), 0.0)


def _necb2020_spaces(model, audit, unknown_control_requirement):
    """NECB 2020/2025 4.2.2.1.(10)-(15) selection. Sidelighting and toplighting
    are evaluated INDEPENDENTLY and unioned — a space qualifies on either.

    :return: (the spaces that require photocontrols, {space name -> controlled
        daylighted area m2})"""
    shading = DaylightControlRequirement.shading_polygons(model)
    if not shading:
        audit.info('daylighting',
                   'the 4.2.2.1.(12)(a) obstruction-ratio exception cannot apply: the model carries no '
                   'shading surfaces, so there is no adjacent structure to measure against',
                   article='4.2.2.1.(12)(a)',
                   ruling='D-57')
    audit.warn('daylighting',
               'THE 4.2.2.1.(15)(a) EXCEPTION IS NOT EVALUATED: whether adjacent structures or natural '
               'objects block direct sunlight for more than 1 500 h/yr between 8 a.m. and 4 p.m. needs an '
               'annual solar-obstruction study, which an SDK-only gem that never simulates cannot do. '
               'Not applying an exception is the STRICT direction (toplighting photocontrols are required '
               'where they might have been excused), so no reference target is loosened by this gap',
               article='4.2.2.1.(15)(a)',
               ruling='D-57')
    audit.info('daylighting', DaylightedAreas.limitations(),
               article='4.2.2.3.; 4.2.2.4.; 4.2.2.5.',
               ruling='D-57')

    selected = []
    controlled = {}
    evidence = []
    seen = {}  # dedupe the unresolved-column notices: one per (space type, column)
    side_count = 0
    top_count = 0
    for space in sorted_by_name(model.getSpaces()):
        if not space.partofTotalFloorArea():
            continue
        if not _is_daylighted(space):
            continue

        verdict = DaylightControlRequirement.evaluate(
            space, audit=audit, unknown_default=unknown_control_requirement,
            shading_surfaces=shading, seen=seen)
        areas = verdict['areas']
        side = verdict['sidelighting']['required']
        top = verdict['toplighting']['required']
        if side:
            side_count += 1
        if top:
            top_count += 1
        if not verdict['required']:
            audit.info('daylighting', 'no photocontrols required',
                       target=space.nameString(),
                       inputs={'sidelighting': verdict['sidelighting']['reason'],
                               'toplighting': verdict['toplighting']['reason']},
                       article='4.2.2.1.(10); 4.2.2.1.(13)',
                       ruling='D-57')
            continue

        area = 0.0
        if side:
            area += areas['primary_sidelighted_m2'] + areas['secondary_sidelighted_m2']
        if top:
            area += areas['toplighted_m2']
        selected.append(space)
        controlled[space.nameString()] = area
        evidence.append(f"{space.nameString()}: "
                        f"{verdict['sidelighting']['reason'] if side else ''}"
                        f"{' + ' if side and top else ''}"
                        f"{verdict['toplighting']['reason'] if top else ''}")
        audit.info('daylighting', 'photocontrols required',
                   target=space.nameString(),
                   inputs={'general_lpd_w_per_m2': ruby_round(verdict['lpd_w_per_m2'], 3),
                           'primary_sidelighted_m2': ruby_round(areas['primary_sidelighted_m2'], 2),
                           'secondary_sidelighted_m2': ruby_round(areas['secondary_sidelighted_m2'], 2),
                           'toplighted_m2': ruby_round(areas['toplighted_m2'], 2),
                           'floor_m2': ruby_round(areas['floor_m2'], 2),
                           'sidelighting': side, 'toplighting': top},
                   value=f"{area:.1f} m2 under photocontrol",
                   evidence=' + '.join(
                       [r for r in [verdict['sidelighting']['reason'] if side else None,
                                    verdict['toplighting']['reason'] if top else None]
                        if r is not None]),
                   article='4.2.2.1.(10); 4.2.2.1.(13)',
                   ruling='D-57')

    daylighted_spaces = sum(1 for s in model.getSpaces()
                            if s.partofTotalFloorArea() and _is_daylighted(s))
    audit.decision('daylighting',
                   'photocontrol requirement determined per 4.2.2.1.(10)-(15): the Table 4.2.1.6. column '
                   'for the space type gates each of sidelighting and toplighting, and each is then a test '
                   'of general-lighting INPUT POWER inside the daylighted area. With a uniform space-level '
                   'LPD that power is exactly LPD x daylighted_area, so no luminaire layout is needed. '
                   'Sidelighting (>=150 W primary, or >=300 W primary + secondary) and toplighting '
                   '(>=150 W under skylights) are INDEPENDENT — never ANDed as the NECB 2011 criteria were',
                   inputs={'daylighted_spaces': daylighted_spaces,
                           'sidelighting_required': side_count, 'toplighting_required': top_count,
                           'spaces_selected': len(selected),
                           'unknown_column_default': unknown_control_requirement},
                   evidence='; '.join(evidence[:5]),
                   article='4.2.2.1.(10); 4.2.2.1.(12); 4.2.2.1.(13); 4.2.2.1.(15); Table 4.2.1.6.',
                   ruling='D-57')
    return selected, controlled


def _necb_default_spaces(model, office_match, audit):
    """The legacy NECB_Default selection, MIRRORING LEGACY AS FIXED BY #2119
    (merged 2026-07-15). It is NECB 2011 machinery: a space is EXCEPTED (no
    sensor) if it fails ANY single APPLICABLE criterion — primary
    sidelighted area <= 100 m2 or sidelighting effective aperture <= 0.1
    (applied ONLY to spaces WITH exterior windows), daylighted area under
    skylights <= 400 m2 or skylight effective aperture <= 0.006 (applied
    ONLY to spaces WITH skylights) — unless it is an office >= 25 m2.
    (Legacy cites 4.2.2.4./4.2.2.7./4.2.2.8./4.2.2.10. for these; those are
    2011 numbers. NECB 2020/2025 Subsection 4.2.2 ends at 4.2.2.6., so
    4.2.2.7.-4.2.2.10. do not exist there, and 4.2.2.4. means something else
    entirely — roof monitors.)

    The pre-#2119 defects are gone from both sides: a window-only space is
    no longer auto-excepted by a skylight criterion it cannot meet (its
    skylight area was 0 <= 400), a skylight-only space likewise, and the
    >=25 m2 office exemption now matches the 2015+/2020 space-type names.
    What is left is a 2011-vs-2020 RULE difference: these thresholds are
    ANDed area/aperture tests, where 4.2.2.1.(10)/(13) are INDEPENDENT
    input-POWER tests (L-26, D-57)."""
    daylight_spaces = [s for s in sorted_by_name(model.getSpaces()) if _is_daylighted(s)]
    # #2119 made legacy's office test a regex — `== 'Office - enclosed'`
    # became `=~ /office\s*-?\s*enclosed/i` — so 'legacy' and
    # 'any_enclosed_office' now COINCIDE. Both stay accepted (callers and
    # docs name either), and 'legacy' is still the one pinned to legacy: if
    # legacy's matcher ever changes again, only the 'legacy' branch moves.
    offices = []
    for space in daylight_spaces:
        space_type = space.spaceType()
        if not space_type.is_initialized() or not space_type.get().standardsSpaceType().is_initialized():
            continue

        name = space_type.get().standardsSpaceType().get()
        if re.search(r'office\s*-?\s*enclosed', name, re.IGNORECASE) and _lowest_floor_area(space) >= 25.0:
            offices.append(space.nameString())

    # Which criteria even apply, per #2119: window criteria to spaces with
    # exterior windows, skylight criteria to spaces with skylights.
    with_windows = []
    with_skylights = []
    for space in daylight_spaces:
        for surface in sorted_by_name(space.surfaces()):
            for sub in sorted_by_name(surface.subSurfaces()):
                if sub.outsideBoundaryCondition() != 'Outdoors':
                    continue

                if sub.subSurfaceType() in ('FixedWindow', 'OperableWindow'):
                    with_windows.append(space.nameString())
                elif sub.subSurfaceType() == 'Skylight':
                    with_skylights.append(space.nameString())

    excepted = []
    metrics = {}
    for space in daylight_spaces:
        side = sidelighting_parameters(space, audit=audit)
        sky = skylight_parameters(space, audit=audit)
        side_ea = _fdiv(side['window_area_m2'] * _fdiv(side['vt_handle'], side['window_area_m2']),
                        side['area_m2'])
        sky_ea = _fdiv(0.85 * sky['skylight_area_m2']
                       * _fdiv(sky['vt_handle'], sky['skylight_area_m2']) * 0.9,
                       sky['area_m2'])
        metrics[space.nameString()] = {'sidelighted_m2': _round(side['area_m2'], 2),
                                       'side_ea': _round(side_ea, 4),
                                       'skylight_m2': _round(sky['area_m2'], 2),
                                       'sky_ea': _round(sky_ea, 5)}
        if space.nameString() in offices:
            continue

        windowed = space.nameString() in with_windows
        skylit = space.nameString() in with_skylights
        if ((windowed and side['area_m2'] <= 100.0)
                or (windowed and side_ea <= 0.1)
                or (skylit and sky['area_m2'] <= 400.0)
                or (skylit and sky_ea <= 0.006)):
            excepted.append(space.nameString())
    audit.warn('daylighting',
               'LEGACY NECB 2011 THRESHOLD EVALUATION IN USE (placement: :necb2011): the applicable '
               'area/aperture criteria are ANDed, so any single failed criterion excepts a space. This is '
               'not the 2020/2025 requirement — 4.2.2.1.(10) and (13) are INDEPENDENT input-POWER tests. '
               'The path exists only to keep the legacy parity gate callable (L-26, D-57)',
               inputs={'daylighted': len(daylight_spaces), 'excepted': len(excepted),
                       'offices_exempt': len(offices),
                       'with_windows': len(set(with_windows)),
                       'with_skylights': len(set(with_skylights)),
                       'office_match': office_match},
               evidence='; '.join(f"{k}: {_hash_inspect(v)}"
                                  for k, v in list(metrics.items())[:5]),
               article='NECB 2011 4.2.2.4./4.2.2.7./4.2.2.8./4.2.2.10. (articles that DO NOT EXIST in NECB 2020/2025, whose Subsection 4.2.2 ends at 4.2.2.6.)',
               ruling='D-57')
    return [s for s in daylight_spaces if s.nameString() not in excepted]


# These two were written here first, when the NaN-skip behaviour of the
# legacy 2011 effective-aperture criteria was discovered (a window-only space
# has ZERO skylight area, so its skylight aperture is NaN and ``NaN <= 0.006``
# is FALSE in both languages — precisely how the ANDed criteria skip the half
# that does not apply, #2119). The hazard turned out to be family-wide, so
# both now live in _compat; the local names stay as the call sites' spelling.
_fdiv = ruby_div
_round = ruby_round


def _hash_inspect(hash_):
    """Ruby ``Hash#inspect`` for the symbol-keyed metric hashes the evidence
    string interpolates ({:sidelighted_m2=>30.0, ...})."""
    return '{' + ', '.join(f":{k}=>{ruby_str(v)}" for k, v in hash_.items()) + '}'


def _lowest_floor_area(space):
    floors = [s for s in space.surfaces() if s.surfaceType() == 'Floor']
    if not floors:
        return 0.0

    lowest_z = min(min(v.z() for v in f.vertices()) for f in floors)
    return sum(f.netArea() for f in floors
               if min(v.z() for v in f.vertices()) == lowest_z)


def _is_daylighted(space):
    return any(sub.outsideBoundaryCondition() == 'Outdoors'
               and sub.subSurfaceType() in ('FixedWindow', 'OperableWindow', 'Skylight')
               for surface in space.surfaces()
               for sub in surface.subSurfaces())


def _illuminance_setpoint(space, data_vintage):
    from btap.necb.loads import space_types as SpaceTypes

    if not space.spaceType().is_initialized():
        return None

    space_type = space.spaceType().get()
    if not (space_type.standardsBuildingType().is_initialized()
            and space_type.standardsSpaceType().is_initialized()):
        return None

    record = SpaceTypes.find(building_type=space_type.standardsBuildingType().get(),
                             space_type=space_type.standardsSpaceType().get(),
                             vintage=data_vintage)
    if record is None:
        return None

    value = record['target_illuminance_setpoint']
    value = 0.0 if value is None else float(value)
    return None if value == 0.0 else value


def _lowest_floor_bounds(space):
    floors = [s for s in space.surfaces() if s.surfaceType() == 'Floor']
    if not floors:
        return None

    lowest_z = min(min(v.z() for v in f.vertices()) for f in floors)
    lowest = [f for f in floors if min(v.z() for v in f.vertices()) == lowest_z]
    points = [v for f in lowest for v in f.vertices()]
    return {'xmin': min(p.x() for p in points), 'xmax': max(p.x() for p in points),
            'ymin': min(p.y() for p in points), 'ymax': max(p.y() for p in points),
            'zmin': lowest_z}
