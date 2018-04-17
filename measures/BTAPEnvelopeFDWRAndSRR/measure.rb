# *******************************************************************************
# OpenStudio(R), Copyright (c) 2008-2018, Alliance for Sustainable Energy, LLC.
# All rights reserved.
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are met:
#
# (1) Redistributions of source code must retain the above copyright notice,
# this list of conditions and the following disclaimer.
#
# (2) Redistributions in binary form must reproduce the above copyright notice,
# this list of conditions and the following disclaimer in the documentation
# and/or other materials provided with the distribution.
#
# (3) Neither the name of the copyright holder nor the names of any contributors
# may be used to endorse or promote products derived from this software without
# specific prior written permission from the respective party.
#
# (4) Other than as required in clauses (1) and (2), distributions in any form
# of modifications or other derivative works may not use the "OpenStudio"
# trademark, "OS", "os", or any other confusingly similar designation without
# specific prior written permission from Alliance for Sustainable Energy, LLC.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDER(S) AND ANY CONTRIBUTORS
# "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO,
# THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
# ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER(S), ANY CONTRIBUTORS, THE
# UNITED STATES GOVERNMENT, OR THE UNITED STATES DEPARTMENT OF ENERGY, NOR ANY OF
# THEIR EMPLOYEES, BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL,
# EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT
# OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS
# INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT,
# STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY
# OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
# *******************************************************************************


