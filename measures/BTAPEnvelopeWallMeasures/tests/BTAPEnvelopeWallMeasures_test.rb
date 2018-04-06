require 'openstudio'
require 'openstudio/measure/ShowRunnerOutput'
require 'fileutils'
require 'openstudio-standards'
begin
  require 'openstudio_measure_tester/test_helper'
rescue LoadError
  puts 'OpenStudio Measure Tester Gem not installed -- will not be able to aggregate and dashboard the results of tests'
end
require_relative '../measure.rb'
require 'minitest/autorun'


class BTAPExteriorWallMeasure_Test < Minitest::Test
  def test_create_building()
    # create an instance of the measure
    measure = BTAPExteriorWallMeasure.new

    # create an instance of a runner
    runner = OpenStudio::Measure::OSRunner.new(OpenStudio::WorkflowJSON.new)

    # make an empty model
    model = OpenStudio::Model::Model.new

    # test arguments and defaults
    arguments = measure.arguments(model)
    #check number of arguments.
    assert_equal(10, arguments.size)
    #check argument 0
    assert_equal('ecm_exterior_wall_conductance', arguments[0].name)
    assert_equal('baseline', arguments[0].defaultValueAsString)
    #check argument 1
    assert_equal('ecm_exterior_roof_conductance', arguments[1].name)
    assert_equal('baseline', arguments[1].defaultValueAsString)
    #check argument 2
    assert_equal('ecm_exterior_floor_conductance', arguments[2].name)
    assert_equal('baseline', arguments[2].defaultValueAsString)

    assert_equal('ecm_ground_wall_conductance', arguments[3].name)
    assert_equal('baseline', arguments[3].defaultValueAsString)
    #check argument 1
    assert_equal('ecm_ground_roof_conductance', arguments[4].name)
    assert_equal('baseline', arguments[4].defaultValueAsString)
    #check argument 2
    assert_equal('ecm_ground_floor_conductance', arguments[5].name)
    assert_equal('baseline', arguments[5].defaultValueAsString)
    #check argument 2
    assert_equal('ecm_exterior_window_conductance', arguments[6].name)
    assert_equal('baseline', arguments[6].defaultValueAsString)
    #check argument 2
    assert_equal('ecm_exterior_skylight_conductance', arguments[7].name)
    assert_equal('baseline', arguments[7].defaultValueAsString)
    #check argument 2
    assert_equal('ecm_exterior_door_conductance', arguments[8].name)
    assert_equal('baseline', arguments[8].defaultValueAsString)
    #check argument 2
    assert_equal('ecm_exterior_overhead_door_conductance', arguments[9].name)
    assert_equal('baseline', arguments[9].defaultValueAsString)


    #Set up test values to validate against.
    values = {}
    values['ecm_exterior_wall_conductance']           = '0.180'
    values['ecm_exterior_roof_conductance']           = '0.185'
    values['ecm_exterior_floor_conductance']          = '0.190'
    values['ecm_ground_wall_conductance']             = '0.195'
    values['ecm_ground_roof_conductance']             = '0.200'
    values['ecm_ground_floor_conductance']            = '0.205'
    values['ecm_exterior_window_conductance']         = '0.210'
    values['ecm_exterior_skylight_conductance']       = '0.215'
    values['ecm_exterior_door_conductance']           = '0.220'
    values['ecm_exterior_overhead_door_conductance']  = '0.225'

    # set argument values to values and run the measure
    argument_map = OpenStudio::Measure.convertOSArgumentVectorToMap(arguments)

    #set argument 0
    ecm_exterior_wall_conductance = arguments[0].clone
    assert(ecm_exterior_wall_conductance.setValue(values['ecm_exterior_wall_conductance']))
    argument_map['ecm_exterior_wall_conductance'] = ecm_exterior_wall_conductance


    #set argument 1
    ecm_exterior_roof_conductance = arguments[1].clone
    assert(ecm_exterior_roof_conductance.setValue(values['ecm_exterior_roof_conductance']))
    argument_map['ecm_exterior_roof_conductance'] = ecm_exterior_roof_conductance

    #set argument 2
    ecm_exterior_floor_conductance = arguments[2].clone
    assert(ecm_exterior_floor_conductance.setValue(values['ecm_exterior_floor_conductance']))
    argument_map['ecm_exterior_wall_conductance'] = ecm_exterior_floor_conductance

    #set argument 3
    ecm_ground_wall_conductance = arguments[3].clone
    assert(ecm_ground_wall_conductance.setValue(values['ecm_ground_wall_conductance']))
    argument_map['ecm_ground_wall_conductance'] = ecm_ground_wall_conductance

    #set argument 4
    ecm_ground_roof_conductance = arguments[4].clone
    assert(ecm_ground_roof_conductance.setValue(values['ecm_ground_floor_conductance']))
    argument_map['ecm_ground_roof_conductance'] = ecm_ground_roof_conductance

    #set argument 5
    ecm_ground_floor_conductance = arguments[5].clone
    assert(ecm_ground_floor_conductance.setValue(values['ecm_ground_roof_conductance']))
    argument_map['ecm_ground_floor_conductance'] = ecm_ground_floor_conductance

    #set argument 6
    ecm_exterior_window_conductance = arguments[6].clone
    assert(ecm_exterior_window_conductance.setValue(values['ecm_exterior_window_conductance']))
    argument_map['ecm_exterior_window_conductance'] = ecm_exterior_window_conductance

    #set argument 5
    ecm_exterior_skylight_conductance = arguments[7].clone
    assert(ecm_exterior_skylight_conductance.setValue(values['ecm_exterior_skylight_conductance']))
    argument_map['ecm_exterior_skylight_conductance'] = ecm_exterior_skylight_conductance

    #set argument 5
    ecm_exterior_door_conductance = arguments[8].clone
    assert(ecm_exterior_door_conductance.setValue(values['ecm_exterior_door_conductance']))
    argument_map['ecm_exterior_door_conductance'] = ecm_exterior_door_conductance

    #set argument 5
    ecm_exterior_overhead_door_conductance = arguments[9].clone
    assert(ecm_exterior_overhead_door_conductance.setValue(values['ecm_exterior_overhead_door_conductance']))
    argument_map['ecm_exterior_overhead_door_conductance'] = ecm_exterior_overhead_door_conductance


    #run the measure
    measure.run(model, runner, argument_map)
    result = runner.result
    assert(result.value.valueName == 'Success')
    #Check that the conductances have indeed changed to what they should be.
    outdoor_surfaces = BTAP::Geometry::Surfaces::filter_by_boundary_condition(model.getSurfaces(), "Outdoors")
    outdoor_subsurfaces = BTAP::Geometry::Surfaces::get_subsurfaces_from_surfaces(outdoor_surfaces)
    ground_surfaces = BTAP::Geometry::Surfaces::filter_by_boundary_condition(model.getSurfaces(), "Ground")


    # Test all walls
    unless values['ecm_exterior_wall_conductance'] == 'baseline'
      BTAP::Geometry::Surfaces::filter_by_surface_types(outdoor_surfaces, "Wall").each do |surface|
        assert_equal(values['ecm_exterior_wall_conductance'].to_f, BTAP::Geometry::Surfaces::get_surface_construction_conductance(surface).round(3))
      end
    else
      BTAP::Geometry::Surfaces::filter_by_surface_types(outdoor_surfaces, "Wall").each_with_index  do |surface, index|

      end
    end

    # Test all roofs
    BTAP::Geometry::Surfaces::filter_by_surface_types(outdoor_surfaces, "RoofCeiling").each do |surface|
      assert_equal(values['ecm_exterior_roof_conductance'], BTAP::Geometry::Surfaces::get_surface_construction_conductance(surface).round(3))
    end

    #Test all floors
    BTAP::Geometry::Surfaces::filter_by_surface_types(outdoor_surfaces, "Floor").each do |surface|
      assert_equal(values['ecm_exterior_floor_conductance'], BTAP::Geometry::Surfaces::get_surface_construction_conductance(surface).round(3))
    end

    #Test all ground walls
    BTAP::Geometry::Surfaces::filter_by_surface_types(ground_surfaces, "Wall").each do |surface|
      assert_equal(values['ecm_ground_wall_conductance'], BTAP::Geometry::Surfaces::get_surface_construction_conductance(surface).round(3))
    end

    #Test all ground roofs
    BTAP::Geometry::Surfaces::filter_by_surface_types(ground_surfaces, "RoofCeiling").each do |surface|
      assert_equal(values['ecm_ground_roof_conductance'], BTAP::Geometry::Surfaces::get_surface_construction_conductance(surface).round(3))
    end

    #Test all ground floors
    BTAP::Geometry::Surfaces::filter_by_surface_types(ground_surfaces, "Floor").each do |surface|
      assert_equal(values['ecm_ground_floor_conductance'], BTAP::Geometry::Surfaces::get_surface_construction_conductance(surface).round(3))
    end

    #Test window conductivity
    BTAP::Geometry::Surfaces::filter_subsurfaces_by_types(outdoor_subsurfaces, ["FixedWindow", "OperableWindow"]).each do |surface|
      assert_equal(values['ecm_exterior_window_conductance'], BTAP::Geometry::Surfaces::get_surface_construction_conductance(surface).round(3))
    end
    #Test skylight conductivity
    BTAP::Geometry::Surfaces::filter_subsurfaces_by_types(outdoor_subsurfaces, ["Skylight", "TubularDaylightDiffuser", "TubularDaylightDome"]).each do |surface|
      assert_equal(values['ecm_exterior_skylight_conductance'], BTAP::Geometry::Surfaces::get_surface_construction_conductance(surface).round(3))
    end
    #Test door conductivity
    BTAP::Geometry::Surfaces::filter_subsurfaces_by_types(outdoor_subsurfaces, ["Door", "GlassDoor"]).each do |surface|
      assert_equal(values['ecm_exterior_door_conductance'], BTAP::Geometry::Surfaces::get_surface_construction_conductance(surface).round(3))
    end

    #Test overhead conductivity
    BTAP::Geometry::Surfaces::filter_subsurfaces_by_types(outdoor_subsurfaces, ["OverheadDoor"]).each do |surface|
      assert_equal(values['ecm_exterior_overhead_door_conductance'], BTAP::Geometry::Surfaces::get_surface_construction_conductance(surface).round(3))
    end
  end
end
