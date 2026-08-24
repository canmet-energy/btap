require 'openstudio'

# The shared audit machinery (AuditLog + article-coverage emitter) the whole
# family writes to. Installed as a gem, or a monorepo sibling during incubation.
begin
  require 'btap_audit'
rescue LoadError
  require File.expand_path('../../btap-audit/lib/btap_audit', __dir__)
end

# The domain gems: installed as gems, or monorepo siblings during incubation.
begin
  require 'openstudio_lighting'
rescue LoadError
  require File.expand_path('../../openstudio-lighting/lib/openstudio_lighting', __dir__)
end
begin
  require 'openstudio_shw'
rescue LoadError
  require File.expand_path('../../openstudio-shw/lib/openstudio_shw', __dir__)
end
begin
  require 'btap_simulation'
rescue LoadError
  require File.expand_path('../../btap-simulation/lib/btap_simulation', __dir__)
end
# btap-modeling: consumed by the AHJ report's floor-plan section (the
# gem is otherwise upstream — it creates models rather than transforming them).
begin
  require 'btap_modeling'
rescue LoadError
  require File.expand_path('../../btap-modeling/lib/btap_modeling', __dir__)
end
begin
  require 'btap_costing'
rescue LoadError
  require File.expand_path('../../btap-costing/lib/btap_costing', __dir__)
end

require_relative 'btap_necb/version'
require_relative 'btap_necb/loads'
require_relative 'btap_necb/envelope'
require_relative 'btap_necb/hvac'
require_relative 'btap_necb/tiers'
require_relative 'btap_necb/decisions'
require_relative 'btap_necb/eui_archetypes'
require_relative 'btap_necb/compliance'
require_relative 'btap_necb/report'

# BtapNECB is the UMBRELLA: it composes the five SDK-only domain gems
# (hvac reference systems + efficiencies, envelope
# prescriptive/reference envelope + thermal bridging, openstudio-loads NECB
# space-use loads, openstudio-lighting LPD allowances + daylighting,
# openstudio-shw service-water-heating minimums) into the NECB Part 8
# performance path — proposed vs reference building energy target (8.4.1.2) —
# with simulation execution via btap-simulation (the one place
# simulation is allowed; the domain gems never simulate), unified costing,
# and ONE AuditLog across everything. The seventh family gem,
# btap-modeling, sits mostly UPSTREAM (it creates the model you feed
# in here) — the AHJ report also consumes its floor-plan engine.
module BtapNECB
  # The shared audit class, now owned by btap-audit: every family gem
  # aliases the SAME class, so one instance flows through all of them.
  AuditLog = BtapAudit::AuditLog unless const_defined?(:AuditLog)

  # Simulation execution now lives in the lowest-level family gem,
  # btap-simulation (SDK+CLI, no compliance layer). Alias it so
  # compliance.rb's Runner.attach_weather! / run_energyplus! / clean_run? /
  # energy_results / unmet_occupied_hours keep working unchanged.
  Runner = BtapSimulation::Runner

  # Run the full performance-path pipeline. See Compliance.performance_compliance.
  def self.performance_compliance(model, **kwargs)
    Compliance.performance_compliance(model, **kwargs)
  end
end
