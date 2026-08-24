require 'openstudio'

# The authoring half (catalog, builder, systems, components, classify,
# teardown) lives in btap-modeling now; this gem keeps the NECB rules and
# costing that consume it, plus back-compat constant aliases below.
begin
  require 'btap_modeling'
rescue LoadError
  require File.expand_path('../../btap-modeling/lib/btap_modeling', __dir__)
end

require_relative 'openstudio_hvac/version'
require_relative 'openstudio_hvac/audit_log'
require_relative 'openstudio_hvac/costing/database'
require_relative 'openstudio_hvac/costing/ledger'
require_relative 'openstudio_hvac/costing/geometry'
require_relative 'openstudio_hvac/costing/quantify_equipment'
require_relative 'openstudio_hvac/costing/ventilation'
require_relative 'openstudio_hvac/costing/report'
require_relative 'openstudio_hvac/necb/audit_log'
require_relative 'openstudio_hvac/necb/reference'
require_relative 'openstudio_hvac/necb/energy_recovery'
require_relative 'openstudio_hvac/necb/efficiency'
require_relative 'openstudio_hvac/necb/checker'

# OpenStudioHVAC builds HVAC system topologies on OpenStudio thermal zones by
# descriptive, fuel-encoding system name. Topology only — sizing runs and code
# efficiency application are the host application's job.
module OpenStudioHVAC
  # The authoring machinery moved to BtapModeling. These aliases keep this
  # gem's remaining NECB/costing code (and external callers) working until it
  # folds into btap-necb, where references become fully qualified.
  Catalog       = BtapModeling::Catalog
  Builder       = BtapModeling::Builder
  Classify      = BtapModeling::Classify
  Teardown      = BtapModeling::Teardown
  Naming        = BtapModeling::Naming
  Canonical     = BtapModeling::Canonical
  Validation    = BtapModeling::Validation
  Coils         = BtapModeling::Coils
  Curves        = BtapModeling::Curves
  Schedules     = BtapModeling::Schedules
  Systems       = BtapModeling::Systems
  EcmAir        = BtapModeling::EcmAir
  CatalogReport = BtapModeling::CatalogReport

  # List the system catalog (MCP/tool-friendly: names are a closed, validated vocabulary).
  #
  # @param filter [String, Regexp, nil] name filter
  # @param family [String, nil] family filter
  # @return [Array<Hash>]
  def self.systems(**kwargs) = BtapModeling.systems(**kwargs)

  # Build a system by descriptive name. See Builder.build_system.
  def self.build_system(...) = BtapModeling.build_system(...)

  # Zone-scoped teardown. See Teardown.remove_hvac_from_zones.
  def self.remove_hvac_from_zones(...) = BtapModeling.remove_hvac_from_zones(...)

  # HVAC capital costing on a SIZED model. See Costing.cost.
  def self.cost(model, **kwargs)
    Costing.cost(model, **kwargs)
  end

  # Characterize ANY model's HVAC into a neutral, serializable facts hash
  # (zone groups, energy types, heat pumps, purchased energy, plants).
  # See Classify.characterize.
  #
  # @param model [OpenStudio::Model::Model]
  # @param audit [NECB::AuditLog, nil] records evidence for every conclusion
  # @return [Hash] the facts schema
  def self.characterize(model, audit: nil) = BtapModeling.characterize(model, audit: audit)

  # Replace whatever HVAC currently serves these zones with a catalog system
  # (zone-scoped teardown + build_system).
  def self.replace_system(...) = BtapModeling.replace_system(...)

  # Render a self-contained HTML catalog of EVERY buildable system. Each system
  # is actually built on the bundled fixture and its real topology extracted, so
  # the inline-SVG loop diagrams cannot drift from what the gem assembles. See
  # CatalogReport.to_html.
  #
  # @param path [String, nil] if given, the HTML is also written here
  # @return [String] the self-contained HTML document
  def self.catalog_html(...) = BtapModeling.catalog_html(...)

  # Reusable OpenStudio-App-style HVAC loop diagrams for ANY model, as a plain
  # hash of inline-SVG strings — so a host report can draw the same diagrams the
  # catalog draws for its own models. Never raises. The host must also embed
  # {hvac_icon_defs} ONCE per document and add
  # OpenStudioHVAC::CatalogReport::DIAGRAM_CSS to its stylesheet so the diagrams'
  # icon <use> refs resolve and they size correctly. See
  # CatalogReport.model_diagrams.
  #
  # @param model [OpenStudio::Model::Model]
  # @return [Hash] { loops: [{ kind:, label:, svg: }...], zone_equipment_svg:, empty: }
  def self.model_hvac_diagrams(...) = BtapModeling.model_hvac_diagrams(...)

  # The hidden master <svg><defs> embedding every component icon ONCE. Emit this
  # ONCE per host HTML document so the diagrams' <use href="#icon-…"> refs
  # resolve. Self-contained (base64 PNG data-URIs, no external requests).
  def self.hvac_icon_defs = BtapModeling.hvac_icon_defs
end
