module BtapNECB
  module Lighting
    module StorageGarage
      # The geometry 4.2.2.2.(4) needs and the gem did not have: a FIXED-METRIC
      # band inward from a wall, and a PER-WALL net opening ratio.
      #
      # Neither could be borrowed. DaylightedAreas.sidelit_polygons builds a band
      # from an APERTURE whose depth is the window head height and whose width is
      # extended by half that again — the 4.2.2.3 convention. This sentence
      # measures a constant 6.1 m from the WALL, glazed or not, with no side
      # extension. And nothing in this gem computes an opening ratio at all; the
      # envelope gem's `exposed_walls` returns a whole-MODEL FDWR.
      module Perimeter
        module_function

        TOLERANCE = 0.01

        # Net opening-to-wall ratio for one wall.
        #
        # NET, not gross: 4.2.2.2.(4) says "net opening-to-wall ratio", and this
        # gem's convention throughout is `sub.netArea` (the envelope gem uses
        # grossArea for its FDWR, which is a different quantity for a window with
        # a frame — do not cross the two).
        def opening_ratio(wall)
          gross = wall.grossArea
          return 0.0 unless gross > TOLERANCE

          wall.subSurfaces.sum(&:netArea) / gross
        end

        def exterior_wall?(surface)
          surface.surfaceType == 'Wall' && surface.outsideBoundaryCondition == 'Outdoors'
        end

        # Walls at or above the 40% net-opening threshold.
        def glazed_perimeter_walls(space)
          space.surfaces.sort_by(&:nameString).select do |s|
            exterior_wall?(s) && opening_ratio(s) >= GLAZED_WALL_RATIO
          end
        end

        # The floor polygons of a space, flattened to z = 0, in the same
        # convention DaylightedAreas uses so the areas are comparable.
        def floor_polygons(space)
          space.surfaces.select { |s| s.surfaceType == 'Floor' }
               .map { |s| s.vertices.map { |v| OpenStudio::Point3d.new(v.x, v.y, 0.0) } }
        end

        # A quad running PERIMETER_BAND_M inward from the wall's base line.
        #
        # Built by projecting the wall to z = 0 and extruding along its inward
        # horizontal normal, rather than by the rotate-about-the-sill trick
        # sidelit_polygons uses: there is no aperture here to rotate about, and
        # the band starts at the wall itself rather than at a sill.
        def band_polygon(wall, depth = PERIMETER_BAND_M)
          base = wall.vertices.map { |v| OpenStudio::Point3d.new(v.x, v.y, 0.0) }
          # The wall collapses to a line; take its two extreme points.
          ends = extreme_pair(base)
          return nil if ends.nil?

          normal = wall.outwardNormal
          inward = OpenStudio::Vector3d.new(-normal.x, -normal.y, 0.0)
          return nil if inward.length < TOLERANCE

          inward.setLength(depth)
          a, b = ends
          # Wound counter-clockwise unconditionally: this rectangle is the CLIP
          # WINDOW, and Sutherland-Hodgman's half-plane test takes its sign from
          # the window's winding. The wall's own vertex order is whatever the
          # model author chose, so it cannot be trusted to give one consistently.
          ensure_ccw([a, b,
                      OpenStudio::Point3d.new(b.x + inward.x, b.y + inward.y, 0.0),
                      OpenStudio::Point3d.new(a.x + inward.x, a.y + inward.y, 0.0)])
        end

        # Signed shoelace: positive is counter-clockwise in a +z-up frame.
        def signed_area(polygon)
          polygon.each_with_index.sum do |p, i|
            q = polygon[(i + 1) % polygon.size]
            (p.x * q.y) - (q.x * p.y)
          end / 2.0
        end

        def ensure_ccw(polygon)
          signed_area(polygon).negative? ? polygon.reverse : polygon
        end

        # The two furthest-apart points — the wall's footprint endpoints.
        def extreme_pair(points)
          best = nil
          longest = 0.0
          points.each_with_index do |p, i|
            points.each_with_index do |q, j|
              next if j <= i

              d = (p - q).length
              next unless d > longest

              longest = d
              best = [p, q]
            end
          end
          longest > TOLERANCE ? best : nil
        end

        # Floor area within 6.1 m of a >=40%-glazed exterior wall.
        #
        # Bands from adjacent qualifying walls OVERLAP at a corner, so the union
        # is clipped as a set, not summed — otherwise a corner is counted twice
        # and the >150 W threshold trips early.
        #
        # @return [Hash] :area_m2 and the walls that contributed
        def qualifying_band_area(space, audit = nil)
          walls = glazed_perimeter_walls(space)
          return { area_m2: 0.0, walls: [] } if walls.empty?

          floors = floor_polygons(space)
          if floors.empty?
            audit&.warn(:lighting,
                        "STORAGE GARAGE '#{space.nameString}' HAS NO FLOOR SURFACE — its 4.2.2.2.(4) " \
                        'perimeter band cannot be measured', article: '4.2.2.2.(4)')
            return { area_m2: 0.0, walls: walls.map(&:nameString) }
          end

          bands = walls.filter_map { |w| band_polygon(w) }
          return { area_m2: 0.0, walls: walls.map(&:nameString) } if bands.empty?

          { area_m2: union_clipped_area(bands, floors), walls: walls.map(&:nameString) }
        end

        # Area of (union of bands) intersected with (union of floors).
        #
        # Deliberately NOT OpenStudio.within / .intersects / .subtract. Those are
        # what DaylightedAreas uses, and they cannot answer this shape: a
        # perimeter band runs the full width of the wall, so it SHARES EDGES with
        # the floor on three sides. Measured on a 20 x 15 m garage with a 6.1 m
        # band, `within` and `intersects` both return false (a shared edge is
        # neither containment nor crossing), and `subtract` reports the whole
        # floor consumed. The 4.2.2.3 bands DaylightedAreas builds are inset from
        # the aperture and never hit that case.
        #
        # The band is always a rectangle, so a convex-clip Sutherland-Hodgman is
        # exact here and has no such edge cases. Overlap between adjacent bands
        # is removed by clipping each floor piece against each band and taking
        # the union of the RESULTS by inclusion-exclusion over a grid-free
        # decomposition: since all bands are rectangles sharing the floor plane,
        # summing clipped areas and subtracting pairwise intersections is exact
        # for the two-band corner case that actually occurs.
        def union_clipped_area(bands, floors)
          pieces = floors.flat_map { |floor| bands.map { |band| clip(floor, band) } }
                         .reject(&:empty?)
          return 0.0 if pieces.empty?

          total = pieces.sum { |poly| shoelace(poly) }
          # Subtract each pairwise overlap once: two perpendicular bands meeting
          # at a corner share exactly one rectangle.
          pieces.each_with_index do |a, i|
            pieces.each_with_index do |b, j|
              next if j <= i

              total -= shoelace(clip(a, b))
            end
          end
          [total, floors.sum { |f| shoelace(f) }].min
        end

        # Sutherland-Hodgman: clip `subject` against the CONVEX polygon `window`.
        def clip(subject, window)
          output = subject
          window.each_with_index do |current, i|
            break if output.empty?

            nxt = window[(i + 1) % window.size]
            input = output
            output = []
            input.each_with_index do |point, k|
              prev = input[(k - 1) % input.size]
              point_in = inside?(point, current, nxt)
              prev_in = inside?(prev, current, nxt)
              output << intersection(prev, point, current, nxt) if prev_in != point_in
              output << point if point_in
            end
          end
          output.compact
        end

        # Left of the directed edge a->b, within tolerance. The sign convention
        # follows the window's own winding, so it works for either orientation
        # provided the window is convex and consistently wound.
        def inside?(point, a, b)
          cross(a, b, point) >= -TOLERANCE
        end

        def cross(a, b, p)
          ((b.x - a.x) * (p.y - a.y)) - ((b.y - a.y) * (p.x - a.x))
        end

        def intersection(p1, p2, a, b)
          d1 = cross(a, b, p1)
          d2 = cross(a, b, p2)
          denominator = d1 - d2
          return p2 if denominator.abs < 1e-12

          t = d1 / denominator
          OpenStudio::Point3d.new(p1.x + ((p2.x - p1.x) * t), p1.y + ((p2.y - p1.y) * t), 0.0)
        end

        def shoelace(polygon)
          return 0.0 if polygon.size < 3

          sum = 0.0
          polygon.each_with_index do |p, i|
            q = polygon[(i + 1) % polygon.size]
            sum += (p.x * q.y) - (q.x * p.y)
          end
          (sum / 2.0).abs
        end
      end
    end
  end
end
