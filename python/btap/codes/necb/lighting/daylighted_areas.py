"""Daylighted-area geometry per NECB 2020/2025 Articles 4.2.2.3. (primary and
secondary SIDELIGHTED areas), 4.2.2.4. (under ROOF MONITORS) and 4.2.2.5.
(under SKYLIGHTS) — the areas that 4.2.2.1.(10) and (13) test lighting
power against.

WHY THIS EXISTS instead of Daylighting.sidelighting_parameters (the legacy
NECB 2011 port, quarantined in _legacy_2011.py): each of
4.2.2.3.(1), 4.2.2.3.(5), 4.2.2.4.(1) and 4.2.2.5.(1) defines its total as
"the combined ... areas WITHOUT DOUBLE-COUNTING OVERLAPPING AREAS", and
4.2.2.5.(2)(b) and 4.2.2.4.(2)(a)(iii) additionally clip toplit area at the
edge of a primary sidelighted area. A per-window sum cannot express either.
This is an adaptation of openstudio-standards' Standard#space_daylighted_areas
(lib/openstudio-standards/standards/Standards.Space.rb): build one polygon
per aperture, flatten every polygon to z = 0, JOIN each set into a union,
then SUBTRACT in priority order (toplit wins over primary, primary over
secondary) and intersect the result with the floor. Polygon booleans are
OpenStudio's own (openstudio.joinAll / .subtract / .within / .intersects /
.getArea) — no new dependency.

NECB-SPECIFIC DEVIATIONS from the openstudio-standards original (which
implements ASHRAE 90.1):
  * side extension = 1/2 the window HEAD HEIGHT on each side
    (4.2.2.3.(3)(a) and (7)(a)); the original's width method is a template
    hook that returns 'none' by default and 2 ft for some 90.1 vintages.
  * primary depth = one window head height (4.2.2.3.(4)(a)); secondary
    depth runs from the end of the primary to one further head height
    (4.2.2.3.(8)(a)) — the same geometry the original builds, but here it
    is the CODE requirement rather than a coincidence.
  * skylight extension = 70% of the ceiling height (4.2.2.5.(2)(a)) — same
    as the original.

HONEST LIMITS, audited every run (see #limitations):
  * 4.2.2.3.(3)(b)/(4)(b)/(8)(b) and 4.2.2.5.(2)(c) bound each dimension by
    "the distance to any vertical obstruction that is 1.5 m or more in
    height". The space's own enclosure IS honoured — every polygon is
    intersected with the floor, so no daylighted area escapes the room.
    Obstructions INSIDE the space (partitions, racking, furniture) are not
    in an OpenStudio thermal model at all, so they cannot be detected; the
    computed areas are therefore an UPPER BOUND within each space.
  * 4.2.2.4. ROOF MONITORS are vertical glazing ABOVE the ceiling. A
    monitor is not a distinguishable object in an OpenStudio model (it is
    ordinary wall glazing, usually on a separate high space), so toplit
    area here covers SKYLIGHTS only. Every model whose spaces have no
    above-ceiling glazing is unaffected; models with monitors get less
    toplit area than the code would give them.
"""

from __future__ import annotations

import re

import openstudio

from btap._compat import NullAudit, ruby_round, sorted_by_name

WINDOW_TYPES = ['FixedWindow', 'OperableWindow', 'GlassDoor']
SKYLIGHT_EXTENT_FRACTION = 0.7  # 4.2.2.5.(2)(a)
TOLERANCE = 0.01


