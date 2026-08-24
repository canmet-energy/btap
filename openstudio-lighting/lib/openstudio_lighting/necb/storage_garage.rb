module OpenStudioLighting
  module NECB
    # Article 4.2.2.2 — Lighting Controls in Storage Garages.
    #
    # Table 4.2.1.6. defers interior storage/parking garages to THIS article
    # rather than to 4.2.2.1.(10)/(13), so a garage is deliberately excluded
    # from the ordinary photocontrol rule and carries its own, different one.
    #
    #   (1) lighting divided into zones no larger than 360 m2
    #   (2) >=30% automatic reduction when no activity is detected for 20 min
    #   (3) covered vehicle entrances/exits separately controlled, >=50%
    #       reduction from sunset to sunrise
    #   (4) where the combined input of luminaires within 6.1 m of a perimeter
    #       wall with >=40% net opening-to-wall ratio (and no exterior
    #       obstruction within 6.1 m) exceeds 150 W, those luminaires reduce
    #       automatically in response to daylight
    #   (5) daylight transition zones and ramps without parking are exempt from
    #       (1), (2) and (4)
    #
    # Controls are modelled the way the rest of this gem models them: as
    # SCHEDULE MODULATION and audited determinations, not as sensor objects.
    # That is the 4.2.2.1.(16)-(23) precedent and it is deliberate — the SDK has
    # no occupancy-sensor object, and inventing one would put hardware in the
    # model that the code never asked to be simulated.
    module StorageGarage
      module_function

      ZONE_AREA_LIMIT_M2 = 360.0        # (1)
      OCCUPANCY_REDUCTION = 0.30        # (2) at least 30%
      ENTRANCE_REDUCTION = 0.50         # (3) at least 50%
      PERIMETER_BAND_M = 6.1            # (4)
      GLAZED_WALL_RATIO = 0.40          # (4) net opening-to-wall
      DAYLIGHT_POWER_THRESHOLD_W = 150.0 # (4)

      # Table 4.2.1.6. sends 'Storage garage interior' here; 'Storage garage' is
      # the building-type row. 'Emergency vehicle garage' is deliberately NOT
      # matched — the control matrix lists it as required/required under
      # 4.2.2.1, so it is not deferred to this article.
      GARAGE_SPACE_TYPES = [/\Astorage garage/i, /\Aparking garage/i].freeze

      def garage?(space)
        st = space.spaceType
        return false if st.empty?

        name = st.get.standardsSpaceType
        building = st.get.standardsBuildingType
        candidates = [name.is_initialized ? name.get : nil, building.is_initialized ? building.get : nil].compact
        candidates.any? { |c| GARAGE_SPACE_TYPES.any? { |re| c =~ re } }
      end

      def garage_spaces(model)
        model.getSpaces.sort_by(&:nameString).select { |s| s.partofTotalFloorArea && garage?(s) }
      end

      # @param model [OpenStudio::Model::Model]
      # @param vintage [String]
      # @param entrance_spaces [Array<String>, nil] names of spaces that ARE
      #   covered vehicle entrances/exits. Geometry cannot tell an entrance bay
      #   from an ordinary bay, so (3) is applied only when the modeller says
      #   which spaces they are, and is declared otherwise.
      # @param audit [AuditLog]
      # @return [Hash] the determinations, keyed by sentence
      def apply(model, vintage: '2020', entrance_spaces: nil, audit: nil)
        audit ||= AuditLog.new
        spaces = garage_spaces(model)
        if spaces.empty?
          audit.info(:lighting, 'no storage-garage space types in the model — Article 4.2.2.2. does not apply',
                     article: '4.2.2.2.')
          return { applies: false }
        end

        article = vintage.to_s == '2025' ? '4.2.2.2.' : '4.2.2.2.'
        result = { applies: true, spaces: spaces.size }
        result[:zoning] = check_zoning(spaces, audit, article)
        result[:occupancy] = apply_occupancy_reduction(model, spaces, vintage, audit, article)
        result[:entrances] = apply_entrance_control(model, spaces, entrance_spaces, audit, article)
        result[:daylight] = apply_daylight_response(model, spaces, audit, article)
        declare_exemptions(audit, article)
        result
      end

      # (1) zones no larger than 360 m2. A CHECK, not a transform: re-zoning a
      # model to satisfy a lighting-control rule would silently change the
      # thermal results.
      def check_zoning(spaces, audit, article)
        zones = spaces.filter_map { |s| s.thermalZone.empty? ? nil : s.thermalZone.get }.uniq
        oversized = zones.select { |z| z.floorArea > ZONE_AREA_LIMIT_M2 }
        inputs = { garage_zones: zones.size, limit_m2: ZONE_AREA_LIMIT_M2,
                   oversized: oversized.map(&:nameString) }
        if oversized.empty?
          audit.decision(:lighting, 'storage-garage lighting zones are within the 360 m2 limit',
                         inputs: inputs, article: "#{article}(1)")
        else
          audit.warn(:lighting,
                     "STORAGE-GARAGE LIGHTING ZONE EXCEEDS 360 m2: #{oversized.map(&:nameString).join(', ')} " \
                     '— 4.2.2.2.(1) requires the lighting to be divided into zones no larger than 360 m2',
                     inputs: inputs, article: "#{article}(1)")
        end
        { oversized: oversized.size, zones: zones.size }
      end

      # (2) >=30% reduction when no activity for 20 min.
      #
      # The gem's existing occupancy-sensor path cannot serve this: it is gated
      # on LPD > 8.6 W/m2 and both garage records sit at 1.5-1.9 W/m2, so it
      # never fires for a garage. And the Table 4.3.2.10 factors it would use
      # give a 26.8% reduction for 'Storage garage interior' and 0% for the
      # building-type row — both short of the 30% this sentence demands. So the
      # floor is applied explicitly here.
      def apply_occupancy_reduction(model, spaces, vintage, audit, article)
        data_vintage = NECB.data_vintage(vintage)
        applied = []
        space_types(spaces).each do |space_type|
          record = space_type_record(space_type, data_vintage)
          next if record.nil?

          lighting_name = record['lighting_schedule'].to_s
          occupancy_name = record['occupancy_schedule'].to_s
          schedules = BtapNECB::Loads.table(data_vintage, 'schedules')
          lighting_rows = schedules.select { |r| r['name'] == lighting_name }
          occupancy_rows = schedules.select { |r| r['name'] == occupancy_name }
          if lighting_rows.empty? || occupancy_rows.empty?
            audit.warn(:lighting, "4.2.2.2.(2) needs both '#{occupancy_name}' and '#{lighting_name}' schedules " \
                                  '— the 30% unoccupied reduction was NOT applied',
                       target: space_type.nameString, article: "#{article}(2)")
            next
          end

          name = "#{lighting_name}-garage-occ#{(OCCUPANCY_REDUCTION * 100).round}-Light Ruleset"
          ruleset = model.getSchedules.sort_by(&:nameString).find { |s| s.nameString == name } ||
                    build_reduced_ruleset(model, name, occupancy_rows, lighting_rows, OCCUPANCY_REDUCTION)
          set_lighting_schedule(space_type, ruleset)
          applied << space_type.nameString
        end

        audit.decision(:lighting,
                       'storage-garage lighting reduced by 30% when unoccupied (schedule modulation, ' \
                       'the 4.2.2.1.(16)-(23) convention — no sensor object is created)',
                       inputs: { space_types: applied, reduction: OCCUPANCY_REDUCTION,
                                 detection_delay_min: 20 },
                       article: "#{article}(2)")
        { space_types: applied }
      end

      # (3) covered vehicle entrances/exits, >=50% sunset to sunrise.
      #
      # No geometry distinguishes an entrance bay from any other bay, and no
      # space-type row marks one. Applied when the modeller names the spaces;
      # declared as requiring identification otherwise, rather than guessed.
      def apply_entrance_control(model, spaces, entrance_spaces, audit, article)
        names = Array(entrance_spaces).map(&:to_s)
        if names.empty?
          audit.info(:lighting,
                     'requires identification by the modeller: 4.2.2.2.(3) separately controls COVERED VEHICLE ' \
                     'ENTRANCES AND EXITS at >=50% reduction from sunset to sunrise, and no geometry or space ' \
                     'type distinguishes an entrance bay from an ordinary parking bay — pass entrance_spaces: ' \
                     'to apply it',
                     article: "#{article}(3)")
          return { applied: [], declared: true }
        end

        matched = spaces.select { |s| names.include?(s.nameString) }
        missing = names - matched.map(&:nameString)
        unless missing.empty?
          audit.warn(:lighting, "entrance_spaces named spaces that are not storage garages: #{missing.join(', ')}",
                     article: "#{article}(3)")
        end
        applied = []
        space_types(matched).each do |space_type|
          schedule = space_type.defaultScheduleSet
          next if schedule.empty?

          lighting = schedule.get.lightingSchedule
          next if lighting.empty?

          name = "#{lighting.get.nameString}-garage-entrance-night#{(ENTRANCE_REDUCTION * 100).round}"
          ruleset = model.getSchedules.sort_by(&:nameString).find { |s| s.nameString == name } ||
                    build_night_reduced_ruleset(model, name, lighting.get, ENTRANCE_REDUCTION)
          set_lighting_schedule(space_type, ruleset)
          applied << space_type.nameString
        end
        audit.decision(:lighting,
                       'covered vehicle entrance/exit lighting reduced by 50% from sunset to sunrise',
                       inputs: { spaces: matched.map(&:nameString), space_types: applied,
                                 reduction: ENTRANCE_REDUCTION },
                       article: "#{article}(3)")
        { applied: applied, declared: false }
      end

      # (4) daylight response where >150 W of luminaires sit within 6.1 m of a
      # >=40%-glazed perimeter wall.
      #
      # Power is LPD x band area, the same convention 4.2.2.1's own >150 W /
      # >300 W thresholds use (DaylightControlRequirement) — the model carries no
      # luminaire inventory, so installed power per band is derived, not counted.
      def apply_daylight_response(model, spaces, audit, article)
        findings = []
        spaces.each do |space|
          band = Perimeter.qualifying_band_area(space, audit)
          next if band[:area_m2] <= 0.0

          lpd = lighting_power_density(space)
          power = lpd * band[:area_m2]
          inputs = { glazed_walls: band[:walls], band_depth_m: PERIMETER_BAND_M,
                     opening_ratio_threshold: GLAZED_WALL_RATIO,
                     band_area_m2: band[:area_m2].round(2), lpd_w_per_m2: lpd.round(3),
                     luminaire_power_w: power.round(1), threshold_w: DAYLIGHT_POWER_THRESHOLD_W }
          if power > DAYLIGHT_POWER_THRESHOLD_W
            add_daylight_control(space, band[:area_m2], audit, article, inputs)
            findings << { space: space.nameString, power_w: power.round(1), controlled: true }
          else
            audit.decision(:lighting,
                           'storage-garage perimeter luminaire power is at or below 150 W — 4.2.2.2.(4) ' \
                           'does not require a daylight response',
                           target: space.nameString, inputs: inputs, article: "#{article}(4)")
            findings << { space: space.nameString, power_w: power.round(1), controlled: false }
          end
        end
        if findings.empty?
          audit.info(:lighting,
                     'no storage-garage space has a perimeter wall at or above 40% net opening — ' \
                     '4.2.2.2.(4) does not apply',
                     article: "#{article}(4)")
        end
        findings
      end

      # (5) is an exemption the model cannot evaluate: neither a daylight
      # transition zone nor a ramp-without-parking is distinguishable from an
      # ordinary bay by geometry or by space type.
      def declare_exemptions(audit, article)
        audit.info(:lighting,
                   'requires identification by the modeller: 4.2.2.2.(5) exempts DAYLIGHT TRANSITION ZONES and ' \
                   'RAMPS WITHOUT PARKING from Sentences (1), (2) and (4). Neither is distinguishable from an ' \
                   'ordinary parking bay in the model, so the determinations above are applied to every ' \
                   'garage space and an exempt space should be excluded by the reviewer',
                   article: "#{article}(5)")
      end
    end
  end
end

require_relative 'storage_garage/perimeter'
require_relative 'storage_garage/schedules'
