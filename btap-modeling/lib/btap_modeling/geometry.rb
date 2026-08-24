module BtapModeling
  # SDK-only envelope geometry: exposed conditioned surface census and
  # centroid-scaled subsurface helpers. The NECB rule appliers built on these
  # (apply_fdwr / apply_srr, 3.2.1.4) live with the envelope NECB code.
  #
  # "Conditioned, non-plenum" is proxied by Space#partofTotalFloorArea + a zone
  # thermostat (the legacy check reads NECB space-type setpoint schedules; on
  # standards-untagged models the proxy is equivalent) — same convention as the
  # hvac classifier.
  module Geometry
    module_function

    def conditioned?(space)
      return false unless space.partofTotalFloorArea

      zone = space.thermalZone
      zone.is_initialized && zone.get.thermostatSetpointDualSetpoint.is_initialized
    end

    # Census of exterior conditioned walls (near-vertical) with area totals and the
    # current FDWR (port of find_exposed_conditioned_vertical_surfaces).
    def exposed_walls(model, min_angle: 89, max_angle: 91)
      walls = []
      wall_area = 0.0
      sub_area = 0.0
      model.getSpaces.sort_by(&:nameString).each do |space|
        next unless conditioned?(space)

        space.surfaces.sort_by(&:nameString).each do |surface|
          next unless surface.surfaceType == 'Wall' && surface.outsideBoundaryCondition == 'Outdoors'

          tilt = surface.tilt * 180.0 / Math::PI
          next unless tilt >= min_angle && tilt <= max_angle

          walls << surface
          wall_area += surface.grossArea * space.multiplier
          surface.subSurfaces.each { |ss| sub_area += ss.grossArea * space.multiplier }
        end
      end
      { walls: walls, wall_area_m2: wall_area, subsurface_area_m2: sub_area,
        fdwr: wall_area < 0.1 ? nil : sub_area / wall_area }
    end

    # Census of exterior conditioned roofs with the current SRR.
    def exposed_roofs(model)
      roofs = []
      roof_area = 0.0
      sub_area = 0.0
      model.getSpaces.sort_by(&:nameString).each do |space|
        next unless conditioned?(space)

        space.surfaces.sort_by(&:nameString).each do |surface|
          next unless surface.surfaceType == 'RoofCeiling' && surface.outsideBoundaryCondition == 'Outdoors'

          roofs << surface
          roof_area += surface.grossArea * space.multiplier
          surface.subSurfaces.each { |ss| sub_area += ss.grossArea * space.multiplier }
        end
      end
      { roofs: roofs, roof_area_m2: roof_area, subsurface_area_m2: sub_area,
        srr: roof_area < 0.1 ? nil : sub_area / roof_area }
    end

    # Scale every subsurface of a surface about its own centroid so its area changes
    # by `area_ratio` (used by the reference-envelope per-orientation FDWR reduction:
    # 8.4.4.3.(3) scales EXISTING fenestration proportionally, never rebuilds).
    def scale_subsurfaces(surface, area_ratio)
      scale = Math.sqrt(area_ratio)
      surface.subSurfaces.sort_by(&:nameString).each do |sub|
        centroid = vertex_centroid(sub.vertices)
        sub.setVertices(sub.vertices.map do |v|
          OpenStudio::Point3d.new(centroid.x + (v.x - centroid.x) * scale,
                                  centroid.y + (v.y - centroid.y) * scale,
                                  centroid.z + (v.z - centroid.z) * scale)
        end)
      end
    end

    def vertex_centroid(vertices)
      n = vertices.size.to_f
      OpenStudio::Point3d.new(vertices.sum(&:x) / n, vertices.sum(&:y) / n, vertices.sum(&:z) / n)
    end
  end
end
