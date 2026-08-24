module OpenStudioLighting
  module NECB
    module StorageGarage
      module_function

      def space_types(spaces)
        spaces.filter_map { |s| s.spaceType.empty? ? nil : s.spaceType.get }.uniq.sort_by(&:nameString)
      end

      def space_type_record(space_type, data_vintage)
        bt = space_type.standardsBuildingType
        st = space_type.standardsSpaceType
        return nil unless bt.is_initialized && st.is_initialized

        BtapNECB::Loads::SpaceTypes.find(building_type: bt.get, space_type: st.get, vintage: data_vintage)
      end

      def lighting_power_density(space)
        floor_area = space.floorArea
        return 0.0 unless floor_area.positive?

        instances = space.lights.to_a
        instances += space.spaceType.get.lights.to_a if space.spaceType.is_initialized
        instances.sum do |instance|
          definition = instance.lightsDefinition
          multiplier = instance.multiplier
          case definition.designLevelCalculationMethod
          when 'Watts/Area'
            definition.wattsperSpaceFloorArea.is_initialized ? definition.wattsperSpaceFloorArea.get * multiplier : 0.0
          when 'LightingLevel'
            definition.lightingLevel.is_initialized ? definition.lightingLevel.get * multiplier / floor_area : 0.0
          else
            0.0
          end
        end
      end

      def set_lighting_schedule(space_type, ruleset)
        set = space_type.defaultScheduleSet
        return false if set.empty?

        set.get.setLightingSchedule(ruleset)
        true
      end

      # A copy of the lighting schedule with the unoccupied hours scaled down.
      #
      # "No activity detected for 20 min" has no representation in an hourly
      # schedule — the shortest thing a ScheduleRuleset can express is the hour.
      # Modulating the hours the occupancy schedule reports as unoccupied is the
      # honest approximation, and it is what 4.2.2.1.(16)-(23) already does; the
      # 20-minute delay is recorded in the audit inputs rather than modelled.
      def build_reduced_ruleset(model, name, occupancy_rows, lighting_rows, reduction)
        require 'date'
        ruleset = OpenStudio::Model::ScheduleRuleset.new(model)
        ruleset.setName(name)
        factor = 1.0 - reduction

        occupancy_rows.each do |occupancy_row|
          lighting_row = lighting_rows.find { |r| r['day_types'] == occupancy_row['day_types'] }
          next if lighting_row.nil?

          day_types = occupancy_row['day_types'].to_s
          values = occupancy_row['values'].each_with_index.map do |occ, hour|
            light = lighting_row['values'][hour].to_f
            occ.to_f.zero? ? light * factor : light
          end
          write_day(model, ruleset, day_types, values, occupancy_row, name)
        end
        ruleset
      end

      # Sunset-to-sunrise reduction for (3). Astronomical sunset varies through
      # the year; a fixed night window is the schedule-level approximation, and
      # the audit says so. (The gem's one true sunset/sunrise control is
      # Exterior's AstronomicalClock option, which applies to exterior luminaires
      # and cannot drive an interior lighting schedule.)
      NIGHT_HOURS = (0..6).to_a + (19..23).to_a

      def build_night_reduced_ruleset(model, name, source, reduction)
        ruleset = OpenStudio::Model::ScheduleRuleset.new(model)
        ruleset.setName(name)
        factor = 1.0 - reduction
        base = source.to_ScheduleRuleset
        default_values = base.is_initialized ? day_values(base.get.defaultDaySchedule) : Array.new(24, 1.0)
        values = default_values.each_with_index.map { |v, hour| NIGHT_HOURS.include?(hour) ? v * factor : v }
        write_values(ruleset.defaultDaySchedule, values)
        ruleset
      end

      def day_values(day_schedule)
        values = Array.new(24, 0.0)
        day_schedule.times.each_with_index do |time, i|
          hour = time.totalHours.ceil
          value = day_schedule.values[i]
          (0...24).each { |h| values[h] = value if h < hour && values[h].zero? }
        end
        values
      end

      def write_day(model, ruleset, day_types, values, row, name)
        if day_types.include?('Default')
          ruleset.defaultDaySchedule.setName("#{name.sub(' Ruleset', '')} Default")
          write_values(ruleset.defaultDaySchedule, values)
        end
        return unless BtapNECB::Loads::Schedules::DAY_TOKENS.any? { |t| day_types.include?(t) }

        rule = OpenStudio::Model::ScheduleRule.new(ruleset)
        rule.daySchedule.setName("#{name.sub(' Ruleset', '')}-#{day_types}")
        write_values(rule.daySchedule, values)
        start_date = Date.parse(row['start_date'])
        end_date = Date.parse(row['end_date'])
        rule.setStartDate(OpenStudio::Date.new(OpenStudio::MonthOfYear.new(start_date.month), start_date.day))
        rule.setEndDate(OpenStudio::Date.new(OpenStudio::MonthOfYear.new(end_date.month), end_date.day))
        if day_types.include?('Wknd')
          rule.setApplySaturday(true)
          rule.setApplySunday(true)
        end
        %w[Monday Tuesday Wednesday Thursday Friday].each { |d| rule.send("setApply#{d}", true) } if day_types.include?('Wkdy')
      end

      def write_values(day_schedule, values)
        day_schedule.clearValues
        values.each_with_index do |value, hour|
          day_schedule.addValue(OpenStudio::Time.new(0, hour + 1, 0, 0), value)
        end
      end

      # The zone-level daylighting control for (4).
      #
      # Daylighting.add_controls SKIPS a zone that already carries a primary
      # control, so a garage that also qualified under 4.2.2.1 would silently
      # lose this one. Table 4.2.1.6. defers garages to 4.2.2.2 precisely so the
      # two rules do not both apply, but the precedence is made explicit here
      # rather than left to whichever pass ran first.
      def add_daylight_control(space, band_area_m2, audit, article, inputs)
        zone = space.thermalZone
        if zone.empty?
          audit.warn(:lighting,
                     "STORAGE GARAGE '#{space.nameString}' HAS NO THERMAL ZONE — the 4.2.2.2.(4) daylight " \
                     'response cannot be attached', target: space.nameString, article: "#{article}(4)")
          return false
        end

        zone = zone.get
        if zone.primaryDaylightingControl.is_initialized
          audit.info(:lighting,
                     "zone '#{zone.nameString}' already carries a primary daylighting control — the " \
                     '4.2.2.2.(4) response is satisfied by it and no second control is added',
                     target: space.nameString, inputs: inputs, article: "#{article}(4)")
          return false
        end

        control = OpenStudio::Model::DaylightingControl.new(space.model)
        control.setName("#{space.nameString} Garage Daylight Sensor")
        control.setSpace(space)
        control.setLightingControlType('Stepped')
        control.setNumberofSteppedControlSteps(1) # on/off: the sentence asks only that power be reduced
        centre = space.floorArea.positive? ? space_centre(space) : nil
        if centre
          control.setPositionXCoordinate(centre[0])
          control.setPositionYCoordinate(centre[1])
          control.setPositionZCoordinate(0.8)
        end
        zone.setPrimaryDaylightingControl(control)
        fraction = space.floorArea.positive? ? [band_area_m2 / space.floorArea, 1.0].min : 0.0
        zone.setFractionofZoneControlledbyPrimaryDaylightingControl(fraction)
        audit.decision(:lighting,
                       'storage-garage perimeter luminaires respond to daylight (>150 W within 6.1 m of a ' \
                       '40%-glazed perimeter wall)',
                       target: space.nameString,
                       inputs: inputs.merge(zone_fraction_controlled: fraction.round(4)),
                       article: "#{article}(4)")
        true
      end

      def space_centre(space)
        points = space.surfaces.select { |s| s.surfaceType == 'Floor' }.flat_map(&:vertices)
        return nil if points.empty?

        [points.sum(&:x) / points.size, points.sum(&:y) / points.size]
      end
    end
  end
end
