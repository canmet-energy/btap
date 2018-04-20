# BTAPLightingPowerDensityMeasure


Lighting Power Density Measure 
This measure is based upon the Github BTAP task #29 " https://github.com/canmet-energy/btap_tasks/issues/29 " 
Based on Open Studio version 2.4 ( April, 2018).

# Measure Requirements
      This measure adjusts the LPD max value for selected or all space types.
      It will adjust the LPD by scalar or actual value.

# Measure arguments requirements:
      This measure accepts 3 arguments:
      ## The first argument is a choice argument for space type or entire building
         •string array: space_types ( default "Entire Building")
	  ## The second argument is a choice argument for LPD type, either percent, value (W/ft^2), or value (W/m^2)
         •string: lpd_type ( ["value","percent"] default "percent")
      ## The third argument is an argument for LPD value
         •float: lpd_value ( default .80)
		 
# Lighting Power Density Measure (measure.rb)
     ## Accepts the arguments
     1- First the measure makes a choice argument for either a space type or entire building. If no space type is chosen, then this will run on the entire building.
	 2- Then, the measure makes a choice argument for LPD type , either value(W/ft^2), value(W/m^2), or percent. If no LPD type is chosen, then percent is the default.
	 3- Then the last argument is a LPD value. The default value is '0.80'.
	 
	 ## Run the measure
	 1- Assign the user inputs to variables.
	 2- Check the space_type for reasonableness and see if measure should run on space type or on the entire building.
	 3- Check the LPD value for reasonableness.
	 4- Check the lighting power reduction percent for reasonableness.
	 5- Report initial condition.
	 6- Setup OpenStudio units, and start unit conversion of LPD from IP units (W/ft^2) to SI units (W/m^2) and vise-versa as needed.
	 7- Create a new LightsDefinition and new Lights object to use with setLightingPowerPerFloorArea.
	 8- Get space types in model, loop through these space types to check if they have lights and are used in the model. Pick a new schedule to use and check if it is defaulted. 
	    Flag if lights_schedules has more than one unique object. 
	 9- Delete lights and luminaires and add in new lights, and assign preferred schedule to new lights object.
	 10- If space has lights and space type also has lights, loop through them and repeat step 9.
	 11- If space has lights and space type has no lights, then repeat step 8 and 9, but instead of looping through the space types, loop through the spaces.
	 12- Clean up template light instance. Finally, report final condition for the value of LPD per floor area in SI and IP units.
	 
	 
# Tests
The "lighting_power_density_measure_test.rb" performs 11 mini-test asserts : 
     
	 1- Check if the model succeeds to accepts three arguments, and check their default values. 
	 
     2- Check if the model succeeds to fail with too high values of 'lpd_percent' ( percent higher than 100%).
     3- Check if the model succeeds to print warning messages for high values of 'lpd_percent' ( percent higher than 90%).
     4- Check if the model succeeds to print warning messages for small values of 'lpd_percent' ( percent lower than 1% and higher than -1%).

     5- Check if the model succeeds to fail with too high values of 'lpd_values' ( values higher than 50 W/ft^2).
     6- Check if the model succeeds to print warning messages for high values of 'lpd_values' ( values higher than 21 W/ft^2).
     7- Check if the model succeeds to fail with negative values of 'lpd_values' ( values lower than 0).

     8- Check if the model succeeds to fail with too high values of 'lpd_values' ( values higher than 538 W/m^2).
     9- Check if the model succeeds to print warning messages for high values of 'lpd_values' ( values higher than 226 W/m^2).
     10-Check if the model succeeds to fail with negative values of 'lpd_values' ( values lower than 0).

     11- Check if the model succeeds with reasonable value of LPD.


 
