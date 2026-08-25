# Self-contained on purpose: until lighting and shw fold in, their facades
# require THIS FILE directly across the sibling boundary.
begin
  require 'btap_audit'
rescue LoadError
  require File.expand_path('../../../btap-audit/lib/btap_audit', __dir__)
end

module BtapNECB
  AuditLog = BtapAudit::AuditLog unless const_defined?(:AuditLog)
end

# The loads domain of btap-necb: NECB space-use data application (people,
# plug/gas equipment, ventilation OA, infiltration, NECB-<letter> schedule
# sets, thermostats) — and the family's vintage-data authority (2025 aliases
# the 2020 tables where verified identical).
module BtapNECB
  module Loads
    DATA_DIR = File.expand_path('loads/data', __dir__)

    def self.rules(vintage)
      @rules ||= {}
      @rules[vintage.to_s] ||= begin
        path = File.join(DATA_DIR, "loads_rules_#{vintage}.json")
        raise(ArgumentError, "no NECB loads rules for vintage '#{vintage}' (expected #{path})") unless File.exist?(path)

        require 'json'
        JSON.parse(File.read(path))
      end
    end

    # The vintage whose data tables back this vintage (2025 -> 2020).
    def self.data_vintage(vintage)
      rules(vintage)['data_vintage_alias'] || vintage.to_s
    end

    def self.table(vintage, name)
      @tables ||= {}
      key = [data_vintage(vintage), name]
      @tables[key] ||= begin
        require 'json'
        JSON.parse(File.read(File.join(DATA_DIR, "#{name}_#{key[0]}.json")))['table']
      end
    end
  end
end

require_relative 'loads/space_types'
require_relative 'loads/schedules'
require_relative 'loads/apply'

module BtapNECB
  module Loads
    # Assign NECB space types to a bare-geometry model. See Apply.
    def self.assign_space_types(model, map, vintage: '2020', audit: nil)
      Apply.assign_space_types(model, map, vintage: vintage, audit: audit)
    end
  end
end
