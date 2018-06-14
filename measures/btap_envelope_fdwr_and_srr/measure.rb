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

require_relative 'resources/BTAPMeasureHelper'
class BTAPEnvelopeFDWRandSRR < OpenStudio::Measure::ModelMeasure
  attr_accessor :use_json_package, :use_string_double
  include(BTAPMeasureHelper)

  def initialize()
    super()
    @use_json_package = false
    @use_string_double = false
    @templates = [
        'NECB2011',
        'NECB2015'
    ]
    @limit_or_max_values = [
        'Limit',
        'Maximize'
    ]
    #Assuming a skylight area of this.
    @skylight_fixture_area = 0.0625
    @measure_interface_detailed = [

        {
            "name" => "wwr",
            "type" => "StringDouble",
            "display_name" => "FDWR (fraction) or a standard value of one of #{@templates}",
            "default_value" => 0.5,
            "max_double_value" => 1.0,
            "min_double_value" => 0.0,
            "valid_strings" => @templates,
            "is_required" => false
        },
        {
            "name" => "wwr_limit_or_max",
            "type" => "Choice",
            "display_name" => "FDWR Limit or Maximize?",
            "default_value" => "Maximize",
            "choices" => @limit_or_max_values,
            "is_required" => false
        },
        {
            "name" => "sillHeight",
            "type" => "Double",
            "display_name" => "Sill height (m)",
            "default_value" => 30.0,
            "max_double_value" => 100.0,
            "min_double_value" => 0.0,
            "is_required" => true
        },
        {
            "name" => "srr",
            "type" => "StringDouble",
            "display_name" => "FDWR (fraction) or a standard value of one of #{@templates}",
            "default_value" => 0.5,
            "max_double_value" => 1.0,
            "min_double_value" => 0.0,
            "valid_strings" => @templates,
            "is_required" => false
        },
        {
            "name" => "srr_limit_or_max",
            "type" => "Choice",
            "display_name" => "SRR Limit or Maximize?",
            "default_value" => "Maximize",
            "choices" => @limit_or_max_values,
            "is_required" => false
        },
        {
            "name" => "skylight_fixture_area",
            "type" => "Double",
            "display_name" => "Area of skylight fixtures used (m2)",
            "default_value" => 0.0625,
            "max_double_value" => 5.0,
            "min_double_value" => 0.0,
            "is_required" => false
        }

    ]

  end


  # override name to return the name of your script
  def name
    return 'BTAPEnvelopeFDWRAndSRR '
  end

  # return a vector of arguments


  # define what happens when the measure is run
  def run(model, runner, user_arguments)
    super(model, runner, user_arguments)


    hdd = nil
    standard = standard = Standard.new


    initial_wwr = standard.get_outdoor_subsurface_ratio(model, surface_type = "Wall")
    initial_srr = standard.get_outdoor_subsurface_ratio(model, surface_type = "RoofCeiling")
    runner.registerInitialCondition("The model's initial FDWR = #{initial_wwr} SRR = #{initial_srr}")


    # use the built-in error checking
    if !runner.validateUserArguments(arguments(model), user_arguments)
      return false
    end

    # assign the user inputs to variables
    arguments = validate_and_get_arguments_in_hash(model, runner, user_arguments)
    return false if false == arguments




    srr = arguments['srr']
    wwr = arguments['wwr']
    srr_limit_or_max = arguments['srr_limit_or_max']
    wwr_limit_or_max = arguments['wwr_limit_or_max']
    sillHeight = arguments['sillHeight']


    if @templates.include?(wwr) or @templates.include?(srr)
      raise("No weatherfile path was specified for model. Please ensure a weather file was added to the model.") if model.weatherFile.empty?
      standard = Standard.build("#{wwr}_LargeOffice")
      hdd = standard.get_necb_hdd18(model)
    end

    # check reasonableness of fraction
    if @templates.include?(wwr)
      #if wwr = 'NECB2011' or 'NECB2015' get proper wwr for hdd of model
      standard = Standard.build("#{wwr}_LargeOffice")
      raise("No weatherfile path was specified for model. Please ensure a weather file was added to the model.") if model.weatherFile.empty?
      hdd = standard.get_necb_hdd18(model)
      srr = standard.get_standards_constant('skylight_to_roof_ratio_max_value')
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
      #if wwr = 'NECB2011' or 'NECB2015' get proper wwr for hdd of model
      standard = Standard.build("#{wwr}_LargeOffice")
      srr = standard.get_standards_constant('skylight_to_roof_ratio_max_value')
    else
      if (srr.to_f <= 0) || (srr.to_f >= 1)
        runner.registerError("Window to Wall Ratio must be greater than 0 and less than 1 or one of the following templates #{@templates}")
        return false
      else
        srr = srr.to_f
      end
    end


    # check reasonableness of sill
    if sillHeight.to_f <= 0
      runner.registerError('Sill height must be > 0.')
      return false
    elsif sillHeight.to_f > 360
      runner.registerWarning("#{sillHeight} inches seems like an unusually high sill height.")
    elsif sillHeight.to_f > 9999
      runner.registerError("#{sillHeight} inches is above the measure limit for sill height.")
      return false
    end

    # flag to track warning for new windows without construction
    if wwr_limit_or_max.downcase == 'Maximize'.downcase
      standard.apply_max_fdwr(model, runner, sillHeight.to_f, wwr.to_f)
    else
      standard.apply_limit_to_subsurface_ratio(model, wwr, surface_type = "Wall")
    end
    if srr_limit_or_max.downcase == 'Maximize'.downcase
      standard.apply_max_srr(model, runner, srr.to_f, @skylight_fixture_area)
    else
      standard.apply_limit_to_subsurface_ratio(model, srr, surface_type = "RoofCeiling")
    end
    wwr = standard.get_outdoor_subsurface_ratio(model, surface_type = "Wall")
    srr = standard.get_outdoor_subsurface_ratio(model, surface_type = "RoofCeiling")
    runner.registerFinalCondition("The model's initial FDWR = #{wwr} SRR = #{srr}")
    return true
  end
end

# this allows the measure to be used by the application
BTAPEnvelopeFDWRandSRR.new.registerWithApplication