def areas(space, audit=None):
    """:param space: openstudio.model.Space
    :param audit: btap.audit.AuditLog or None
    :return: all areas in m2 —
        'toplighted_m2', 'primary_sidelighted_m2', 'secondary_sidelighted_m2',
        'floor_m2', 'window_area_m2', 'skylight_area_m2',
        'window_vt_max', 'skylight_vt_max' (None when there are none)
    """
    audit = audit if audit is not None else NullAudit()
    result = {'toplighted_m2': 0.0, 'primary_sidelighted_m2': 0.0,
              'secondary_sidelighted_m2': 0.0,
              'floor_m2': 0.0, 'window_area_m2': 0.0, 'skylight_area_m2': 0.0,
              'window_vt_max': None, 'skylight_vt_max': None}

    floor_surface = None
    floor_polygons = []
    for surface in sorted_by_name(space.surfaces()):
        if surface.surfaceType() != 'Floor':
            continue

        if floor_surface is None:
            floor_surface = surface
        floor_polygons.append([openstudio.Point3d(v.x(), v.y(), 0.0)
                               for v in surface.vertices()])
    if floor_surface is None:
        audit.warn('daylighting',
                   f"space '{space.nameString()}' has NO FLOOR SURFACE — daylighted areas cannot be "
                   'determined, so 4.2.2.1.(10)/(13) are evaluated against zero area',
                   article='4.2.2.3.; 4.2.2.5.')
        return result

    toplit = []
    primary = []
    secondary = []

    for surface in sorted_by_name(space.surfaces()):
        if surface.outsideBoundaryCondition() == 'Outdoors' and surface.surfaceType() == 'Wall':
            if not _is_vertical(surface, space, audit):
                continue

            for sub in sorted_by_name(surface.subSurfaces()):
                if not (sub.outsideBoundaryCondition() == 'Outdoors'
                        and sub.subSurfaceType() in WINDOW_TYPES):
                    continue

                result['window_area_m2'] += sub.netArea()
                vt = _visible_transmittance(sub)
                if vt is not None:
                    result['window_vt_max'] = max(result['window_vt_max'] or 0.0, vt)

                pair = _sidelit_polygons(space, sub, floor_surface, audit)
                if pair is None:
                    continue

                primary.append(pair[0])
                secondary.append(pair[1])
        elif (surface.outsideBoundaryCondition() == 'Outdoors'
                and surface.surfaceType() == 'RoofCeiling'):
            if not _is_horizontal(surface, space, audit):
                continue

            for sub in sorted_by_name(surface.subSurfaces()):
                if not (sub.outsideBoundaryCondition() == 'Outdoors'
                        and sub.subSurfaceType() == 'Skylight'):
                    continue

                result['skylight_area_m2'] += sub.netArea()
                vt = _visible_transmittance(sub)
                if vt is not None:
                    result['skylight_vt_max'] = max(result['skylight_vt_max'] or 0.0, vt)

                polygon = _toplit_polygon(space, sub, floor_surface, audit)
                if polygon is not None:
                    toplit.append(polygon)

    # Join each set into its own union — this is what "without double-counting
    # overlapping areas" (4.2.2.3.(1)/(5), 4.2.2.4.(1), 4.2.2.5.(1)) requires.
    floor_union = _join(space, floor_polygons, 'floor', audit)
    toplit_union = _join(space, toplit, 'toplighted', audit)
    primary_union = _join(space, primary, 'primary sidelighted', audit)
    secondary_union = _join(space, secondary, 'secondary sidelighted', audit)

    # Subtract in NECB's OWN precedence order: PRIMARY > TOPLIT > SECONDARY.
    #   * 4.2.2.5.(2)(b) caps each skylight extension at "the distance to any
    #     primary sidelighted area", so the toplit area STOPS at the primary
    #     band — the primary is never reduced by a skylight. Because a primary
    #     band always hugs an exterior wall and every polygon is clipped to
    #     the floor, "stop the extension at the band" and "subtract the band"
    #     give the same area here.
    #   * 4.2.2.3.(9): no secondary sidelighted area exists beyond the limit
    #     of an adjacent under-skylight or primary area, so secondary loses to
    #     both.
    # NOTE this is the OPPOSITE of the openstudio-standards original this was
    # adapted from, which subtracts toplit from primary — correct for ASHRAE
    # 90.1, wrong for NECB.
    toplit_only = _subtract(toplit_union, primary_union)
    secondary_only = _subtract(_subtract(secondary_union, primary_union), toplit_union)

    result['floor_m2'] = _total_area(floor_union)
    result['toplighted_m2'] = _overlap_area(toplit_only, floor_union)
    result['primary_sidelighted_m2'] = _overlap_area(primary_union, floor_union)
    result['secondary_sidelighted_m2'] = _overlap_area(secondary_only, floor_union)
    return result


