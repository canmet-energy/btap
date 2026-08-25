# The envelope domain of btap-necb: NECB Section 3.2 prescriptive application,
# the 8.4.4.3/.4 reference-envelope transform, thermal bridging (TBD), the
# 3.2.1.4 fenestration rule appliers, and Table C-1 climate resolution.
# The generic machinery it drives lives in btap-modeling; assembly costing in
# btap-costing.
module BtapNECB
  module Envelope
    # Authoring machinery (btap-modeling) and costing, under the lexical names
    # the domain files use.
    Geometry      = BtapModeling::Geometry
    Constructions = BtapModeling::Constructions
    Costing       = BtapCosting::Envelope

    RULES_DIR = File.expand_path('envelope/data', __dir__)

    # Load the vendored envelope rules for a vintage ('2020', '2025').
    def self.rules(vintage)
      @rules ||= {}
      @rules[vintage.to_s] ||= begin
        path = File.join(RULES_DIR, "envelope_rules_#{vintage}.json")
        raise(ArgumentError, "no NECB envelope rules for vintage '#{vintage}' (expected #{path})") unless File.exist?(path)

        require 'json'
        JSON.parse(File.read(path))
      end
    end
  end
end

require_relative 'envelope/climate'
require_relative 'envelope/rules'
require_relative 'envelope/fenestration'
require_relative 'envelope/prescriptive'
require_relative 'envelope/thermal_bridging'
require_relative 'envelope/reference'

module BtapNECB
  module Envelope
    # apply_prescriptive and reference_envelope are defined by the domain
    # files above, directly on this module. Only the two conveniences the old
    # facade added live here.
    def self.hdd18(model, **kwargs)
      Climate.hdd18(model, **kwargs)
    end

    def self.cost(model, **kwargs)
      Costing.cost(model, **kwargs)
    end
  end
end
