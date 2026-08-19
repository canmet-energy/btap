module OpenStudioSHW
  module NECB
    # Section 6.2 prescriptive requirements that a MODEL can actually answer.
    #
    # Most of 6.2.3-6.2.7 cannot be: they govern installed hardware (a device
    # that shuts a pool heater off, insulation thickness on a pipe run) that an
    # energy model has no object for. Those are declared in the coverage
    # manifest as modeller scope, and this module deliberately does not pretend
    # to check them.
    #
    # What IS answerable is the one rule keyed on the DEMAND the model already
    # sizes from: 6.2.5.1's booster-heater trigger.
    module Prescriptive
      module_function

      BOOSTER_TEMPERATURE_C = 60.0
      BOOSTER_FLOW_FRACTION = 0.50

      # 6.2.5.1: "Where LESS THAN 50% of the total design flow of a service
      # water heating system has a design discharge temperature higher than
      # 60 C, separate remote heaters or booster heaters shall be installed for
      # those portions of the system with a design temperature higher than 60 C."
      #
      # The rule is a trap for the unwary: it fires when the hot fraction is
      # SMALL, not large. A system that is mostly >60 C is allowed to run one
      # plant; a system with a minority high-temperature load must not drag the
      # whole plant up to serve it.
      #
      # auto_size already has everything needed — each spaces_w_dhw entry
      # carries peak_flow_si and temperature_c — and then discards it by
      # collapsing to a single max_temp_c. This reads it before it is lost.
      #
      # @param sizing [Hash] the auto_size result
      # @param model [OpenStudio::Model::Model]
      # @param audit [AuditLog]
      # @return [Hash, nil] the determination, or nil when there is no demand
      def check_booster_heaters(sizing, model, audit)
        spaces = Array(sizing['spaces_w_dhw'])
        return nil if spaces.empty?

        total = spaces.sum { |s| s['peak_flow_si'].to_f }
        return nil unless total.positive?

        hot = spaces.select { |s| s['temperature_c'].to_f > BOOSTER_TEMPERATURE_C }
        hot_flow = hot.sum { |s| s['peak_flow_si'].to_f }
        fraction = hot_flow / total
        heaters = model.getWaterHeaterMixeds.size

        result = { fraction: fraction.round(4), hot_spaces: hot.size, water_heaters: heaters }
        inputs = { high_temp_flow_fraction: fraction.round(4),
                   threshold_c: BOOSTER_TEMPERATURE_C,
                   spaces_above_threshold: hot.size, water_heaters_in_model: heaters }

        if hot.empty?
          # Not a pass and not a failure — the sentence has no subject.
          audit.info(:shw, 'sentence 6.2.5.1 is vacuous — no space calls for service water above 60 C, ' \
                           'so no portion of the system needs a separate booster heater',
                     inputs: inputs, article: '6.2.5.1.')
        elsif fraction >= BOOSTER_FLOW_FRACTION
          audit.decision(:shw, 'booster heaters not required — at least half the design flow is above 60 C, ' \
                               'so the whole system may be served by one plant',
                         inputs: inputs, value: "#{(fraction * 100).round(1)}% of design flow above 60 C",
                         article: '6.2.5.1.')
        elsif heaters > 1
          audit.decision(:shw, 'a minority of the design flow is above 60 C and the model carries more than ' \
                               'one water heater — the separate booster heater appears to be present',
                         inputs: inputs, value: "#{(fraction * 100).round(1)}% of design flow above 60 C",
                         article: '6.2.5.1.')
        else
          # SHOUTED: the checklist classifier is case-sensitive about violations.
          audit.warn(:shw, 'BOOSTER HEATER REQUIRED and NOT present: only ' \
                           "#{(fraction * 100).round(1)}% of the design flow is above 60 C, and the model has " \
                           'a single water heater serving every load. 6.2.5.1 requires separate remote or ' \
                           'booster heaters for the portions above 60 C',
                     inputs: inputs, article: '6.2.5.1.')
        end
        result
      end

      # The clauses of 6.2.3-6.2.7 that no model can answer, named individually
      # so an AHJ sees each one accounted for rather than absent.
      #
      # This is a DECLARATION, not a check. It exists because silence reads as
      # "not applicable", and these very much apply — they are simply verified
      # from drawings and on site rather than from an .osm.
      FIELD_VERIFIED = {
        '6.2.3.1.' => 'piping insulation thickness (Table 6.2.3.1.) — the model carries no pipe objects ' \
                      'and no pipe-run lengths, so thickness cannot be checked',
        '6.2.4.3.' => 'heat-trace temperature-maintenance controls — no model object represents them',
        '6.2.6.1.' => 'shower head flow limit 7.6 L/min — the model holds a per-area aggregate demand ' \
                      'with no fixture count, so a per-showerhead rate cannot be derived',
        '6.2.6.2.' => 'lavatory flow limits (5.7 L/min private, 1.9 L/min public) — same reason as 6.2.6.1.',
        '6.2.7.1.' => 'pool heater shutoff device and pump/heater time switches — installed controls',
        '6.2.7.2.' => 'pool and hot-tub covers — EnergyPlus models INDOOR pools only, and this sentence ' \
                      'governs heated OUTDOOR pools and tubs'
      }.freeze

      def declare_field_verified(audit)
        FIELD_VERIFIED.each do |article, what|
          audit.info(:shw, "requires field or document verification: #{what}", article: article)
        end
      end
    end
  end
end
