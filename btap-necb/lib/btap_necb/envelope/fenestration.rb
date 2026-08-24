module BtapNECB
  module Envelope
    # The 3.2.1.4 fenestration-area rule appliers (FDWR window rebuild, SRR
    # centroid-scaled skylights) — rule application, hence NECB-side; the
    # generic census/scaling machinery they drive is BtapModeling::Geometry.
    module Fenestration
      module_function

    # Rebuild windows to hit an FDWR limit (port of apply_max_fdwr_nrcan): remove
    # existing subsurfaces, setWindowToWallRatio per exposed wall, retype to
    # FixedWindow and assign the given construction.
    def apply_fdwr(model, fdwr_lim, window_construction, audit: nil)
      census = Geometry.exposed_walls(model)
      return false if census[:wall_area_m2] < 0.1 || fdwr_lim > 1

      census[:walls].each do |surface|
        surface.subSurfaces.sort_by(&:nameString).each(&:remove)
        next if fdwr_lim < 0.001

        surface.setWindowToWallRatio(fdwr_lim)
        surface.subSurfaces.sort_by(&:nameString).each do |sub|
          sub.setSubSurfaceType('FixedWindow')
          sub.setConstruction(window_construction)
          sub.setName("#{surface.nameString}_#{sub.subSurfaceType}")
        end
      end
      audit&.decision(:geometry, 'windows rebuilt to FDWR limit',
                      inputs: { fdwr_limit: fdwr_lim.round(4), walls: census[:walls].size },
                      value: "resulting FDWR #{Geometry.exposed_walls(model)[:fdwr]&.round(4)}",
                      article: '3.2.1.4.(1)')
      true
    end

    # Add centroid-scaled skylights at an SRR limit (port of OPTION A): one skylight
    # per exposed conditioned roof, the roof polygon scaled about its centroid by
    # sqrt(fraction) — exact for convex roofs (a scaled convex polygon has exactly
    # fraction x the area).
    def apply_srr(model, srr_lim, skylight_construction, audit: nil)
      census = Geometry.exposed_roofs(model)
      return false if census[:roof_area_m2] < 0.1 || srr_lim > 1

      scale = Math.sqrt(srr_lim)
      census[:roofs].each do |surface|
        surface.subSurfaces.sort_by(&:nameString).each(&:remove)
        next if srr_lim < 0.001

        centroid = Geometry.vertex_centroid(surface.vertices)
        new_vertices = surface.vertices.map do |v|
          OpenStudio::Point3d.new(centroid.x + (v.x - centroid.x) * scale,
                                  centroid.y + (v.y - centroid.y) * scale,
                                  centroid.z + (v.z - centroid.z) * scale)
        end
        skylight = OpenStudio::Model::SubSurface.new(new_vertices, model)
        skylight.setSurface(surface)
        skylight.setSubSurfaceType('Skylight')
        skylight.setConstruction(skylight_construction)
        skylight.setName("#{surface.nameString}_Skylight")
      end
      audit&.decision(:geometry, 'skylights added at SRR limit',
                      inputs: { srr_limit: srr_lim.round(4), roofs: census[:roofs].size },
                      value: "resulting SRR #{Geometry.exposed_roofs(model)[:srr]&.round(4)}",
                      article: '3.2.1.4.(2)')
      true
    end
    end
  end
end
