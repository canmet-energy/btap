# The HVAC domain of btap-necb: reference-system selection (8.4.4.7-.19),
# Part 5/8.4.4 efficiency application, energy recovery, and the economizer/
# fan-curve checker. Drives btap-modeling's builders and btap-costing's
# quantities.
module BtapNECB
  module HVAC
    Catalog  = BtapModeling::Catalog
    Builder  = BtapModeling::Builder
    Classify = BtapModeling::Classify
    Coils    = BtapModeling::Coils
    Curves   = BtapModeling::Curves
    Schedules = BtapModeling::Schedules
    Systems  = BtapModeling::Systems
    Costing  = BtapCosting::HVAC
  end
end

require_relative 'hvac/reference'
require_relative 'hvac/energy_recovery'
require_relative 'hvac/efficiency'
require_relative 'hvac/checker'
