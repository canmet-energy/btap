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
        'Limit',
        'Maximize'
    ]

    #Assuming a skylight area of this.
    @skylight_fixture_area = 0.0625
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
    wwr_limit_or_max.setDefaultValue('Maximize')
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
    srr_limit_or_max.setDefaultValue('Maximize')
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
    standard = Standard.new()
    initial_wwr = standard.get_outdoor_subsurface_ratio(model, surface_type = "Wall")
    initial_srr = standard.get_outdoor_subsurface_ratio(model, surface_type = "RoofCeiling")
    runner.registerInitialCondition("The model's initial FDWR = #{initial_wwr} SRR = #{initial_srr}")


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
    if srr_limit_or_max.downcase  == 'Maximize'.downcase
      standard.apply_max_srr(model, runner, srr.to_f,@skylight_fixture_area)
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
