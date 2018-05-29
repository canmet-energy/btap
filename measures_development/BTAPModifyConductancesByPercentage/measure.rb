require "#{File.dirname(__FILE__)}/resources/os_lib_reporting"
require "#{File.dirname(__FILE__)}/resources/os_lib_schedules"
require "#{File.dirname(__FILE__)}/resources/os_lib_helper_methods"

# see the URL below for information on how to write OpenStudio measures
# http://nrel.github.io/OpenStudio-user-documentation/reference/measure_writing_guide/

# start the measure
class BTAPModifyConductancesByPercentage < OpenStudio::Measure::ModelMeasure

  # human readable name
  def name
    return "BTAP Modify Conductances by Percentage"
  end

  # human readable description
  def description
    return "Modifies wall, roof and floor conductances by percentage"
  end

  # human readable description of modeling approach
  def modeler_description
    return "Modifies wall, roof and floor conductances by percentage"
  end

  # define the arguments that the user will input
  def arguments()
    args = OpenStudio::Ruleset::OSArgumentVector.new
    
    wall_cond_percentage = OpenStudio::Ruleset::OSArgument::makeDoubleArgument('wall_cond_percentage',true)
    wall_cond_percentage.setDisplayName('Wall Conductance Modifier (%)')
    wall_cond_percentage.setDefaultValue(0)
    args << wall_cond_percentage
     
    floor_cond_percentage = OpenStudio::Ruleset::OSArgument::makeDoubleArgument('floor_cond_percentage',true)
    floor_cond_percentage.setDisplayName('Floor Conductance Modifier (%)')
    floor_cond_percentage.setDefaultValue(0)
    args << floor_cond_percentage
    
    roof_cond_percentage = OpenStudio::Ruleset::OSArgument::makeDoubleArgument('roof_cond_percentage',true)
    roof_cond_percentage.setDisplayName('Roof Conductance Modifier (%)')
    roof_cond_percentage.setDefaultValue(0)
    args << roof_cond_percentage
    
    return args
  end

  # define what happens when the measure is run
  def run( runner, user_arguments)
    
    
    # get sql, model, and web assets
    setup = OsLib_Reporting.setup(runner)
    unless setup
      return false
    end
    model = setup[:model]
    # workspace = setup[:workspace]
    sql_file = setup[:sqlFile]
    web_asset_path = setup[:web_asset_path]
    model.setSqlFile( sql_file )
    super(model, runner, user_arguments)
    # reporting final condition
    runner.registerInitialCondition('Gathering data from EnergyPlus SQL file and OSM model.')
    

    # use the built-in error checking
    if !runner.validateUserArguments(arguments(), user_arguments)
      return false
    end
    
    wall_cond_percentage = runner.getDoubleArgumentValue('wall_cond_percentage',user_arguments)
    floor_cond_percentage = runner.getDoubleArgumentValue('floor_cond_percentage',user_arguments)
    roof_cond_percentage = runner.getDoubleArgumentValue('roof_cond_percentage',user_arguments)
    
    if wall_cond_percentage < -100.0
      runner.registerError("Wall Conductance modifier percentage 'wall_cond_percentage' is #{wall_cond_percentage}; must be greater than -100%")
      return false
    end
    if floor_cond_percentage < -100.0
      runner.registerError("Floor Conductance modifier percentage 'floor_cond_percentage' is #{floor_cond_percentage}; must be greater than -100%")
      return false
    end
    if roof_cond_percentage < -100.0
      runner.registerError("Roof Conductance modifier percentage 'roof_cond_percentage' is #{roof_cond_percentage}; must be greater than -100%")
      return false
    end
    #BTAP::Geometry::Surfaces::filter_by_surface_types(surfaces,surfaceTypes)
    #BTAP::Geometry::Surfaces::get_surface_construction_conductance(surface)
    #BTAP::Geometry::Surfaces::set_surfaces_construction_conductance(surfaces,conductance)
    #BTAP::Geometry::Surfaces::filter_by_surface_types(surfaces,surfaceTypes)
    surface_array = BTAP::Geometry::Spaces::get_surfaces_from_spaces(model,model.getSpaces)
    
    unless wall_cond_percentage == 0
      wall_surfaces = BTAP::Geometry::Surfaces::filter_by_surface_types(surface_array,"Wall")
      wall_surfaces.each do |surface|
        conductance = BTAP::Geometry::Surfaces::get_surface_construction_conductance(surface)
        new_conductance = conductance*(1+wall_cond_percentage/100)
        BTAP::Geometry::Surfaces::set_surfaces_construction_conductance([surface],new_conductance)
      end
    end
    
    unless floor_cond_percentage == 0
      floor_surfaces = BTAP::Geometry::Surfaces::filter_by_surface_types(surface_array,"Floor")
      floor_surfaces.each do |surface|
        conductance = BTAP::Geometry::Surfaces::get_surface_construction_conductance(surface)
        new_conductance = conductance*(1+floor_cond_percentage/100)
        BTAP::Geometry::Surfaces::set_surfaces_construction_conductance([surface],new_conductance)
      end
    end
    
    unless roof_cond_percentage == 0
      roof_surfaces = BTAP::Geometry::Surfaces::filter_by_surface_types(surface_array,"RoofCeiling")
      roof_surfaces.each do |surface|
        conductance = BTAP::Geometry::Surfaces::get_surface_construction_conductance(surface)
        new_conductance = conductance*(1+roof_cond_percentage/100)
        BTAP::Geometry::Surfaces::set_surfaces_construction_conductance([surface],new_conductance)
      end
    end
    qaqc = BTAP.perform_qaqc(model)
    qaqc[:ecm]={}
    qaqc[:ecm][:wall_conductance_modifier] = wall_cond_percentage
    qaqc[:ecm][:floor_conductance_modifier] = floor_cond_percentage
    qaqc[:ecm][:roof_conductance_modifier] = roof_cond_percentage
    File.open("qaqc.json", 'w') {|f| f.write(JSON.pretty_generate(qaqc)) }
    return true

  end
  
end

# register the measure to be used by the application
BTAPModifyConductancesByPercentage.new.registerWithApplication
