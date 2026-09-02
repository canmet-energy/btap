NECB Compliance - Windows
=========================

What it does
------------
Runs the NECB Part 8 performance path on an OpenStudio model: simulates the
proposed building, generates and simulates the reference building, and reports
the Article 8.4.1.2 determination with a self-contained HTML report.

Nothing else needs to be installed. The package carries CPython 3.12 and the
pinned OpenStudio 3.11.0, EnergyPlus 25.2.0, and canmet-btap wheels.

It installs PER-USER and needs no administrator rights, so there is no UAC
prompt and it works on a locked-down machine. Everything lives under one
directory; nothing is written to system folders or the registry.

Quick start
-----------
  1. Open the "NECB Compliance (console)" shortcut in the Start menu.
  2. Run:  btap-compliance samples\5ZoneNoHVAC.osm --epw weather\<file>.epw
Or double-click  samples\run-demo.cmd  for a worked example.

  btap-compliance --help    lists every option.

Exit codes
----------
  0  compliant
  1  NOT compliant          - a verdict, not an error
  2  usage or input error   - bad flag, missing file
  3  model rejected         - see "Space types" below
  4  simulation failure     - EnergyPlus reported a severe/fatal error
  5  internal error
  6  no determination made  - --quick, or --simulate sizing|none

Space types - READ THIS if you get exit 3
-----------------------------------------
The reference building can only be generated when every space type resolves
against the NECB catalog. Models produced by BTAP or openstudio-standards
already carry the right tags. Models built by hand in the OpenStudio
Application usually do not, and will be refused BEFORE any simulation runs -
the error names each unresolved type and suggests catalog names.

Two ways to fix it:
  * tag the model: set standardsBuildingType + standardsSpaceType on each
    space type to NECB catalog names; or
  * use the on-ramp for a uniform building:
      --space-type "Space Function/Office enclosed > 25 m2"
    or, per space, a JSON file:
      --space-type-map mymap.json
    where mymap.json is {"Space 101": ["Space Function", "Office enclosed > 25 m2"]}

This tool checks a model against the code. It does not make an arbitrary model
compliance-ready.

How long it takes
-----------------
A real determination runs four EnergyPlus simulations (proposed sizing and
annual, reference sizing and annual), and up to three more if the 8.4.1.2.(5)
capacity loop iterates. Budget 40-90 minutes for a small building. Progress is
printed as each phase starts.

--quick shortens the run to one week so you can see the pipeline work in
minutes. It is NOT a code-compliant determination and the tool refuses to
report a verdict for it.

Costing
-------
Costing is off by default. The priced RS-Means-derived tables are NOT included
in this package - point --costs-csv at your own licensed table to enable it.

Licences
--------
The regimes are deliberately kept separate:

  LICENSE                 canmet-btap source - LGPL-3.0-or-later.
  THIRD-PARTY-NOTICES.txt CPython and every installed wheel, with the path to
                          each redistributed licence text under
                          python\Lib\site-packages or licenses\.
