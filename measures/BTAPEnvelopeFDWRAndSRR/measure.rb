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
  # override name to return the name of your script
  def name
    return 'Set FDWR and SRR for model. '
  end

  # return a vector of arguments
  def arguments(model)
    args = OpenStudio::Measure::OSArgumentVector.new

    # make double argument for wwr
    wwr = OpenStudio::Measure::OSArgument.makeDoubleArgument('wwr', true)
    wwr.setDisplayName('Window to Wall Ratio (fraction).')
    wwr.setDefaultValue(0.4)
    args << wwr

    # make double argument for wwr
    srr = OpenStudio::Measure::OSArgument.makeDoubleArgument('srr', true)
    srr.setDisplayName('Skylight to Roof Ratio (fraction).')
    srr.setDefaultValue(0.05)
    args << srr


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

    # use the built-in error checking
    if !runner.validateUserArguments(arguments(model), user_arguments)
      return false
    end

    # assign the user inputs to variables
    srr = runner.getDoubleArgumentValue('srr', user_arguments)
    wwr = runner.getDoubleArgumentValue('wwr', user_arguments)
    sillHeight = runner.getDoubleArgumentValue('sillHeight', user_arguments)


    # check reasonableness of fraction
    if (wwr <= 0) || (wwr >= 1)
      runner.registerError('Window to Wall Ratio must be greater than 0 and less than 1.')
      return false
    end

    if (srr <= 0) || (srr >= 1)
      runner.registerError('Skylight Ratio must be greater than 0 and less than 1.')
      return false
    end

    # check reasonableness of fraction
    if sillHeight <= 0
      runner.registerError('Sill height must be > 0.')
      return false
    elsif sillHeight > 360
      runner.registerWarning("#{sillHeight} inches seems like an unusually high sill height.")
    elsif sillHeight > 9999
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

    # get delta in ft^2 for final - starting window area
    increase_window_area_si = OpenStudio::Quantity.new(final_ext_window_area - starting_ext_window_area, unit_area_si)
    increase_window_area_ip = OpenStudio.convert(increase_window_area_si, unit_area_ip).get



    # report final condition
    final_wwr = format('%.02f', (final_ext_window_area / final_gross_ext_wall_area))
    runner.registerFinalCondition("The model's final window to wall ratio  is #{final_wwr}. Window area increased by #{neat_numbers(increase_window_area_ip.value, 0)} (ft^2).")

    return true
  end
end

# this allows the measure to be used by the application
BTAPEnvelopeFDWRandSRR.new.registerWithApplication
