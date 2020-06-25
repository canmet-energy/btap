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

# start the measure
class BTAPSetInfiltration < OpenStudio::Measure::ModelMeasure
  # define the name that a user will see
  def name
    return 'BTAPSetInfiltration'
  end

  # define the arguments that the user will input
  def arguments(model)
    args = OpenStudio::Measure::OSArgumentVector.new

    # make an argument for infiltration
    infiltration_si = OpenStudio::Measure::OSArgument.makeDoubleArgument('infiltration_si', true)
    infiltration_si.setDisplayName('Space Infiltration Flow per Exterior Envelope Surface Area m3/s/m2 at 75 Pa') # m/s
    infiltration_si.setDefaultValue(0.0027)
    args << infiltration_si

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
    infiltration_si = runner.getDoubleArgumentValue('infiltration_si', user_arguments)

    if infiltration_si === 999
      #do nothing
      runner.registerInfo("BTAPSetInfiltration is skipped")
    else
      runner.registerInfo("BTAPSetInfiltration is not skipped")
      # get space infiltration objects used in the model
      space_infiltration_objects = model.getSpaceInfiltrationDesignFlowRates

      #convert infiltration_si from 75 PA to 5 Pa
      infiltration_si = infiltration_si*0.1720048

      #loop through all infiltration objects
      space_infiltration_objects.each do |space_infiltration_object|
        space_infiltration_object.setFlowperExteriorSurfaceArea(infiltration_si)
      end

    end

    

    return true
  end
end

# this allows the measure to be used by the application
BTAPSetInfiltration.new.registerWithApplication