def limitations():
    """One-line audit of what this geometry cannot see. Emitted once per run by
    the caller, never suppressed."""
    return ('4.2.2.3.(3)(b)/(4)(b)/(8)(b) and 4.2.2.5.(2)(c) bound each daylighted dimension by the distance '
            'to a vertical obstruction >= 1.5 m high: the SPACE ENCLOSURE is honoured (every daylighted '
            'polygon is intersected with the floor), but obstructions INSIDE a space are not present in an '
            'OpenStudio thermal model, so the areas are an upper bound within each space; and 4.2.2.4. ROOF '
            'MONITORS are not a distinguishable object in an OpenStudio model, so toplighted area covers '
            'SKYLIGHTS only')


# --- geometry helpers -----------------------------------------------------

def _visible_transmittance(sub_surface):
    try:
        vt = sub_surface.visibleTransmittance()
        return vt.get() if vt.is_initialized() else None
    except Exception:
        return None


def _is_vertical(surface, space, audit):
    if abs(surface.outwardNormal().z()) < 0.001:
        return True
    if not surface.subSurfaces():
        return True

    audit.warn('daylighting',
               f"NON-VERTICAL EXTERIOR WALL '{surface.nameString()}' in space "
               f"'{space.nameString()}' carries "
               'glazing — its sidelighted areas are NOT computed (the 4.2.2.3. width/depth construction '
               'assumes vertical glazing)', article='4.2.2.3.')
    return False


def _is_horizontal(surface, space, audit):
    normal = surface.outwardNormal()
    if normal.z() > 0.999 and abs(normal.x()) < 0.001 and abs(normal.y()) < 0.001:
        return True
    if not surface.subSurfaces():
        return True

    audit.warn('daylighting',
               f"NON-HORIZONTAL ROOF '{surface.nameString()}' in space '{space.nameString()}' carries "
               'skylights — the daylighted area under them is NOT computed (the 4.2.2.5. projection '
               'construction assumes a horizontal roof)', article='4.2.2.5.')
    return False


