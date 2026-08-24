# The lighting domain of btap-necb: Part 4 LPD allowances, the LED
# alternative, daylighting (4.2.1.6 + storage garages 4.2.2.2), exterior
# lighting, and the 8.4.4.5 reference treatment.
module BtapNECB
  module Lighting
    Costing = BtapCosting::Lighting

    DATA_DIR = File.expand_path('lighting/data/necb', __dir__)

    def self.rules(vintage)
      @rules ||= {}
      @rules[vintage.to_s] ||= begin
        path = File.join(DATA_DIR, "lighting_rules_#{vintage}.json")
        raise(ArgumentError, "no NECB lighting rules for vintage '#{vintage}' (expected #{path})") unless File.exist?(path)

        require 'json'
        JSON.parse(File.read(path))
      end
    end

    def self.data_vintage(vintage)
      rules(vintage)['data_vintage_alias'] || vintage.to_s
    end

    def self.table(name)
      @tables ||= {}
      @tables[name] ||= begin
        require 'json'
        JSON.parse(File.read(File.join(DATA_DIR, "#{name}.json")))['table']
      end
    end

    # The merged LED alternative table (lighting_per_area W/ft2 + heat fractions).
    def self.led_record(building_type:, space_type:)
      table('led_lighting_2020').find do |r|
        r['building_type'] == building_type && r['space_type'] == space_type
      end
    end
  end
end

require_relative 'lighting/apply_lights'
require_relative 'lighting/exterior'
require_relative 'lighting/reference'
require_relative 'lighting/daylighted_areas'
require_relative 'lighting/daylight_control_requirement'
require_relative 'lighting/daylighting'
require_relative 'lighting/storage_garage'
# Reopens Daylighting with the quarantined legacy-2011 area math (pinned to
# legacy as fixed by #2119), so it must load after daylighting.rb (which owns
# the module and the live 2020 rule).
require_relative 'lighting/daylighted_areas_legacy_2011'
require_relative 'lighting/reference_daylighting'

module BtapNECB
  module Lighting
    # Cost the model's lighting fixtures. This is the NECB layer, so it
    # supplies the daylighted-area provider btap-costing deliberately does
    # not own (callers can still override it).
    def self.cost(model, **kwargs)
      kwargs[:daylighting_areas] ||= Daylighting.costing_area_provider
      Costing.cost(model, **kwargs)
    end
  end
end
