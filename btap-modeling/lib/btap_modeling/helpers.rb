module BtapModeling
  # The three small BTAP geometry helpers the wizards depend on, ported
  # standalone (BTAP::Geometry.match_surfaces / rotate_model and
  # BTAP::Geometry::Surfaces.set_surfaces_boundary_condition).
  module Helpers
    module_function

    # Match interior surfaces between every pair of spaces (legacy semantics:
    # sorted pairwise matchSurfaces).
    def match_surfaces(model)
      model.getSpaces.sort_by(&:nameString).each do |space1|
        model.getSpaces.sort_by(&:nameString).each do |space2|
          space1.matchSurfaces(space2)
        end
      end
      model
    end

    # Set an outside boundary condition on surfaces; Adiabatic removes
    # subsurfaces first (an adiabatic surface cannot carry them).
    def set_boundary_condition(surfaces, boundary_condition)
      unless OpenStudio::Model::Surface.validOutsideBoundaryConditionValues.include?(boundary_condition)
        raise(ArgumentError, "invalid outside boundary condition '#{boundary_condition}'")
      end

      surfaces.each do |surface|
        surface.subSurfaces.each(&:remove) if boundary_condition == 'Adiabatic'
        surface.setOutsideBoundaryCondition(boundary_condition)
      end
      surfaces
    end

    # Rotate every planar surface group about the z axis.
    def rotate_model(model, degrees)
      transformation = OpenStudio::Transformation.rotation(OpenStudio::Vector3d.new(0, 0, 1),
                                                           degrees * Math::PI / 180)
      model.getPlanarSurfaceGroups.each { |group| group.changeTransformation(transformation) }
      model
    end
    # Above-ground storey count: the declared standards value when set, else
    # counted from storeys with any at-or-above-grade space. Lived in hvac's
    # costing module historically, but it is pure geometry and the authoring
    # systems (vav_reheat zoning) need it — so it lives here and costing
    # delegates.
    def above_ground_storeys(model)
      declared = model.getBuilding.standardsNumberOfAboveGroundStories
      return declared.get if declared.is_initialized

      model.getBuildingStorys.count do |story|
        story.spaces.any? { |s| s.zOrigin.to_f >= -0.01 }
      end.clamp(1, 1000)
    end

  end
end