class BTAPEnvelopeFDWRandSRR < OpenStudio::Measure::ModelMeasure
  def initialize()
    super()
    @templates = [
        'NECB2011',
        'NECB2015'
    ]

    @limit_or_max_values = [
        'limit',
        'maximize'
    ]
  end


  # override name to return the name of your script
  def name
    return 'Set FDWR and SRR for model. Or set Max NECB values based on NECB or epw HDD value. '
  end

  # return a vector of arguments
  def arguments(model)
    args = OpenStudio::Measure::OSArgumentVector.new

    # make double argument for wwr
    wwr = OpenStudio::Measure::OSArgument.makeStringArgument('wwr', true)
    wwr.setDisplayName("FDWR (fraction) or a standard value of one of #{@templates}")
    wwr.setDefaultValue('NECB2011')
    args << wwr

    # make choice argument for wwr_limit_or_max
    choices = OpenStudio::StringVector.new
    @limit_or_max_values.each do |choice|
      choices << choice
    end
    wwr_limit_or_max = OpenStudio::Measure::OSArgument.makeChoiceArgument('wwr_limit_or_max', choices, true)
    wwr_limit_or_max.setDisplayName("FDWR Limit or Maximize?")
    wwr_limit_or_max.setDefaultValue('maximize')
    args << wwr_limit_or_max


    # make double argument for wwr
    srr = OpenStudio::Measure::OSArgument.makeStringArgument('srr', true)
    srr.setDisplayName("SSR (fraction) or a standard value of one of #{@templates}")
    srr.setDefaultValue('NECB2011')
    args << srr

    # make choice argument for srr_limit_or_max
    choices = OpenStudio::StringVector.new
    @limit_or_max_values.each do |choice|
      choices << choice
    end
    srr_limit_or_max = OpenStudio::Measure::OSArgument.makeChoiceArgument('srr_limit_or_max', choices, true)
    srr_limit_or_max.setDisplayName("SRR Limit or Maximize?")
    srr_limit_or_max.setDefaultValue('maximize')
    args << srr_limit_or_max


    # make double argument for sillHeight
    sillHeight = OpenStudio::Measure::OSArgument.makeDoubleArgument('sillHeight', true)
    sillHeight.setDisplayName('Sill Height (in).')
    sillHeight.setDefaultValue(30.0)
    args << sillHeight
    return args
  end

  # define what happens when the measure is run
  def run(model, runner, user_arguments)
    super(model, runner, user_arguments)

    #Check to see if argument is a template name and a MAX
    #First get HDD from file.
    #Get SRR and FDWR Max values.
    #


    # use the built-in error checking
    if !runner.validateUserArguments(arguments(model), user_arguments)
      return false
    end

    # assign the user inputs to variables
    srr = runner.getStringArgumentValue('srr', user_arguments)
    wwr = runner.getStringArgumentValue('wwr', user_arguments)
    srr_limit_or_max = runner.getStringArgumentValue('srr_limit_or_max', user_arguments)
    wwr_limit_or_max = runner.getStringArgumentValue('wwr_limit_or_max', user_arguments)
    sillHeight = runner.getDoubleArgumentValue('sillHeight', user_arguments)


    # check reasonableness of fraction
    if @templates.include?(wwr)
      #Get template FDWR value from standard.
    else
      if (wwr.to_f <= 0) || (wwr.to_f >= 1)
        runner.registerError("Window to Wall Ratio must be greater than 0 and less than 1 or one of the following templates #{@templates}")
        return false
      else
        wwr = wwr.to_f
      end
    end

    # check reasonableness of fraction
    if @templates.include?(srr)
      #Get template FDWR value from standard.
    else
      if (srr.to_f <= 0) || (srr.to_f >= 1)
        runner.registerError("Window to Wall Ratio must be greater than 0 and less than 1 or one of the following templates #{@templates}")
        return false
      else
        srr = srr.to_f
      end
    end




    # check reasonableness of fraction
    if sillHeight.to_f <= 0
      runner.registerError('Sill height must be > 0.')
      return false
    elsif sillHeight.to_f > 360
      runner.registerWarning("#{sillHeight} inches seems like an unusually high sill height.")
    elsif sillHeight.to_f > 9999
      runner.registerError("#{sillHeight} inches is above the measure limit for sill height.")
      return false
    end

    # setup OpenStudio units that we will need
    unit_sillHeight_ip = OpenStudio.createUnit('ft').get
    unit_sillHeight_si = OpenStudio.createUnit('m').get
    unit_area_ip = OpenStudio.createUnit('ft^2').get
    unit_area_si = OpenStudio.createUnit('m^2').get


    # define starting units
    sillHeight_ip = OpenStudio::Quantity.new(sillHeight / 12, unit_sillHeight_ip)

    # unit conversion
    sillHeight_si = OpenStudio.convert(sillHeight_ip, unit_sillHeight_si).get

    # hold data for initial condition
    starting_gross_ext_wall_area = 0.0 # includes windows and doors
    starting_ext_window_area = 0.0

    # hold data for final condition
    final_gross_ext_wall_area = 0.0 # includes windows and doors
    final_ext_window_area = 0.0

    # flag for not applicable
    exterior_walls = false
    windows_added = false

    # flag to track notifications of zone multipliers
    space_warning_issued = []

    # flag to track warning for new windows without construction
    empty_const_warning = false


    # loop through surfaces finding exterior walls with proper orientation
    outdoors_surfaces = BTAP::Geometry::Surfaces::filter_by_boundary_condition(model.getSurfaces(), "Outdoors")
    walls = BTAP::Geometry::Surfaces::filter_by_surface_types(outdoors_surfaces, 'Wall')

    walls.each do |surface|
      if surface.space.empty?
        runner.registerWarning("#{surface.name} doesn't have a parent space and won't be included in the measure reporting or modifications.")
        next
      end
      # get surface_gross_area accounting for zone_multiplier
      space = surface.space
      zone = space.get.thermalZone unless space.empty?
      zone.empty? ? zone_multiplier = 1 : zone_multiplier = zone.get.multiplier
      surface_gross_area = surface.grossArea * zone_multiplier

      # loop through sub surfaces and add area including multiplier
      ext_window_area = 0
      surface.subSurfaces.each do |subSurface|
        ext_window_area += subSurface.grossArea * subSurface.multiplier * zone_multiplier
      end

      starting_gross_ext_wall_area += surface_gross_area
      starting_ext_window_area += ext_window_area

      new_window = surface.setWindowToWallRatio(wwr, sillHeight_si.value, true)
      if new_window.empty?
        runner.registerWarning("The requested window to wall ratio for surface '#{surface.name}' was too large. Fenestration was not altered for this surface.")
      else
        windows_added = true
        # warn user if resulting window doesn't have a construction, as it will result in failed simulation. In the future may use logic from starting windows to apply construction to new window.
        if new_window.get.construction.empty? && (empty_const_warning == false)
          runner.registerWarning('one or more resulting windows do not have constructions. This script is intended to be used with models using construction sets versus hard assigned constructions.')
          empty_const_warning = true
        end
      end
    end

    # report initial condition wwr
    # the initial and final ratios does not currently account for either sub-surface or zone multipliers.
    starting_wwr = format('%.02f', (starting_ext_window_area / starting_gross_ext_wall_area))
    runner.registerInitialCondition("The model's initial window to wall ratio was #{starting_wwr}.")

    if !windows_added
      runner.registerAsNotApplicable("The model has exterior #{facade.downcase} walls, but no windows could be added with the requested window to wall ratio")
      return true
    end

    # data for final condition wwr
    walls.each do |s|
      if s.space.empty?
        runner.registerWarning("#{s.name} doesn't have a parent space and won't be included in the measure reporting or modifications.")
        next
      end


      # get surface area adjusting for zone multiplier
      space = s.space
      if !space.empty?
        zone = space.get.thermalZone
      end
      if !zone.empty?
        zone_multiplier = zone.get.multiplier
        if zone_multiplier > 1
        end
      else
        zone_multiplier = 1 # space is not in a thermal zone
      end
      surface_gross_area = s.grossArea * zone_multiplier

      # loop through sub surfaces and add area including multiplier
      ext_window_area = 0
      s.subSurfaces.each do |subSurface| # onlky one and should have multiplier of 1
        ext_window_area += subSurface.grossArea * subSurface.multiplier * zone_multiplier
      end

      final_gross_ext_wall_area += surface_gross_area
      final_ext_window_area += ext_window_area
    end


    # get delta in ft^2 for final - starting window area
    increase_window_area_si = OpenStudio::Quantity.new(final_ext_window_area - starting_ext_window_area, unit_area_si)
    increase_window_area_ip = OpenStudio.convert(increase_window_area_si, unit_area_ip).get


    # report final condition
    final_wwr = format('%.02f', (final_ext_window_area / final_gross_ext_wall_area))
    runner.registerFinalCondition("The model's final window to wall ratio  is #{final_wwr}. Window area increased by #{neat_numbers(increase_window_area_ip.value, 0)} (ft^2).")

    return true
  end

  # short def to make numbers pretty (converts 4125001.25641 to 4,125,001.26 or 4,125,001). The definition be called through this measure
  def neat_numbers(number, roundto = 2) # round to 0 or 2)
    # round to zero or two decimals
    if roundto == 2
      number = format '%.2f', number
    else
      number = number.round
    end
    # regex to add commas
    number.to_s.reverse.gsub(/([0-9]{3}(?=([0-9])))/, '\\1,').reverse
  end


  # Reduces the WWR to the values specified by the NECB
  # NECB 3.2.1.4
  def apply_standard_window_to_wall_ratio(model)
    # Loop through all spaces in the model, and
    # per the PNNL PRM Reference Manual, find the areas
    # of each space conditioning category (res, nonres, semi-heated)
    # separately.  Include space multipliers.
    nr_wall_m2 = 0.001 # Avoids divide by zero errors later
    nr_wind_m2 = 0
    res_wall_m2 = 0.001
    res_wind_m2 = 0
    sh_wall_m2 = 0.001
    sh_wind_m2 = 0
    total_wall_m2 = 0.001
    total_subsurface_m2 = 0.0
    # Store the space conditioning category for later use
    space_cats = {}
    model.getSpaces.sort.each do |space|
      # Loop through all surfaces in this space
      wall_area_m2 = 0
      wind_area_m2 = 0
      space.surfaces.sort.each do |surface|
        # Skip non-outdoor surfaces
        next unless surface.outsideBoundaryCondition == 'Outdoors'
        # Skip non-walls
        next unless surface.surfaceType.casecmp('wall').zero?
        # This wall's gross area (including window area)
        wall_area_m2 += surface.grossArea * space.multiplier
        # Subsurfaces in this surface
        surface.subSurfaces.sort.each do |ss|
          wind_area_m2 += ss.netArea * space.multiplier
        end
      end

      # Determine the space category
      # zTODO This should really use the heating/cooling loads
      # from the proposed building.  However, in an attempt
      # to avoid another sizing run just for this purpose,
      # conditioned status is based on heating/cooling
      # setpoints.  If heated-only, will be assumed Semiheated.
      # The full-bore method is on the next line in case needed.
      # cat = thermal_zone_conditioning_category(space, template, climate_zone)
      cooled = space_cooled?(space)
      heated = space_heated?(space)
      cat = 'Unconditioned'
      # Unconditioned
      if !heated && !cooled
        cat = 'Unconditioned'
        # Heated-Only
      elsif heated && !cooled
        cat = 'Semiheated'
        # Heated and Cooled
      else
        res = thermal_zone_residential?(space.thermalZone.get)
        cat = if res
                'ResConditioned'
              else
                'NonResConditioned'
              end
      end
      space_cats[space] = cat
      # NECB2011 keep track of totals for NECB regardless of conditioned or not.
      total_wall_m2 += wall_area_m2
      total_subsurface_m2 += wind_area_m2 # this contains doors as well.

      # Add to the correct category
      case cat
        when 'Unconditioned'
          next # Skip unconditioned spaces
        when 'NonResConditioned'
          nr_wall_m2 += wall_area_m2
          nr_wind_m2 += wind_area_m2
        when 'ResConditioned'
          res_wall_m2 += wall_area_m2
          res_wind_m2 += wind_area_m2
        when 'Semiheated'
          sh_wall_m2 += wall_area_m2
          sh_wind_m2 += wind_area_m2
      end
    end

    # Calculate the WWR of each category
    wwr_nr = ((nr_wind_m2 / nr_wall_m2) * 100.0).round(1)
    wwr_res = ((res_wind_m2 / res_wall_m2) * 100).round(1)
    wwr_sh = ((sh_wind_m2 / sh_wall_m2) * 100).round(1)
    fdwr = ((total_subsurface_m2 / total_wall_m2) * 100).round(1) # used by NECB2011

    # Convert to IP and report
    nr_wind_ft2 = OpenStudio.convert(nr_wind_m2, 'm^2', 'ft^2').get
    nr_wall_ft2 = OpenStudio.convert(nr_wall_m2, 'm^2', 'ft^2').get

    res_wind_ft2 = OpenStudio.convert(res_wind_m2, 'm^2', 'ft^2').get
    res_wall_ft2 = OpenStudio.convert(res_wall_m2, 'm^2', 'ft^2').get

    sh_wind_ft2 = OpenStudio.convert(sh_wind_m2, 'm^2', 'ft^2').get
    sh_wall_ft2 = OpenStudio.convert(sh_wall_m2, 'm^2', 'ft^2').get

    OpenStudio.logFree(OpenStudio::Info, 'openstudio.standards.Model', "WWR NonRes = #{wwr_nr.round}%; window = #{nr_wind_ft2.round} ft2, wall = #{nr_wall_ft2.round} ft2.")
    OpenStudio.logFree(OpenStudio::Info, 'openstudio.standards.Model', "WWR Res = #{wwr_res.round}%; window = #{res_wind_ft2.round} ft2, wall = #{res_wall_ft2.round} ft2.")
    OpenStudio.logFree(OpenStudio::Info, 'openstudio.standards.Model', "WWR Semiheated = #{wwr_sh.round}%; window = #{sh_wind_ft2.round} ft2, wall = #{sh_wall_ft2.round} ft2.")

    # WWR limit
    wwr_lim = 40.0

    # Check against WWR limit
    red_nr = wwr_nr > wwr_lim
    red_res = wwr_res > wwr_lim
    red_sh = wwr_sh > wwr_lim

    # NECB FDWR limit
    hdd = self.get_necb_hdd18(model)
    fdwr_lim = (max_fwdr(hdd) * 100.0).round(1)
    # puts "Current FDWR is #{fdwr}, must be less than #{fdwr_lim}."
    # puts "Current subsurf area is #{total_subsurface_m2} and gross surface area is #{total_wall_m2}"
    # Stop here unless windows / doors need reducing
    return true unless fdwr > fdwr_lim
    OpenStudio.logFree(OpenStudio::Info, 'openstudio.standards.Model', "Reducing the size of all windows (by raising sill height) to reduce window area down to the limit of #{wwr_lim.round}%.")
    # Determine the factors by which to reduce the window / door area
    mult = fdwr_lim / fdwr
    # Reduce the window area if any of the categories necessary
    model.getSpaces.sort.each do |space|
      # Loop through all surfaces in this space
      space.surfaces.sort.each do |surface|
        # Skip non-outdoor surfaces
        next unless surface.outsideBoundaryCondition == 'Outdoors'
        # Skip non-walls
        next unless surface.surfaceType == 'Wall'
        # Subsurfaces in this surface
        surface.subSurfaces.sort.each do |ss|
          # Reduce the size of the window
          red = 1.0 - mult
          sub_surface_reduce_area_by_percent_by_raising_sill(ss, red)
        end
      end
    end
    return true
  end

  # Reduces the SRR to the values specified by the PRM. SRR reduction
  # will be done by shrinking vertices toward the centroid.
  #
  def apply_standard_skylight_to_roof_ratio(model)
    # Loop through all spaces in the model, and
    # per the PNNL PRM Reference Manual, find the areas
    # of each space conditioning category (res, nonres, semi-heated)
    # separately.  Include space multipliers.
    nr_wall_m2 = 0.001 # Avoids divide by zero errors later
    nr_sky_m2 = 0
    res_wall_m2 = 0.001
    res_sky_m2 = 0
    sh_wall_m2 = 0.001
    sh_sky_m2 = 0
    total_roof_m2 = 0.001
    total_subsurface_m2 = 0
    model.getSpaces.sort.each do |space|
      # Loop through all surfaces in this space
      wall_area_m2 = 0
      sky_area_m2 = 0
      space.surfaces.sort.each do |surface|
        # Skip non-outdoor surfaces
        next unless surface.outsideBoundaryCondition == 'Outdoors'
        # Skip non-walls
        next unless surface.surfaceType == 'RoofCeiling'
        # This wall's gross area (including skylight area)
        wall_area_m2 += surface.grossArea * space.multiplier
        # Subsurfaces in this surface
        surface.subSurfaces.sort.each do |ss|
          sky_area_m2 += ss.netArea * space.multiplier
        end
      end

      # Determine the space category
      cat = 'NonRes'
      if space_residential?(space)
        cat = 'Res'
      end
      # if space.is_semiheated
      # cat = 'Semiheated'
      # end

      # Add to the correct category
      case cat
        when 'NonRes'
          nr_wall_m2 += wall_area_m2
          nr_sky_m2 += sky_area_m2
        when 'Res'
          res_wall_m2 += wall_area_m2
          res_sky_m2 += sky_area_m2
        when 'Semiheated'
          sh_wall_m2 += wall_area_m2
          sh_sky_m2 += sky_area_m2
      end
      total_roof_m2 += wall_area_m2
      total_subsurface_m2 += sky_area_m2
    end

    # Calculate the SRR of each category
    srr_nr = ((nr_sky_m2 / nr_wall_m2) * 100).round(1)
    srr_res = ((res_sky_m2 / res_wall_m2) * 100).round(1)
    srr_sh = ((sh_sky_m2 / sh_wall_m2) * 100).round(1)
    srr = ((total_subsurface_m2 / total_roof_m2) * 100.0).round(1)
    OpenStudio.logFree(OpenStudio::Info, 'openstudio.standards.Model', "The skylight to roof ratios (SRRs) are: NonRes: #{srr_nr.round}%, Res: #{srr_res.round}%.")

    # SRR limit
    srr_lim = self.get_standards_constant('skylight_to_roof_ratio_max_value') * 100.0
    # Check against SRR limit
    red_nr = srr_nr > srr_lim
    red_res = srr_res > srr_lim
    red_sh = srr_sh > srr_lim

    # Stop here unless windows need reducing
    return true unless srr > srr_lim
    OpenStudio.logFree(OpenStudio::Info, 'openstudio.standards.Model', "Reducing the size of all windows (by raising sill height) to reduce window area down to the limit of #{srr_lim.round}%.")
    # Determine the factors by which to reduce the window / door area
    mult = srr_lim / srr

    # Reduce the subsurface areas
    model.getSpaces.sort.each do |space|
      # Loop through all surfaces in this space
      space.surfaces.sort.each do |surface|
        # Skip non-outdoor surfaces
        next unless surface.outsideBoundaryCondition == 'Outdoors'
        # Skip non-walls
        next unless surface.surfaceType == 'RoofCeiling'
        # Subsurfaces in this surface
        surface.subSurfaces.sort.each do |ss|
          # Reduce the size of the subsurface
          red = 1.0 - mult
          sub_surface_reduce_area_by_percent_by_shrinking_toward_centroid(ss, red)
        end
      end
    end

    return true
  end

  # @author phylroy.lopez@nrcan.gc.ca
  # @param hdd [Float]
  # @return [Double] a constant float
  def max_fwdr(hdd)
    #get formula from json database.
    return eval(self.get_standards_formula('fdwr_formula'))
  end


end

# this allows the measure to be used by the application
BTAPEnvelopeFDWRandSRR.new.registerWithApplication
