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

# see the URL below for information on how to write OpenStudio measures
# http://openstudio.nrel.gov/openstudio-measure-writing-guide

# see the URL below for information on using life cycle cost objects in OpenStudio
# http://openstudio.nrel.gov/openstudio-life-cycle-examples

# see the URL below for access to C++ documentation on model objects (click on "model" in the main window to view model objects)
# http://openstudio.nrel.gov/sites/openstudio.nrel.gov/files/nv_data/cpp_documentation_it/model/html/namespaces.html

# load OpenStudio measure libraries
require_relative 'resources/BTAPMeasureHelper'
include BTAPMeasureHelper



# start the measure
class BTAPAddDOASSys < OpenStudio::Measure::ModelMeasure
  # define the name that a user will see, this method may be deprecated as
  # the display name in PAT comes from the name field in measure.xml
  def name
    return 'BTAPAddDOASSys'
  end

  # define the arguments that the user will input
  def arguments(model)
    args = OpenStudio::Measure::OSArgumentVector.new

    zonesselected = OpenStudio::Measure::OSArgument::makeStringArgument('zonesselected', false)
    zonesselected.setDisplayName('Choose which zones to add DOAS to')
    zonesselected.setDefaultValue("All Zones")

    args << zonesselected

    return args
  end

  # define what happens when the measure is run
  def run(model, runner, user_arguments)
    super(model, runner, user_arguments)

    # use the built-in error checking
    if !runner.validateUserArguments(arguments(model), user_arguments)
      return false
    end
    zonesselected = runner.getStringArgumentValue('zonesselected',user_arguments)


    if zonesselected == '999'
      runner.registerInfo("BTAPAddDOASSys is skipped")
    else
      runner.registerInfo("BTAPAddDOASSys is not skipped")
      if model.building.get.name.to_s.include?("MediumOffice") or model.building.get.name.to_s.include?("LargeOffice") or model.building.get.name.to_s.include?("HighriseApartment")
        #do nothing
        puts "Don't use BTAPAddDOASSys for office or highrise"

      else
        puts "use BTAPAddDOASSys "
        if zonesselected == "All Zones"
          #prep work
          #get zoneequipmentlist ready
          list_of_zone_hvac_eqp_list = model.getZoneHVACEquipmentLists
          erv_temp = OpenStudio::Model::ZoneHVACEnergyRecoveryVentilator.new(model)
          erv_class = erv_temp.class
          erv_temp.remove

          #Get the zones that are connected to an air loop with an outdoor air system
          airloops = model.getAirLoopHVACs
          zones_done = []
          airloops.each do |airloop|
            airloop.supplyComponents.each do |supplyComponent|
              if supplyComponent.to_AirLoopHVACOutdoorAirSystem.is_initialized
                airloop_oas_sys = supplyComponent.to_AirLoopHVACOutdoorAirSystem.get
                #this air loop serves zones with an OAS. Set up DOAS for the zones served by this air loop

                #record zones, check if it has a doas (erv), if it does, don't add a doas
                airloop.thermalZones.each do |zone|
                  store_zone= true
                  if not zones_done.include?(zone)
                    list_of_zone_hvac_eqp_list.each do|zone_eqp_list|
                      if zone_eqp_list.thermalZone == zone
                        zone_eqp_list.equipment.each do |zone_eqp|
                          if zone_eqp.class == erv_class.class
                            store_zone = false
                          end
                        end
                      end
                    end
                    if store_zone
                      #for the zones connected to this air loop, set up doas
                    
                      set_up_doas(model, zone, airloop_oas_sys)
                    end
                  end
                end

              end #supplyComponent.to_AirLoopHVACOutdoorAirSystem.is_initialized

            end #airloop.supplyComponents.each do |supplyComponent|



          end #airloops.each do |airloop|
          
        end #if zonesselected == "All Zones"
      end #if model.building.get.name.to_s.include?("MediumOffice") or model.building.get.name.to_s.include?("LargeOffice") or model.building.get.name.to_s.include?("HighriseApartment")
    end


    return true
  end
end



# this allows the measure to be used by the application
BTAPAddDOASSys.new.registerWithApplication
