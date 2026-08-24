require_relative 'lib/btap_modeling/version'

Gem::Specification.new do |spec|
  spec.name = 'btap-modeling'
  spec.version = BtapModeling::VERSION
  spec.authors = ['NRCan / openstudio-standards contributors']
  spec.summary = 'Parametric building geometry wizards for OpenStudio models (SDK-only)'
  spec.description = 'Footprint wizards (rectangle, aspect-ratio, courtyard, H, L, T, U) with ' \
                     'perimeter/core zoning, below-grade storeys and matched surfaces — the ' \
                     'authoring on-ramp for the openstudio-* NECB gem family.'
  spec.homepage = 'https://github.com/canmet-energy/btap-gems'
  spec.metadata = {
    # These gems are not published: the repository is private and the costing
    # data is licence-encumbered. Publishing is a deliberate act — clear this
    # entry consciously, do not let a stray `gem push` make the decision.
    'allowed_push_host' => 'none',
    'source_code_uri' => 'https://github.com/canmet-energy/btap-gems',
    'homepage_uri' => 'https://github.com/canmet-energy/btap-gems'
  }
  spec.license = 'LGPL-3.0-or-later'
  spec.required_ruby_version = '>= 3.2'
  spec.files = Dir['lib/**/*', 'README.md', 'LICENSE*']
  spec.require_paths = ['lib']

  spec.add_dependency 'btap-audit', '~> 0.2'
end