def _sidelit_polygons(space, sub_surface, floor_surface, audit):
    """Primary (4.2.2.3.(2)-(4)) and secondary (4.2.2.3.(6)-(8)) polygons for one
    window, both folded down onto the z = 0 floor plane."""
    vertices = list(sub_surface.vertices())
    if len(vertices) != 4:
        audit.warn('daylighting',
                   f"WINDOW '{sub_surface.nameString()}' in space '{space.nameString()}' has "
                   f"{len(vertices)} vertices, not 4 — EXCLUDED from the sidelighted areas",
                   article='4.2.2.3.')
        return None

    plane = floor_surface.plane()
    heights = [(v - plane.project(v)).length() for v in vertices]
    sill_height = min(heights)
    head_height = max(heights)
    if head_height <= 0.0:
        return None

    # 4.2.2.3.(3)(a)/(7)(a): 1/2 the window head height on each side.
    extra_width = head_height / 2.0

    rotation_origin = None
    previous = None
    widest = 0.0
    for vertex in vertices:
        projected = plane.project(vertex)
        if previous is not None:
            width = (previous - projected).length()
            if width > widest:
                widest = width
                rotation_origin = projected
        previous = projected
    if rotation_origin is None:
        return None

    face_transform = openstudio.Transformation.alignFace(sub_surface.vertices())
    aligned = list(face_transform.inverse() * sub_surface.vertices())
    min_x = min(v.x() for v in aligned)
    max_x = max(v.x() for v in aligned)

    primary = []
    secondary = []
    non_rectangular = False
    for vertex in aligned:
        if abs(vertex.x() - min_x) < TOLERANCE:
            new_x = vertex.x() - extra_width
        elif abs(vertex.x() - max_x) < TOLERANCE:
            new_x = vertex.x() + extra_width
        else:
            non_rectangular = True
            new_x = vertex.x()
        # Zero the bottom edge: the primary area runs from the wall inward,
        # so the aperture's own sill offset is folded out (4.2.2.3.(4)(a)
        # measures the depth from the FLOOR to the top of the glazing).
        primary_y = vertex.y() - sill_height if vertex.y() == 0 else vertex.y()
        # 4.2.2.3.(8)(a): the secondary band begins where the primary ends and
        # runs one further head height.
        secondary_y = primary_y + head_height
        primary.append(openstudio.Point3d(new_x, primary_y, 0.0))
        secondary.append(openstudio.Point3d(new_x, secondary_y, 0.0))
    if non_rectangular:
        audit.warn('daylighting',
                   f"NON-RECTANGULAR WINDOW '{sub_surface.nameString()}' in space "
                   f"'{space.nameString()}': its "
                   'side extension is applied only to the extreme vertices, so its sidelighted areas are '
                   'approximate', article='4.2.2.3.')

    primary = list(face_transform * primary)
    secondary = list(face_transform * secondary)

    # Rotate both bands down onto the floor plane about the window's own base.
    rotation = openstudio.createRotation(
        rotation_origin,
        openstudio.Vector3d(0, 0, -1).cross(sub_surface.outwardNormal()),
        openstudio.degToRad(90))
    return [_set_z_zero(list(reversed(list(rotation * primary)))),
            _set_z_zero(list(reversed(list(rotation * secondary))))]


def _toplit_polygon(space, sub_surface, floor_surface, audit):
    """4.2.2.5.(2): the skylight's projection onto the floor grown by 70% of the
    ceiling height in each direction."""
    vertices = list(sub_surface.vertices())
    if len(vertices) != 4:
        audit.warn('daylighting',
                   f"SKYLIGHT '{sub_surface.nameString()}' in space '{space.nameString()}' has "
                   f"{len(vertices)} vertices, not 4 — EXCLUDED from the toplighted area",
                   article='4.2.2.5.')
        return None

    plane = floor_surface.plane()
    on_floor = [plane.project(v) for v in vertices]
    ceiling_height = max((v - plane.project(v)).length() for v in vertices)
    if ceiling_height <= 0.0:
        return None

    extent = SKYLIGHT_EXTENT_FRACTION * ceiling_height
    face_transform = openstudio.Transformation.alignFace(on_floor)
    aligned = list(face_transform.inverse() * on_floor)
    min_x = min(v.x() for v in aligned)
    max_x = max(v.x() for v in aligned)
    min_y = min(v.y() for v in aligned)
    max_y = max(v.y() for v in aligned)

    grown = []
    for vertex in aligned:
        if abs(vertex.x() - min_x) < TOLERANCE:
            new_x = vertex.x() - extent
        elif abs(vertex.x() - max_x) < TOLERANCE:
            new_x = vertex.x() + extent
        else:
            new_x = vertex.x()
        if abs(vertex.y() - min_y) < TOLERANCE:
            new_y = vertex.y() - extent
        elif abs(vertex.y() - max_y) < TOLERANCE:
            new_y = vertex.y() + extent
        else:
            new_y = vertex.y()
        grown.append(openstudio.Point3d(new_x, new_y, 0.0))
    return _set_z_zero(list(reversed(list(face_transform * grown))))


