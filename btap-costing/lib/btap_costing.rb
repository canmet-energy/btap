require 'openstudio'

# Costing consumes MODEL OBJECTS, so it sits on the authoring gem — never on
# the NECB rules layer. Where a costing rule needs NECB-owned geometry (the
# daylighted-area sensors), the NECB layer passes a provider in.
begin
  require 'btap_modeling'
rescue LoadError
  require File.expand_path('../../btap-modeling/lib/btap_modeling', __dir__)
end

require_relative 'btap_costing/version'

# The authoring constants costing quantifies against — resolved once here so
# the domain files' bare references (Catalog, Coils, …) keep their lexical
# meaning after the move out of the host gems.
module BtapCosting
  module HVAC
    Catalog  = BtapModeling::Catalog
    Builder  = BtapModeling::Builder
    Classify = BtapModeling::Classify
    Coils    = BtapModeling::Coils
  end

  module Envelope
    Geometry = BtapModeling::Geometry
  end
end
require_relative 'btap_costing/audit_log'
require_relative 'btap_costing/hvac/database'
require_relative 'btap_costing/hvac/ledger'
require_relative 'btap_costing/hvac/geometry'
require_relative 'btap_costing/hvac/quantify_equipment'
require_relative 'btap_costing/hvac/ventilation'
require_relative 'btap_costing/hvac/report'
require_relative 'btap_costing/envelope/database'
require_relative 'btap_costing/envelope/interpolate'
require_relative 'btap_costing/envelope/assemblies'
require_relative 'btap_costing/envelope/quantify'
require_relative 'btap_costing/envelope/envelope_costs'
require_relative 'btap_costing/envelope/thermal_bridging_costs'
require_relative 'btap_costing/envelope/report'
require_relative 'btap_costing/lighting/database'
require_relative 'btap_costing/lighting/fixtures'
require_relative 'btap_costing/lighting/report'
require_relative 'btap_costing/shw'

# BtapCosting prices model objects: HVAC equipment BOMs, envelope assemblies,
# lighting fixtures, and SHW — one gem owning the whole licensed-data seam.
# The vendored CSVs are PLACEHOLDER schema copies; real RS-Means values are
# injected at runtime (costs_csv:/local_factors_csv: or BTAP_COSTING_DIR) and
# are never committed or redistributed. See lib/btap_costing/data/*/README.md.
module BtapCosting
end
