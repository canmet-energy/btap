#see the URL below for information on how to write OpenStudio measures
# http://openstudio.nrel.gov/openstudio-measure-writing-guide

#see the URL below for access to C++ documentation on model objects (click on "model" in the main window to view model objects)
# http://openstudio.nrel.gov/sites/openstudio.nrel.gov/files/nv_data/cpp_documentation_it/model/html/namespaces.html

#start the measure
class BTAPChangeEnergyRecoveryEfficiency < OpenStudio::Measure::ModelMeasure
  
  #define the name that a user will see, this method may be deprecated as
  #the display name in PAT comes from the name field in measure.xml
  def name
    return "BTAPChangeEnergyRecoveryEfficiency"
  end
  
  #define the arguments that the user will input
  #define the arguments that the user will input
   #define the arguments that the user will input
  def arguments(model)
    args = OpenStudio::Ruleset::OSArgumentVector.new
     
		# Sensible Effectiveness at 100% Heating Air Flow (default of 0.76)
		sensible_eff_at_100_heating = OpenStudio::Ruleset::OSArgument::makeDoubleArgument("sensible_eff_at_100_heating", false)
		sensible_eff_at_100_heating.setDisplayName("Sensible Effectiveness at 100% Heating Air Flow")
		sensible_eff_at_100_heating.setDefaultValue(0.76)
		args << sensible_eff_at_100_heating	
		
		# Latent Effectiveness at 100% Heating Air Flow (default of 0.76)
		latent_eff_at_100_heating = OpenStudio::Ruleset::OSArgument::makeDoubleArgument("latent_eff_at_100_heating", false)
		latent_eff_at_100_heating.setDisplayName("Latent Effectiveness at 100% Heating Air Flow")
		latent_eff_at_100_heating.setDefaultValue(0.68)
		args << latent_eff_at_100_heating		
	
		# Sensible Effectiveness at 75% Heating Air Flow (default of 0.76)
		sensible_eff_at_75_heating = OpenStudio::Ruleset::OSArgument::makeDoubleArgument("sensible_eff_at_75_heating", false)
		sensible_eff_at_75_heating.setDisplayName("Sensible Effectiveness at 75% Heating Air Flow")
		sensible_eff_at_75_heating.setDefaultValue(0.81)
		args << sensible_eff_at_75_heating	
		
		# Latent Effectiveness at 100% Heating Air Flow (default of 0.76)
		latent_eff_at_75_heating = OpenStudio::Ruleset::OSArgument::makeDoubleArgument("latent_eff_at_75_heating", false)
		latent_eff_at_75_heating.setDisplayName("Latent Effectiveness at 75% Heating Air Flow")
		latent_eff_at_75_heating.setDefaultValue(0.73)
		args << latent_eff_at_75_heating		

		# Sensible Effectiveness at 100% Cooling Air Flow (default of 0.76)
		sensible_eff_at_100_cooling = OpenStudio::Ruleset::OSArgument::makeDoubleArgument("sensible_eff_at_100_cooling", false)
		sensible_eff_at_100_cooling.setDisplayName("Sensible Effectiveness at 100% Cooling Air Flow")
		sensible_eff_at_100_cooling.setDefaultValue(0.76)
		args << sensible_eff_at_100_cooling	
		
		# Latent Effectiveness at 100% Cooling Air Flow (default of 0.76)
		latent_eff_at_100_cooling = OpenStudio::Ruleset::OSArgument::makeDoubleArgument("latent_eff_at_100_cooling", false)
		latent_eff_at_100_cooling.setDisplayName("Latent Effectiveness at 100% Cooling Air Flow")
		latent_eff_at_100_cooling.setDefaultValue(0.68)
		args << latent_eff_at_100_cooling		
	
		# Sensible Effectiveness at 75% Cooling Air Flow (default of 0.76)
		sensible_eff_at_75_cooling = OpenStudio::Ruleset::OSArgument::makeDoubleArgument("sensible_eff_at_75_cooling", false)
		sensible_eff_at_75_cooling.setDisplayName("Sensible Effectiveness at 75% Cooling Air Flow")
		sensible_eff_at_75_cooling.setDefaultValue(0.81)
		args << sensible_eff_at_75_cooling	
		
		# Latent Effectiveness at 100% Cooling Air Flow (default of 0.76)
		latent_eff_at_75_cooling = OpenStudio::Ruleset::OSArgument::makeDoubleArgument("latent_eff_at_75_cooling", false)
		latent_eff_at_75_cooling.setDisplayName("Latent Effectiveness at 75% Cooling Air Flow")
		latent_eff_at_75_cooling.setDefaultValue(0.73)
		args << latent_eff_at_75_cooling	
	
    return args
  end #end the arguments method


  
  #define what happens when the measure is run
  def run(model, runner, user_arguments)
    super(model, runner, user_arguments)
    
    #use the built-in error checking 
    if not runner.validateUserArguments(arguments(model), user_arguments)
      return false
    end


		#get input
		sensible_eff_at_100_heating = runner.getDoubleArgumentValue("sensible_eff_at_100_heating",user_arguments)		
		latent_eff_at_100_heating = runner.getDoubleArgumentValue("latent_eff_at_100_heating",user_arguments)	
		sensible_eff_at_75_heating = runner.getDoubleArgumentValue("sensible_eff_at_75_heating",user_arguments)	
		latent_eff_at_75_heating = runner.getDoubleArgumentValue("latent_eff_at_75_heating",user_arguments)
			
		sensible_eff_at_100_cooling = runner.getDoubleArgumentValue("sensible_eff_at_100_cooling",user_arguments)	
		latent_eff_at_100_cooling = runner.getDoubleArgumentValue("latent_eff_at_100_cooling",user_arguments)	
		sensible_eff_at_75_cooling = runner.getDoubleArgumentValue("sensible_eff_at_75_cooling",user_arguments)	
		latent_eff_at_75_cooling = runner.getDoubleArgumentValue("latent_eff_at_75_cooling",user_arguments)	
		


		model.getAirLoopHVACOutdoorAirSystems.each do |oa_system|
			oa_system.oaComponents.each do |oa_component|
				if oa_component.to_HeatExchangerAirToAirSensibleAndLatent.is_initialized
					runner.registerInfo("*** Identified the ERV")
					erv = oa_component.to_HeatExchangerAirToAirSensibleAndLatent.get
					
					if sensible_eff_at_100_cooling == 999
						runner.registerInfo("sensible_eff_at_100_cooling is not skipped")
					else
						runner.registerInfo("sensible_eff_at_100_cooling is not skipped")
						erv.setSensibleEffectivenessat100CoolingAirFlow(sensible_eff_at_100_cooling)
					end

					if sensible_eff_at_75_cooling == 999
						runner.registerInfo("sensible_eff_at_75_cooling is not skipped")
					else
						runner.registerInfo("sensible_eff_at_75_cooling is not skipped")
						erv.setSensibleEffectivenessat75CoolingAirFlow(sensible_eff_at_75_cooling)
					end
					
					if latent_eff_at_100_cooling == 999
						runner.registerInfo("latent_eff_at_100_cooling is not skipped")
					else
						runner.registerInfo("latent_eff_at_100_cooling is not skipped")
						erv.setLatentEffectivenessat100CoolingAirFlow(latent_eff_at_100_cooling)
					end
					
					if latent_eff_at_75_cooling == 999
						runner.registerInfo("latent_eff_at_75_cooling is not skipped")
					else
						runner.registerInfo("latent_eff_at_75_cooling is not skipped")
						erv.setLatentEffectivenessat75CoolingAirFlow(latent_eff_at_75_cooling)
					end
					
					if sensible_eff_at_100_heating == 999
						runner.registerInfo("sensible_eff_at_100_heating is not skipped")
					else
						runner.registerInfo("sensible_eff_at_100_heating is not skipped")
						erv.setSensibleEffectivenessat100HeatingAirFlow(sensible_eff_at_100_heating)
					end
					
					if sensible_eff_at_75_heating == 999
						runner.registerInfo("sensible_eff_at_75_heating is not skipped")
					else
						runner.registerInfo("sensible_eff_at_75_heating is not skipped")
						erv.setSensibleEffectivenessat75HeatingAirFlow(sensible_eff_at_75_heating)	
					end
					
					if latent_eff_at_100_heating == 999
						runner.registerInfo("latent_eff_at_100_heating is not skipped")
					else
						runner.registerInfo("latent_eff_at_100_heating is not skipped")
						erv.setLatentEffectivenessat100HeatingAirFlow(latent_eff_at_100_heating)
					end
					
					if latent_eff_at_75_heating == 999
						runner.registerInfo("latent_eff_at_75_heating is not skipped")
					else
						runner.registerInfo("latent_eff_at_75_heating is not skipped")
						erv.setLatentEffectivenessat75HeatingAirFlow(latent_eff_at_75_heating)
					end				

				end 
			end
		end		

		return true
 
  end #end the run method

end #end the measure

#this allows the measure to be use by the application
BTAPChangeEnergyRecoveryEfficiency.new.registerWithApplication