def _set_z_zero(polygon):
    return [openstudio.Point3d(vertex.x(), vertex.y(), 0.0) for vertex in polygon]


# --- polygon booleans (thin wrappers over the OpenStudio utilities) -------

def _join(space, polygons, name, audit):
    """Union a set of polygons. joinAll can fail on sets that form an inner loop
    (the classic case: windows on all four walls); the openstudio-standards
    original retries with n-1 polygons and adds the remainder back, and that
    workaround is kept here."""
    if not polygons:
        return []
    if len(polygons) == 1:
        return polygons

    sink = openstudio.StringStreamLogSink()
    sink.setLogLevel(openstudio.Info)
    combined = list(openstudio.joinAll(polygons, TOLERANCE))
    failed = _join_failures(sink)
    sink.disable()

    if failed > 0:
        retry_sink = openstudio.StringStreamLogSink()
        retry_sink.setLogLevel(openstudio.Info)
        first = polygons[0]
        rest = list(openstudio.joinAll(polygons[1:], TOLERANCE))
        retry_failed = _join_failures(retry_sink)
        retry_sink.disable()
        if retry_failed == 0:
            combined = rest + _subtract([first], rest)
            failed = 0

    if failed > 0:
        audit.warn('daylighting',
                   f"POLYGON UNION FAILED for the {name} areas of space '{space.nameString()}' "
                   f"({failed} joinAll complaint(s) over {len(polygons)} polygons) — the area reported is "
                   'SMALLER than the code requires, so the 4.2.2.1.(10)/(13) power test may under-trigger',
                   article='4.2.2.3.; 4.2.2.5.')
    return combined


def _join_failures(sink):
    return sum(1 for message in sink.logMessages()
               if re.search('utilities.geometry', message.logChannel())
               and ('Expected polygons to join together' in message.logMessage()
                    or 'Union has inner loops' in message.logMessage()))


def _subtract(a_polygons, b_polygons):
    """a_polygons minus b_polygons."""
    if not a_polygons:
        return []
    if not b_polygons:
        return list(a_polygons)

    results = []
    for a_polygon in a_polygons:
        pieces = []
        for piece in openstudio.subtract(a_polygon, list(b_polygons), TOLERANCE):
            if len(piece) == 0:
                continue
            area = openstudio.getArea(piece)
            if not area.is_initialized() or area.get() < 0.5:  # drop slivers, as the original does
                continue
            pieces.append(piece)
        results.extend(_set_z_zero(piece) for piece in pieces)
    return _dedupe(results)


def _dedupe(polygons):
    seen = {}
    for polygon in polygons:
        key = tuple((ruby_round(v.x(), 6), ruby_round(v.y(), 6)) for v in polygon)
        if key not in seen:
            seen[key] = polygon
    return list(seen.values())


def _total_area(polygons):
    total = 0.0
    for polygon in polygons:
        area = openstudio.getArea(polygon)
        total += area.get() if area.is_initialized() else 0.0
    return total


def _overlap_area(a_polygons, b_polygons):
    """Area of a_polygons that lies inside b_polygons."""
    if not a_polygons or not b_polygons:
        return 0.0

    overlap = 0.0
    for b_polygon in b_polygons:
        for a_polygon in a_polygons:
            if openstudio.within(a_polygon, b_polygon, TOLERANCE):
                area = openstudio.getArea(a_polygon)
                if area.is_initialized():
                    overlap += area.get()
            elif openstudio.intersects(a_polygon, b_polygon, TOLERANCE):
                initial = openstudio.getArea(b_polygon)
                if not initial.is_initialized():
                    continue

                remaining = 0.0
                for piece in openstudio.subtract(b_polygon, [a_polygon], TOLERANCE):
                    if len(piece) == 0:
                        continue
                    area = openstudio.getArea(piece)
                    remaining += area.get() if area.is_initialized() else 0.0
                overlap += (initial.get() - remaining)
    return overlap
