require_relative 'test_helper'
require_relative 'support/oracle_probes'

# P3 gate (parity half): resulting PER-SURFACE construction conductances match legacy
# apply_standard_construction_properties (mechanism-agnostic — legacy rewrites default
# construction sets via BTAP; the gem hard-assigns). Skips without openstudio-standards.
# Oracle-side values come from OracleProbes::Envelope.prescriptive — the same
# function the Leg-C golden exporter freezes (D-78).
class TestPrescriptiveParity < Minitest::Test
  include FixtureHelper

  def legacy
    OracleProbes::Access.gate!(self, OracleProbes::Access.standard)
  end

  # The BTAP-Mass default set in this repo lacks a few subsurface constructions
  # (tubular domes/diffusers), which crashes legacy customize_default_sub_surface_
  # constructions_conductance with 'Optional not initialized'. Fill the gaps with
  # sensible stand-ins so the legacy path can run; this does not affect the
  # surface-conductance comparison.
  def complete_default_subsurface_set!(model)
    model.getDefaultConstructionSets.each do |set|
      subs = set.defaultExteriorSubSurfaceConstructions
      next if subs.empty?

      subs = subs.get
      fallback_glazing = subs.fixedWindowConstruction
      fallback_opaque = subs.doorConstruction
      next if fallback_glazing.empty?

      subs.setOperableWindowConstruction(fallback_glazing.get) if subs.operableWindowConstruction.empty?
      subs.setGlassDoorConstruction(fallback_glazing.get) if subs.glassDoorConstruction.empty?
      subs.setSkylightConstruction(fallback_glazing.get) if subs.skylightConstruction.empty?
      subs.setTubularDaylightDomeConstruction(fallback_glazing.get) if subs.tubularDaylightDomeConstruction.empty?
      subs.setTubularDaylightDiffuserConstruction(fallback_glazing.get) if subs.tubularDaylightDiffuserConstruction.empty?
      subs.setOverheadDoorConstruction(fallback_opaque.get) if !fallback_opaque.empty? && subs.overheadDoorConstruction.empty?
    end
  end

  def legacy_prescriptive
    @legacy_prescriptive ||= OracleProbes::Envelope.prescriptive(
      legacy,
      attach_weather!(load_raw_fixture),
      attach_weather!(load_raw_fixture),
      subsurface_patch: method(:complete_default_subsurface_set!)
    )
  end

  def test_per_surface_conductance_parity
    std = legacy
    legacy_c = legacy_prescriptive['conductances']

    gem_model = attach_weather!(load_raw_fixture)
    # same starting constructions as the legacy path so base assemblies match.
    # include_films: false — this is a MECHANISM-parity gate against legacy
    # apply_standard_construction_properties (BTAP, construction-only
    # conductance); the gem's default is include_films: true (code-literal,
    # matching the OSut path the NECB2020 prototypes actually use).
    std.model_add_constructions(gem_model)
    BtapNECB::Envelope.apply_prescriptive(gem_model, vintage: '2020', include_films: false)
    gem_c = OracleProbes::Signatures.surface_conductances(gem_model)

    mismatches = legacy_c.keys.filter_map do |name|
      l = legacy_c[name]
      g = gem_c[name]
      "#{name}: legacy #{l} vs gem #{g}" if g.nil? || (l - g).abs > 1e-3
    end
    assert_empty mismatches, mismatches.join("\n")
    assert_operator legacy_c.size, :>, 8, 'meaningful surface count compared (ground floors excluded per D-32)'
  end

  def test_fdwr_area_parity
    std = legacy
    legacy_fdwr = legacy_prescriptive['fdwr']

    gem_model = attach_weather!(load_raw_fixture)
    std.model_add_constructions(gem_model)
    BtapNECB::Envelope.apply_prescriptive(gem_model, vintage: '2020', apply_fdwr: true)
    gem_census = BtapModeling::Geometry.exposed_walls(gem_model)

    assert_in_delta legacy_fdwr, gem_census[:fdwr], 0.01,
                    'FDWR after mutation matches legacy apply_max_fdwr_nrcan'
  end
end
