require_relative 'test_helper'

# Article 4.2.2.2 — Lighting Controls in Storage Garages.
#
# The repo has no storage-garage fixture (every .osm is the same 800 m2 office),
# so these build geometry from scratch the way test_daylighting_necb2020.rb
# does. That is not incidental: (1) and (4) are geometric rules, and a fixture
# with one zone and four windows could not exercise either.
class TestStorageGarage < Minitest::Test
  SG = BtapNECB::Lighting::StorageGarage
  PERIM = BtapNECB::Lighting::StorageGarage::Perimeter

  # A rectangular garage. `wwr` glazes the y = 0 wall to that fraction of its
  # gross area, which is what 4.2.2.2.(4)'s 40% threshold is measured against.
  def garage(width: 20.0, depth: 15.0, height: 3.0, wwr: 0.0,
             space_type: 'Storage garage interior', building_type: 'Space Function')
    model = OpenStudio::Model::Model.new
    space = OpenStudio::Model::Space.new(model)
    space.setName('Garage')
    zone = OpenStudio::Model::ThermalZone.new(model)
    space.setThermalZone(zone)

    floor = [[0, 0], [width, 0], [width, depth], [0, depth]].map { |x, y| OpenStudio::Point3d.new(x, y, 0) }
    surface(model, space, floor.reverse, 'Floor', 'Ground')
    surface(model, space, floor.map { |p| OpenStudio::Point3d.new(p.x, p.y, height) }, 'RoofCeiling', 'Outdoors')

    wall = [OpenStudio::Point3d.new(0, 0, height), OpenStudio::Point3d.new(0, 0, 0),
            OpenStudio::Point3d.new(width, 0, 0), OpenStudio::Point3d.new(width, 0, height)]
    front = surface(model, space, wall, 'Wall', 'Outdoors')
    if wwr.positive?
      # A ribbon centred on the wall, sized to hit the requested ratio exactly.
      wh = height * wwr
      sub = [OpenStudio::Point3d.new(0, 0, wh), OpenStudio::Point3d.new(0, 0, 0),
             OpenStudio::Point3d.new(width, 0, 0), OpenStudio::Point3d.new(width, 0, wh)]
      window = OpenStudio::Model::SubSurface.new(sub, model)
      window.setSurface(front)
      window.setSubSurfaceType('FixedWindow')
    end
    [[width, 0, width, depth], [width, depth, 0, depth], [0, depth, 0, 0]].each_with_index do |(x1, y1, x2, y2), i|
      pts = [OpenStudio::Point3d.new(x1, y1, height), OpenStudio::Point3d.new(x1, y1, 0),
             OpenStudio::Point3d.new(x2, y2, 0), OpenStudio::Point3d.new(x2, y2, height)]
      surface(model, space, pts, 'Wall', 'Outdoors').setName("Side #{i}")
    end

    st = OpenStudio::Model::SpaceType.new(model)
    st.setName("#{building_type} #{space_type}")
    st.setStandardsBuildingType(building_type)
    st.setStandardsSpaceType(space_type)
    st.setDefaultScheduleSet(OpenStudio::Model::DefaultScheduleSet.new(model))
    space.setSpaceType(st)
    [model, space, st]
  end

  def surface(model, space, points, type, boundary)
    s = OpenStudio::Model::Surface.new(points, model)
    s.setSpace(space)
    s.setSurfaceType(type)
    s.setOutsideBoundaryCondition(boundary)
    s
  end

  def light(space_type, w_per_m2)
    definition = OpenStudio::Model::LightsDefinition.new(space_type.model)
    definition.setWattsperSpaceFloorArea(w_per_m2)
    OpenStudio::Model::Lights.new(definition).setSpaceType(space_type)
  end

  def audit = BtapNECB::AuditLog.new

  def entry(log, article)
    log.entries.find { |e| e[:article].to_s.start_with?(article) }
  end

  # --- applicability -----------------------------------------------------

  def test_a_model_with_no_garage_is_not_subject_to_the_article
    model = OpenStudio::Model::Model.new
    log = audit
    assert_equal({ applies: false }, SG.apply(model, audit: log))
    assert_match(/does not apply/, entry(log, '4.2.2.2.')[:action])
  end

  # Table 4.2.1.6 lists emergency vehicle garages as required/required under
  # 4.2.2.1, so they are NOT deferred here and must not be swept in.
  def test_emergency_vehicle_garages_are_not_storage_garages
    _, space, = garage(space_type: 'Emergency vehicle garage')
    refute(SG.garage?(space))
  end

  def test_both_catalog_garage_rows_are_recognised
    _, interior, = garage(space_type: 'Storage garage interior')
    assert(SG.garage?(interior))
    _, whole, = garage(space_type: 'WholeBuilding', building_type: 'Storage garage')
    assert(SG.garage?(whole))
  end

  # --- (1) zoning --------------------------------------------------------

  def test_a_zone_within_360_m2_passes
    model, = garage(width: 20.0, depth: 15.0)   # 300 m2
    log = audit
    SG.apply(model, audit: log)
    e = entry(log, '4.2.2.2.(1)')
    assert_equal(:decision, e[:level])
    assert_match(/within the 360 m2 limit/, e[:action])
  end

  def test_an_oversized_zone_is_a_shouted_finding
    model, = garage(width: 40.0, depth: 15.0)   # 600 m2
    log = audit
    SG.apply(model, audit: log)
    e = entry(log, '4.2.2.2.(1)')
    assert_equal(:warning, e[:level])
    assert_match(/EXCEEDS 360 m2/, e[:action], 'violations are SHOUTED')
  end

  # --- (4) the geometry that did not exist -------------------------------

  def test_opening_ratio_is_net_over_gross_per_wall
    model, space, = garage(width: 20.0, height: 3.0, wwr: 0.5)
    front = space.surfaces.find { |s| s.subSurfaces.any? }
    assert_in_delta(0.5, PERIM.opening_ratio(front), 1e-6)
    blank = space.surfaces.find { |s| s.surfaceType == 'Wall' && s.subSurfaces.empty? }
    assert_in_delta(0.0, PERIM.opening_ratio(blank), 1e-6)
  end

  def test_only_walls_at_or_above_40_percent_qualify
    _, under, = garage(wwr: 0.39)
    assert_empty(PERIM.glazed_perimeter_walls(under))
    _, over, = garage(wwr: 0.41)
    assert_equal(1, PERIM.glazed_perimeter_walls(over).size)
  end

  # The band is a fixed 6.1 m from the wall — NOT the head-height-derived band
  # that DaylightedAreas builds for 4.2.2.3.
  def test_the_band_is_6_1_m_deep_and_clipped_to_the_floor
    _, space, = garage(width: 20.0, depth: 15.0, wwr: 0.5)
    band = PERIM.qualifying_band_area(space)
    assert_in_delta(20.0 * 6.1, band[:area_m2], 0.5, 'one 20 m wall x 6.1 m')
  end

  # A shallower garage than the band depth must not report more band than floor.
  def test_the_band_cannot_exceed_the_floor_it_is_clipped_to
    _, space, = garage(width: 20.0, depth: 4.0, wwr: 0.5)
    band = PERIM.qualifying_band_area(space)
    assert_operator(band[:area_m2], :<=, space.floorArea + 0.5)
  end

  def test_power_at_or_below_150_w_needs_no_daylight_response
    model, space, st = garage(width: 20.0, depth: 15.0, wwr: 0.5)
    light(st, 1.0)   # 1 W/m2 x ~122 m2 band = ~122 W
    log = audit
    SG.apply(model, audit: log)
    e = entry(log, '4.2.2.2.(4)')
    assert_match(/does not require a daylight response/, e[:action])
    assert(space.thermalZone.get.primaryDaylightingControl.empty?)
  end

  def test_power_above_150_w_gets_a_daylight_control
    model, space, st = garage(width: 20.0, depth: 15.0, wwr: 0.5)
    light(st, 5.0)   # ~610 W in the band
    log = audit
    SG.apply(model, audit: log)
    e = entry(log, '4.2.2.2.(4)')
    assert_equal(:decision, e[:level])
    assert(space.thermalZone.get.primaryDaylightingControl.is_initialized,
           'the sentence requires an automatic daylight response')
    assert_operator(e[:inputs][:luminaire_power_w], :>, 150.0)
  end

  # Daylighting.add_controls skips a zone that already has a primary control, so
  # the precedence must be stated rather than left to pass ordering.
  def test_an_existing_primary_control_is_not_duplicated
    model, space, st = garage(width: 20.0, depth: 15.0, wwr: 0.5)
    light(st, 5.0)
    existing = OpenStudio::Model::DaylightingControl.new(model)
    existing.setSpace(space)
    space.thermalZone.get.setPrimaryDaylightingControl(existing)
    log = audit
    SG.apply(model, audit: log)
    assert_match(/already carries a primary daylighting control/, entry(log, '4.2.2.2.(4)')[:action])
  end

  def test_an_unglazed_garage_is_outside_sentence_four
    model, = garage(wwr: 0.0)
    log = audit
    SG.apply(model, audit: log)
    assert_match(/no storage-garage space has a perimeter wall/, entry(log, '4.2.2.2.(4)')[:action])
  end

  # --- (3) and (5): declared, not guessed --------------------------------

  def test_entrances_are_declared_when_the_modeller_has_not_named_them
    model, = garage
    log = audit
    SG.apply(model, audit: log)
    e = entry(log, '4.2.2.2.(3)')
    assert_equal(:info, e[:level])
    assert_match(/requires identification by the modeller/, e[:action])
  end

  def test_exemptions_are_declared_every_run
    model, = garage
    log = audit
    SG.apply(model, audit: log)
    e = entry(log, '4.2.2.2.(5)')
    assert_match(/DAYLIGHT TRANSITION ZONES and RAMPS WITHOUT PARKING/, e[:action])
  end

  # --- the citation bug --------------------------------------------------

  # The general occupancy-sensor path used to tag itself 4.2.2.2., which made the
  # storage-garage manifest entry report citations it never earned.
  def test_the_general_occupancy_path_no_longer_claims_this_article
    source = File.read(File.expand_path('../lib/btap_necb/lighting/apply_lights.rb', __dir__),
                       encoding: 'UTF-8')
    refute_match(/article: '4\.2\.2\.2\./, source,
                 'apply_lights must not cite 4.2.2.2 — that is the storage-garage article')
  end
end
