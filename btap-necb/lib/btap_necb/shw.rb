# The SHW domain of btap-necb: per-space demand + the auto-sized plant, Part 6
# performance (Table 6.2.2.1, the NECB2020 UEF procedure), prescriptive checks
# (booster heaters, field-verified declarations), and the 8.4.4.20 reference.
module BtapNECB
  module SHW
    Costing = BtapCosting::SHW

    DATA_DIR = File.expand_path('shw/data', __dir__)

    def self.rules(vintage)
      @rules ||= {}
      @rules[vintage.to_s] ||= begin
        path = File.join(DATA_DIR, "shw_rules_#{vintage}.json")
        raise(ArgumentError, "no NECB shw rules for vintage '#{vintage}' (expected #{path})") unless File.exist?(path)

        require 'json'
        JSON.parse(File.read(path))
      end
    end
  end
end

require_relative 'shw/demand'
require_relative 'shw/efficiency'
require_relative 'shw/prescriptive'
require_relative 'shw/reference'

module BtapNECB
  module SHW
    # Demand + plant: see Demand.apply_shw.
    def self.apply_shw(model, **kwargs)
      Demand.apply_shw(model, **kwargs)
    end

    def self.cost(model, **kwargs)
      Costing.cost(model, **kwargs)
    end
  end
end
