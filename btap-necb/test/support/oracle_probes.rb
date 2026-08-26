# frozen_string_literal: true

# The ORACLE PROBES: every oracle-side computation the eleven parity gates
# make, extracted so the gates and the exported Leg-C goldens
# (scripts/export_oracle_goldens.rb) are one implementation and cannot drift.
#
# Three-way verification (D-78): Leg A = these probes compared live against
# the gem (the parity gates); Leg C = these probes' output frozen to
# test/goldens/oracle/*.json under the pin, consumed by the future Python
# port directly — so a bug faithfully ported from Ruby still fails.
#
# Contract: every probe returns PLAIN JSON-ROUNDTRIPPABLE data — string keys,
# floats/strings/booleans/nil/arrays only — because the same value must
# compare equal whether it came from the live oracle or from a golden file.
# Signature builders used on BOTH sides (gem and oracle models) live in
# Signatures for the same reason.
#
# Nothing here requires openstudio-standards at load time: acquisition is
# lazy inside Access, preserving the gates' skip-without-pin behavior.
module OracleProbes
  # ---------------------------------------------------------------- access
  module Access
    module_function

    # The pinned oracle, or :unavailable (memoized; same contract the gates
    # carried individually).
    def standard
      @standard ||= begin
        require 'openstudio-standards' # the PINNED oracle (legacy_pin/Gemfile)
        Standard.build('NECB2020')
      rescue LoadError, StandardError => e
        warn "legacy parity skipped: #{e.class}: #{e.message[0, 80]}"
        :unavailable
      end
    end

    # The BTAP envelope coster (btap sub-files are required BY PATH from the
    # oracle's own gem root — PR #2120 renamed them; see the gate history).
    def coster
      @coster ||= begin
        require 'openstudio-standards'
        legacy_dir = File.join(Gem.loaded_specs['openstudio-standards'].full_gem_path,
                               'lib/openstudio-standards/btap')
        require File.join(legacy_dir, 'paths')
        require File.join(legacy_dir, 'costing/database')
        require File.join(legacy_dir, 'costing/btap_costing')
        require File.join(legacy_dir, 'costing/envelope_costing')
        require File.join(legacy_dir, 'linear_regression')
        c = BTAP::Costing.allocate
        c.instance_variable_set(:@costing_database, BTAP::Database.instance)
        c
      rescue LoadError, StandardError => e
        warn "legacy costing parity skipped: #{e.class}: #{e.message[0, 100]}"
        :unavailable
      end
    end

    # The lighting coster: additional btap requires, the sorted-accessor
    # monkeypatches legacy attributes.rb normally provides, and the stubs that
    # scope cost_audit_lighting to FIXTURES ONLY (sensors and LED audited
    # separately).
    def lighting_coster
      @lighting_coster ||= begin
        require 'openstudio-standards'
        legacy_dir = File.join(Gem.loaded_specs['openstudio-standards'].full_gem_path,
                               'lib/openstudio-standards/btap')
        require File.join(legacy_dir, 'paths')
        require File.join(legacy_dir, 'costing/database')
        require File.join(legacy_dir, 'costing/btap_costing')
        require File.join(legacy_dir, 'costing/lighting_costing')
        require File.join(legacy_dir, 'costing/led_lighting_costing')
        require File.join(legacy_dir, 'costing/daylighting_sensor_control_costing')
        OpenStudio::Model::Model.class_eval do
          define_method(:getThermalZonesSorted) { getThermalZones.sort_by { |z| z.name.get } }
        end
        OpenStudio::Model::ThermalZone.class_eval do
          define_method(:getSpacesSorted) { spaces.sort_by { |s| s.name.get } }
        end
        c = BTAP::Costing.allocate
        c.instance_variable_set(:@costing_database, BTAP::Database.instance)
        c
      rescue LoadError, StandardError => e
        warn "legacy lighting costing skipped: #{e.class}: #{e.message[0, 100]}"
        :unavailable
      end
    end

    # The pinned gem tree on disk (for data-file probes), or nil.
    def pin_root
      Gem.loaded_specs['openstudio-standards']&.full_gem_path
    rescue StandardError
      nil
    end

    # Gate helper: returns the resource or skips/flunks the calling test.
    def gate!(test, resource)
      if resource == :unavailable || resource.nil?
        msg = 'legacy oracle not bundled — run under BUNDLE_GEMFILE=legacy_pin/Gemfile'
        return ENV['LEGACY_PIN_REQUIRED'] == '1' ? test.flunk(msg) : test.skip(msg)
      end
      resource
    end
  end

  # ------------------------------------------------------------ signatures
  # Model-readers used identically on gem-built and oracle-built objects, so
  # both sides quantize/normalize the same way. String keys throughout.
  module Signatures
    module_function

    def optional_f(value, digits = 9)
      value.is_initialized ? value.get.round(digits) : nil
    end

    def optional_name(optional)
      optional.is_initialized ? optional.get.nameString : nil
    end

    def day_values(day_schedule)
      (1..24).map { |hour| day_schedule.getValue(OpenStudio::Time.new(0, hour, 0, 0)).round(6) }
    end

    def rule_signature(rule)
      { 'days' => %w[Monday Tuesday Wednesday Thursday Friday Saturday Sunday].map { |d| rule.send("apply#{d}") },
        'values' => day_values(rule.daySchedule),
        'start' => rule.startDate.is_initialized ? rule.startDate.get.to_s : nil,
        'end' => rule.endDate.is_initialized ? rule.endDate.get.to_s : nil }
    end

    def ruleset_signature(schedule)
      ruleset = schedule.to_ScheduleRuleset
      return { 'fallback' => schedule.nameString } if ruleset.empty?

      ruleset = ruleset.get
      { 'default' => day_values(ruleset.defaultDaySchedule),
        'winter' => ruleset.isWinterDesignDayScheduleDefaulted ? nil : day_values(ruleset.winterDesignDaySchedule),
        'summer' => ruleset.isSummerDesignDayScheduleDefaulted ? nil : day_values(ruleset.summerDesignDaySchedule),
        'rules' => ruleset.scheduleRules.map { |r| rule_signature(r) }
                          .sort_by { |s| s['days'].map { |b| b ? 1 : 0 }.join } }
    end

    # The 17-field per-space-type loads signature (loads-apply gate).
    def loads_signature(space_type)
      people = space_type.people.first
      equip = space_type.electricEquipment.first
      gas = space_type.gasEquipment.first
      dsoa = space_type.designSpecificationOutdoorAir
      infiltration = space_type.spaceInfiltrationDesignFlowRates.first
      schedule_set = space_type.defaultScheduleSet
      {
        'people_per_m2' => people ? optional_f(people.peopleDefinition.peopleperSpaceFloorArea) : nil,
        'people_frac_radiant' => people ? people.peopleDefinition.fractionRadiant.round(9) : nil,
        'epd_w_m2' => equip ? optional_f(equip.electricEquipmentDefinition.wattsperSpaceFloorArea) : nil,
        'epd_frac_latent' => equip ? equip.electricEquipmentDefinition.fractionLatent.round(9) : nil,
        'epd_frac_radiant' => equip ? equip.electricEquipmentDefinition.fractionRadiant.round(9) : nil,
        'epd_frac_lost' => equip ? equip.electricEquipmentDefinition.fractionLost.round(9) : nil,
        'gas_w_m2' => gas ? optional_f(gas.gasEquipmentDefinition.wattsperSpaceFloorArea) : nil,
        'oa_method' => dsoa.is_initialized ? dsoa.get.outdoorAirMethod : nil,
        'oa_per_area' => dsoa.is_initialized ? dsoa.get.outdoorAirFlowperFloorArea.round(9) : nil,
        'oa_per_person' => dsoa.is_initialized ? dsoa.get.outdoorAirFlowperPerson.round(9) : nil,
        'oa_ach' => dsoa.is_initialized ? dsoa.get.outdoorAirFlowAirChangesperHour.round(9) : nil,
        'infil_per_ext' => infiltration ? optional_f(infiltration.flowperExteriorSurfaceArea) : nil,
        'infil_per_wall' => infiltration ? optional_f(infiltration.flowperExteriorWallArea) : nil,
        'infil_ach' => infiltration ? optional_f(infiltration.airChangesperHour) : nil,
        'occ_sch' => schedule_set.is_initialized ? optional_name(schedule_set.get.numberofPeopleSchedule) : nil,
        'act_sch' => schedule_set.is_initialized ? optional_name(schedule_set.get.peopleActivityLevelSchedule) : nil,
        'equip_sch' => schedule_set.is_initialized ? optional_name(schedule_set.get.electricEquipmentSchedule) : nil
      }
    end

    def thermostat_signature(model, name)
      t = model.getThermostatSetpointDualSetpoints.find { |x| x.nameString == name }
      return nil if t.nil?

      { 'heating' => optional_name(t.heatingSetpointTemperatureSchedule),
        'cooling' => optional_name(t.coolingSetpointTemperatureSchedule) }
    end

    def lights_signature(space_type)
      lights = space_type.lights.sort_by(&:nameString).reject { |l| l.nameString.include?('Additional') }.first
      return nil if lights.nil?

      d = lights.lightsDefinition
      schedule = space_type.defaultScheduleSet.is_initialized ? space_type.defaultScheduleSet.get.lightingSchedule : nil
      sched_sig = nil
      if schedule&.is_initialized
        rs = schedule.get.to_ScheduleRuleset
        sched_sig = if rs.empty?
                      schedule.get.nameString
                    else
                      { 'name' => schedule.get.nameString,
                        'default' => day_values(rs.get.defaultDaySchedule),
                        'rules' => rs.get.scheduleRules.map { |r| day_values(r.daySchedule) } }
                    end
      end
      { 'w_m2' => d.wattsperSpaceFloorArea.is_initialized ? d.wattsperSpaceFloorArea.get.round(9) : nil,
        'w_person' => d.wattsperPerson.is_initialized ? d.wattsperPerson.get.round(9) : nil,
        'return_air' => d.returnAirFraction.round(9), 'radiant' => d.fractionRadiant.round(9),
        'visible' => d.fractionVisible.round(9), 'schedule' => sched_sig }
    end

    # Per-surface construction-only conductance map (prescriptive gate).
    # D-32: ground FLOORS excluded — legacy retargets them to the Table
    # 3.2.3.1 strip value over the FULL area; the gem implements the printed
    # zone-conditional rule, an intentional, MCP-verified divergence.
    def surface_conductances(model)
      model.getSurfaces.sort_by(&:nameString).filter_map do |s|
        next unless %w[Outdoors Ground Foundation].include?(s.outsideBoundaryCondition)
        next if s.isGroundSurface && s.surfaceType == 'Floor'
        next if s.construction.empty? || s.construction.get.to_Construction.empty?

        [s.nameString, s.construction.get.to_Construction.get.thermalConductance.to_f.round(4)]
      end.to_h
    end

    def water_heater_signature(heater)
      { 'tank_volume_m3' => optional_f(heater.tankVolume, 12),
        'capacity_w' => optional_f(heater.heaterMaximumCapacity, 6),
        'parasitic_w' => heater.onCycleParasiticFuelConsumptionRate.round(9),
        'fuel' => heater.heaterFuelType }
    end

    def water_use_signatures(model)
      model.getWaterUseEquipments.sort_by { |w| w.space.get.nameString }.map do |w|
        { 'space' => w.space.get.nameString,
          'peak_flow_m3s' => w.waterUseEquipmentDefinition.peakFlowRate.round(15),
          'schedule' => w.flowRateFractionSchedule.is_initialized ? w.flowRateFractionSchedule.get.nameString : nil }
      end
    end

    def water_heater_efficiency_signature(heater)
      { 'efficiency' => optional_f(heater.heaterThermalEfficiency),
        'ua_w_k' => optional_f(heater.offCycleLossCoefficienttoAmbientTemperature),
        'plf_curve' => heater.partLoadFactorCurve.is_initialized,
        'parasitic_frac_to_tank' => heater.offCycleParasiticHeatFractiontoTank.round(9) }
    end

    def daylighting_controls_signature(model)
      model.getDaylightingControls.sort_by(&:nameString).map do |c|
        { 'name' => c.nameString,
          'x' => c.positionXCoordinate.round(9), 'y' => c.positionYCoordinate.round(9),
          'z' => c.positionZCoordinate.round(9), 'control_type' => c.lightingControlType }
      end
    end
  end

  # -------------------------------------------------------------- envelope
  module Envelope
    HDD_SWEEP = [0, 1500, 2999, 3000, 3999, 4000, 4001, 5500, 6999, 7000, 8000, 9998, 9999, 12_000].freeze
    SURFACES = { 'outdoors' => %w[wall roofceiling floor window skylight door],
                 'ground' => %w[wall roofceiling floor] }.freeze

    module_function

    # {'max_u' => {'boundary/surface/hdd' => u}, 'max_fdwr' => {'hdd' => v}, 'srr_max' => v}
    def lookups(std)
      max_u = {}
      SURFACES.each do |boundary, surfaces|
        surfaces.each do |surface|
          HDD_SWEEP.each { |hdd| max_u["#{boundary}/#{surface}/#{hdd}"] = std.max_u_necb(surface, boundary, hdd) }
        end
      end
      { 'max_u' => max_u,
        'max_fdwr' => HDD_SWEEP.to_h { |hdd| [hdd.to_s, std.max_fwdr(hdd)] },
        'srr_max' => std.get_standards_constant('skylight_to_roof_ratio_max_value') }
    end

    # Nearest-Table-C-1-city HDD for a model with the given EPW attached.
    def hdd18(std, model)
      std.get_necb_hdd18(model: model, necb_hdd: true)
    end

    # Mutates the given raw-fixture model along the legacy prescriptive path
    # and returns {'conductances' => {...}, 'fdwr_model' => <the second
    # mutated model's census fdwr>}. The two halves take their own models
    # because the FDWR path applies a different legacy method.
    def prescriptive(std, conductance_model, fdwr_model, subsurface_patch:)
      std.model_add_constructions(conductance_model)
      subsurface_patch.call(conductance_model)
      std.apply_standard_construction_properties(model: conductance_model)

      std.model_add_constructions(fdwr_model)
      std.apply_standard_window_to_wall_ratio(model: fdwr_model) # -1 default = NECB max
      { 'conductances' => Signatures.surface_conductances(conductance_model),
        'fdwr' => BtapModeling::Geometry.exposed_walls(fdwr_model)[:fdwr] }
    end

    # The legacy 2020 U-table JSON node, read from the pinned gem tree.
    def u_table(pin_root)
      rel = 'lib/openstudio-standards/standards/necb/NECB2020/data/surface_thermal_transmittance.json'
      path = File.join(pin_root, rel)
      return nil unless File.exist?(path)

      require 'json'
      JSON.parse(File.read(path))['tables']['surface_thermal_transmittance']['table']
    end
  end

  # --------------------------------------------------------------- costing
  module Costing
    INTERPOLATE_POINT_SETS = [
      [[1.0, 10.0], [2.0, 20.0], [4.0, 30.0]],
      [[0.5, 100.0], [0.9, 90.0], [1.7, 260.0], [3.2, 410.0]],
      [[2.0, 55.5]]
    ].freeze
    INTERPOLATE_XS = [0.4, 0.5, 0.55, 0.99, 1.0, 1.5, 2.0, 3.05, 3.99, 4.0, 4.05, 4.2, 9.0].freeze
    TB_TALLIES = { 'parapet' => { 'BTAP-ExteriorWall-SteelFramed-1 good' => 100.0 },
                   'jamb' => { 'BTAP-ExteriorWall-SteelFramed-1 good' => 50.0 },
                   'sill' => { 'BTAP-ExteriorWall-SteelFramed-1 good' => 25.0 },
                   'rimjoist' => { 'BTAP-ExteriorWall-SteelFramed-1 good' => 30.0 },
                   'transition' => { 'BTAP-ExteriorWall-SteelFramed-1 good' => 500.0 } }.freeze

    module_function

    # {'set_index/x' => y} across the fixed point sets and xs.
    def interpolations
      out = {}
      INTERPOLATE_POINT_SETS.each_with_index do |points, set_index|
        INTERPOLATE_XS.each do |x|
          y, = BTAP::LinearRegression.interpolate(x_y_array: points.map(&:dup), x2: x)
          out["#{set_index}/#{x}"] = y.to_f
        end
      end
      BTAP::LinearRegression.extrapolation_boundaries_exceeded? # reset legacy sticky flag
      out
    end

    # {'sheet/assembly/rsi3' => dollars} for every candidate in the vendored
    # catalogs, priced at (province, city) with whatever priced table is in
    # effect (the caller records that context).
    def construction_costs(coster, database, province, city)
      out = {}
      database.constructions.each do |sheet, assemblies|
        assemblies.each_key do |assembly|
          database.construction_candidates(sheet, assembly).each do |rsi, construction|
            legacy_hash = { 'type' => construction['type'], 'id_layers' => construction['id_layers'].dup }
            coster.cost_construction(legacy_hash, province, city)
            out["#{sheet}/#{assembly}/#{rsi.round(3)}"] = legacy_hash['cost'].to_f
          end
        end
      end
      out
    end

    # {'surfaces' => {name => rsi}, 'sub_surfaces' => {name => rsi}} via
    # TBD.rsi on an already-prescriptive-applied model.
    def tbd_rsi(model)
      require 'tbd'
      surfaces = {}
      model.getSurfaces.sort_by(&:nameString).each do |surface|
        next if surface.construction.empty? || surface.construction.get.to_LayeredConstruction.empty?
        next unless surface.outsideBoundaryCondition == 'Outdoors' ||
                    BtapCosting::Envelope::Quantify::GROUND_BOUNDARIES.include?(surface.outsideBoundaryCondition)

        lc = surface.construction.get.to_LayeredConstruction.get
        surfaces[surface.nameString] = TBD.rsi(lc, surface.filmResistance)
      end
      sub_surfaces = {}
      model.getSubSurfaces.sort_by(&:nameString).each do |sub|
        next if sub.construction.empty? || sub.construction.get.to_LayeredConstruction.empty?

        lc = sub.construction.get.to_LayeredConstruction.get
        sub_surfaces[sub.nameString] = TBD.rsi(lc, 0)
      end
      { 'surfaces' => surfaces, 'sub_surfaces' => sub_surfaces }
    end

    # {material_id => quantity} for the fixed bridging tallies.
    def tb_material_quantities
      BTAP::BridgingData.get_material_quantities_for_edges(TB_TALLIES).transform_keys(&:to_s)
    rescue NameError
      # BridgingData needs the tbd-dependent bridging.rb; load it explicitly.
      require File.join(Gem.loaded_specs['openstudio-standards'].full_gem_path,
                        'lib/openstudio-standards/btap/bridging')
      retry
    end

    # The one legacy lighting dollar total (fixtures only; sensors + LED
    # stubbed to zero, audited separately).
    def lighting_total(coster, std, model, province, city)
      coster.instance_variable_set(:@costing_report,
                                   { 'province_state' => province, 'city' => city, 'lighting' => {} })
      coster.instance_variable_set(:@cost_items, [])
      def coster.add_costed_item(**_kwargs); end
      def coster.cost_audit_daylighting_sensor_control(model:, prototype_creator:); 0.0; end
      def coster.cost_audit_led_lighting(model:, prototype_creator:); 0.0; end
      coster.cost_audit_lighting(model, std).to_f
    end
  end

  # ----------------------------------------------------------------- loads
  module Loads
    PAIRS = [
      ['Space Function', 'Office enclosed > 25 m2'],
      ['Space Function', 'Corridor/Transition area other-sch-A'],
      ['Space Function', 'Dining area - family dining'],
      ['Space Function', 'Food preparation area'],
      ['Space Function', 'Warehouse storage area medium to bulky palletized items'],
      ['Space Function', 'Classroom/Lecture hall/Training room other'],
      ['Space Function', 'Computer/Server room-sch-A']
    ].freeze

    module_function

    # {'schedule name' => ruleset_signature} for every unique vendored name.
    def schedules(std, names)
      names.to_h do |name|
        model = OpenStudio::Model::Model.new
        [name, Signatures.ruleset_signature(std.model_add_schedule(model, name))]
      end
    end

    # {'bt|st' => {'loads' => sig, 'thermostat' => sig}} for the given pairs,
    # applied by the legacy space_type_apply_* trio on one tagged model.
    def apply(std, pairs)
      model = OpenStudio::Model::Model.new
      pairs.each do |building_type, space_type|
        st = OpenStudio::Model::SpaceType.new(model)
        st.setName("#{building_type} #{space_type}")
        st.setStandardsBuildingType(building_type)
        st.setStandardsSpaceType(space_type)
      end
      model.getSpaceTypes.sort_by(&:nameString).each do |space_type|
        std.space_type_apply_internal_loads(space_type: space_type, set_lights: false)
        std.space_type_apply_internal_load_schedules(space_type, set_lights: false)
        std.space_type_apply_thermostat_schedules(space_type)
      end
      pairs.to_h do |building_type, space_type_name|
        full = "#{building_type} #{space_type_name}"
        st = model.getSpaceTypes.find { |s| s.nameString == full }
        [full, { 'loads' => Signatures.loads_signature(st),
                 'thermostat' => Signatures.thermostat_signature(model, "#{full} Thermostat") }]
      end
    end

    # The runtime deep-merged legacy tables, verbatim.
    def merged_tables(std)
      { 'space_types' => std.standards_data['tables']['space_types']['table'],
        'schedules' => std.standards_data['tables']['schedules']['table'] }
    end
  end

  # -------------------------------------------------------------- lighting
  module Lighting
    PAIRS = [
      ['Space Function', 'Office enclosed > 25 m2'],
      ['Space Function', 'Conference/Meeting/Multi-purpose room'],
      ['Space Function', 'Corridor/Transition area other-sch-A'],
      ['Space Function', 'Dining area - family dining'],
      ['Space Function', 'Classroom/Lecture hall/Training room other']
    ].freeze

    module_function

    # {'bt|st' => lights_signature} for one lights_type.
    def lights(std, pairs, lights_type)
      model = OpenStudio::Model::Model.new
      pairs.each do |bt, st|
        space_type = OpenStudio::Model::SpaceType.new(model)
        space_type.setName("#{bt} #{st}")
        space_type.setStandardsBuildingType(bt)
        space_type.setStandardsSpaceType(st)
      end
      model.getSpaceTypes.sort_by(&:nameString).each do |space_type|
        std.space_type_apply_internal_loads(space_type: space_type,
                                            set_people: false, set_electric_equipment: false,
                                            set_gas_equipment: false, set_ventilation: false,
                                            set_infiltration: false, set_lights: true,
                                            lights_type: lights_type, lights_scale: 1.0)
        std.space_type_apply_internal_load_schedules(space_type,
                                                     set_people: false, set_electric_equipment: false,
                                                     set_gas_equipment: false, set_ventilation: false,
                                                     set_lights: true)
      end
      pairs.to_h do |bt, st_name|
        full = "#{bt} #{st_name}"
        [full, Signatures.lights_signature(model.getSpaceTypes.find { |s| s.nameString == full })]
      end
    end

    # [primary_sidelighted_area, vt_handle, window_area_sum]
    def sidelighting(std, space, floor)
      std.get_parameters_sidelighting(daylight_space: space, floor_surface: floor,
                                      floor_vertices: [floor.vertices], floor_area: floor.netArea,
                                      primary_sidelighted_area: 0.0, area_weighted_vt_handle: 0.0,
                                      window_area_sum: 0.0).map(&:to_f)
    end

    # [daylighted_under_skylight_area, vt_handle, skylight_area_sum]
    def skylight(std, space)
      std.get_parameters_skylight(daylight_space: space, skylight_area_weighted_vt_handle: 0.0,
                                  skylight_area_sum: 0.0, daylighted_under_skylight_area: 0.0).map(&:to_f)
    end

    # Control placement on an already-tagged model (mutates it).
    def daylighting_controls(std, model)
      std.model_add_daylighting_controls(model: model, daylighting_type: 'NECB_Default')
      Signatures.daylighting_controls_signature(model)
    end
  end

  # ------------------------------------------------------------------- shw
  module Shw
    EFFICIENCY_CASES = [
      ['Electricity', 11_000, 0.200],   # electric small, low volume
      ['Electricity', 11_000, 0.300],   # electric small, >=270 L formula
      ['Electricity', 40_000, 0.300],   # electric large
      ['NaturalGas', 15_000, 0.100],    # gas 76-208 L (FHR 221 -> 193-284 bin)
      ['NaturalGas', 15_000, 0.150],    # gas 76-208 L (FHR 256)
      ['NaturalGas', 20_000, 0.300],    # gas 208-380 L (FHR 361 -> >=284 bin)
      ['NaturalGas', 25_000, 0.400],    # gas 22-30.5 kW row
      ['NaturalGas', 100_000, 0.500],   # large gas: Et + SL
      ['FuelOilNo2', 15_000, 0.150]     # oil follows the gas path (legacy)
    ].freeze

    module_function

    # model_add_swh on the given tagged model (mutates it):
    # {'heater' => sig, 'water_use' => [sigs]}
    def swh(std, tagged_model)
      std.model_add_swh(model: tagged_model, swh_fueltype: 'NaturalGas', shw_scale: 1.0)
      heater = tagged_model.getWaterHeaterMixeds.first
      { 'heater' => heater ? Signatures.water_heater_signature(heater) : nil,
        'water_use' => Signatures.water_use_signatures(tagged_model) }
    end

    # {'fuel/capacity/volume' => efficiency signature} across the fixed bins.
    def efficiencies(std)
      EFFICIENCY_CASES.to_h do |fuel, capacity_w, volume_m3|
        model = OpenStudio::Model::Model.new
        heater = OpenStudio::Model::WaterHeaterMixed.new(model)
        heater.setTankVolume(volume_m3)
        heater.setHeaterMaximumCapacity(capacity_w)
        heater.setHeaterFuelType(fuel)
        std.water_heater_mixed_apply_efficiency(heater)
        ["#{fuel}/#{capacity_w}/#{volume_m3}", Signatures.water_heater_efficiency_signature(heater)]
      end
    end
  end
end
