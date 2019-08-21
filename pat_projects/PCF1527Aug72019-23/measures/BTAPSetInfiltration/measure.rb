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
    infiltration_ip = OpenStudio::Measure::OSArgument.makeDoubleArgument('infiltration_ip', true)
    infiltration_ip.setDisplayName('Space Infiltration Flow per Exterior Envelope Surface Area (cfm/ft^2).') # (ft^3/min)/(ft^2) = (ft/min)
    infiltration_ip.setDefaultValue(0.05)
    args << infiltration_ip

    # make an argument for material and installation cost
    material_cost_ip = OpenStudio::Measure::OSArgument.makeDoubleArgument('material_cost_ip', true)
    material_cost_ip.setDisplayName('Increase in Material and Installation Costs for Building per Exterior Envelope Area ($/ft^2).')
    material_cost_ip.setDefaultValue(0.0)
    args << material_cost_ip

    # make an argument for o&m cost
    om_cost_ip = OpenStudio::Measure::OSArgument.makeDoubleArgument('om_cost_ip', true)
    om_cost_ip.setDisplayName('O & M Costs for Construction per Area Used ($/ft^2).')
    om_cost_ip.setDefaultValue(0.0)
    args << om_cost_ip

    # make an argument for o&m frequency
    om_frequency = OpenStudio::Measure::OSArgument.makeIntegerArgument('om_frequency', true)
    om_frequency.setDisplayName('O & M Frequency (whole years).')
    om_frequency.setDefaultValue(1)
    args << om_frequency

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
    infiltration_ip = runner.getDoubleArgumentValue('infiltration_ip', user_arguments)
    material_cost_ip = runner.getDoubleArgumentValue('material_cost_ip', user_arguments)
    years_until_costs_start = 0 # removed user argument and set it to 0. For this measure it should always be 0
    om_cost_ip = runner.getDoubleArgumentValue('om_cost_ip', user_arguments)
    om_frequency = runner.getIntegerArgumentValue('om_frequency', user_arguments)

    # check infiltration for reasonableness
    if infiltration_ip < 0
      runner.registerError("The requested space infiltration flow rate of #{infiltration_ip} cfm/ft^2 was below the measure limit. Choose a positive number.")
      return false
    elsif infiltration_ip == 0.001 # put more thought into best warning trigger value
      runner.registerWarning("The requested space infiltration flow rate of  #{infiltration_ip} cfm/ft^2 seems abnormally low.")
    elsif infiltration_ip > 1.0 # put more thought into best warning trigger value
      runner.registerWarning("The requested space infiltration flow rate of  #{infiltration_ip} cfm/ft^2 seems abnormally high.")
    end

    # short def to make numbers pretty (converts 4125001.25641 to 4,125,001.26 or 4,125,001). The definition be called through this measure
    def neat_numbers(number, roundto = 2) # round to 0 or 2)
      if roundto == 2
        number = format '%.2f', number
      else
        number = number.round
      end
      # regex to add commas
      number.to_s.reverse.gsub(/([0-9]{3}(?=([0-9])))/, '\\1,').reverse
    end

    # helper to make it easier to do unit conversions on the fly
    def unit_helper(number, from_unit_string, to_unit_string)
      converted_number = OpenStudio.convert(OpenStudio::Quantity.new(number, OpenStudio.createUnit(from_unit_string).get), OpenStudio.createUnit(to_unit_string).get).get.value
    end

    # get space infiltration objects used in the model
    space_infiltration_objects = model.getSpaceInfiltrationDesignFlowRates

    # reporting initial condition of model
    if !space_infiltration_objects.empty?
      runner.registerInitialCondition("The initial model contained #{space_infiltration_objects.size} space infiltration objects.")
    else
      runner.registerInitialCondition('The initial model did not contain any space infiltration objects.')
    end




    # si units for infiltration argument
    infiltration_si = unit_helper(infiltration_ip, 'ft/min', 'm/s')

    #loop through all infiltration objects
    space_infiltration_objects.each do |space_infiltration_object|
      space_infiltration_object.setFlowperExteriorSurfaceArea(infiltration_si)
    end


    

    return true
  end
end

# this allows the measure to be used by the application
BTAPSetInfiltration.new.registerWithApplication
