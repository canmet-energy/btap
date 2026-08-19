require 'json'

module OpenStudioHVAC
  # Builds OpenStudio performance-curve objects from the gem's data/curves.json.
  module Curves
    DATA_PATH = File.expand_path('../data/curves.json', __dir__)

    def self.data
      @data ||= JSON.parse(File.read(DATA_PATH))['curves']
    end

    # The defrost Energy Input Ratio modifier, f(T).
    #
    # EnergyPlus REQUIRES this field whenever Defrost Strategy is 'ReverseCycle'
    # — on Coil:Heating:DX:SingleSpeed, Coil:Heating:DX:VariableSpeed and
    # AirConditioner:VariableRefrigerantFlow alike:
    #
    #   ** Severe ** ...required Defrost Energy Input Ratio Function of
    #                Temperature Curve Name is blank.
    #                ...field is required because Defrost Strategy is "ReverseCycle".
    #
    # and the SDK leaves it unset, because its own default strategy is
    # 'Resistive', which needs no curve. Setting the strategy without the curve
    # therefore produces a model that looks fine to every in-process check and
    # is rejected by EnergyPlus. Eight catalog systems shipped that way.
    #
    # The value is 1.0 — deliberately, not as a placeholder. The legacy oracle
    # supplies a 22-point lookup table for this curve whose output is 1.0 at
    # EVERY point (15.0-27.2 C indoor, -25 to +6 C outdoor), i.e. defrost EIR is
    # not modified by temperature. A biquadratic with c1 = 1 and every other
    # coefficient 0 is that same function, without importing the table.
    #
    # @return [OpenStudio::Model::CurveBiquadratic] shared per model
    def self.defrost_eir_ft(model)
      name = 'DEFROST-EIR-FT'
      existing = model.getCurves.find { |c| c.nameString == name }
      return existing.to_CurveBiquadratic.get unless existing.nil?

      curve = OpenStudio::Model::CurveBiquadratic.new(model)
      curve.setName(name)
      curve.setCoefficient1Constant(1.0)
      [curve.method(:setCoefficient2x), curve.method(:setCoefficient3xPOW2),
       curve.method(:setCoefficient4y), curve.method(:setCoefficient5yPOW2),
       curve.method(:setCoefficient6xTIMESY)].each { |m| m.call(0.0) }
      # The oracle table's own independent-variable span; outside it EnergyPlus
      # clamps, which for a constant function changes nothing.
      curve.setMinimumValueofx(15.0)
      curve.setMaximumValueofx(27.2)
      curve.setMinimumValueofy(-25.0)
      curve.setMaximumValueofy(6.0)
      curve
    end

    # Build (or fetch, if already present in the model) a named curve.
    #
    # @param model [OpenStudio::Model::Model]
    # @param name [String] a curve name from data/curves.json
    # @return [OpenStudio::Model::Curve]
    def self.build(model, name)
      existing = model.getCurves.find { |c| c.nameString == name }
      return existing unless existing.nil?

      spec = data[name]
      raise(ArgumentError, "unknown curve '#{name}'") if spec.nil?

      curve = case spec['type']
              when 'biquadratic' then build_biquadratic(model, spec)
              when 'quadratic'   then build_quadratic(model, spec)
              when 'cubic'       then build_cubic(model, spec)
              when 'quadlinear'  then build_quadlinear(model, spec)
              else raise(ArgumentError, "unknown curve type '#{spec['type']}' for '#{name}'")
              end
      curve.setName(name)
      curve
    end

    def self.build_biquadratic(model, spec)
      curve = OpenStudio::Model::CurveBiquadratic.new(model)
      curve.setCoefficient1Constant(spec['coeff_1_constant'])
      curve.setCoefficient2x(spec['coeff_2_x'])
      curve.setCoefficient3xPOW2(spec['coeff_3_x2'])
      curve.setCoefficient4y(spec['coeff_4_y'])
      curve.setCoefficient5yPOW2(spec['coeff_5_y2'])
      curve.setCoefficient6xTIMESY(spec['coeff_6_xy'])
      curve.setMinimumValueofx(spec['min_x'])
      curve.setMaximumValueofx(spec['max_x'])
      curve.setMinimumValueofy(spec['min_y'])
      curve.setMaximumValueofy(spec['max_y'])
      curve.setMinimumCurveOutput(spec['min_out']) if spec['min_out']
      curve.setMaximumCurveOutput(spec['max_out']) if spec['max_out']
      curve
    end

    def self.build_quadlinear(model, spec)
      curve = OpenStudio::Model::CurveQuadLinear.new(model)
      curve.setCoefficient1Constant(spec['coeff_1'])
      curve.setCoefficient2w(spec['coeff_2'])
      curve.setCoefficient3x(spec['coeff_3'])
      curve.setCoefficient4y(spec['coeff_4'])
      curve.setCoefficient5z(spec['coeff_5'])
      curve.setMinimumValueofw(spec['min_w'])
      curve.setMaximumValueofw(spec['max_w'])
      curve.setMinimumValueofx(spec['min_x'])
      curve.setMaximumValueofx(spec['max_x'])
      curve.setMinimumValueofy(spec['min_y'])
      curve.setMaximumValueofy(spec['max_y'])
      curve.setMinimumValueofz(spec['min_z'])
      curve.setMaximumValueofz(spec['max_z'])
      curve
    end

    def self.build_quadratic(model, spec)
      curve = OpenStudio::Model::CurveQuadratic.new(model)
      curve.setCoefficient1Constant(spec['coeff_1_constant'])
      curve.setCoefficient2x(spec['coeff_2_x'])
      curve.setCoefficient3xPOW2(spec['coeff_3_x2'])
      curve.setMinimumValueofx(spec['min_x'])
      curve.setMaximumValueofx(spec['max_x'])
      curve
    end

    def self.build_cubic(model, spec)
      curve = OpenStudio::Model::CurveCubic.new(model)
      curve.setCoefficient1Constant(spec['coeff_1_constant'])
      curve.setCoefficient2x(spec['coeff_2_x'])
      curve.setCoefficient3xPOW2(spec['coeff_3_x2'])
      curve.setCoefficient4xPOW3(spec['coeff_4_x3'])
      curve.setMinimumValueofx(spec['min_x'])
      curve.setMaximumValueofx(spec['max_x'])
      curve
    end
  end
end
