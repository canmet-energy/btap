Sample models — 16 files, one building
==============================================================

The same 5-zone office (a DOE prototype, so it carries real constructions) in
every file. Only the mechanical system changes, so the compliance verdict moves
with the HVAC rather than with the building.

All are tagged with NECB space types already, so no --space-type is needed:

  necb-compliance samples\01-baseboard-gas.osm --city toronto --quick

Drop --quick for a real 8.4.1.2 determination (40-90 min, four simulations).
--quick shortens the run to a week and the tool refuses to call that a verdict.

SYSTEMS — one per catalog family, spanning fuels and delivery types
--------------------------------------------------------------
  01-baseboard-gas                     Baseboard gas boiler
  02-psz-gas-dx                        PSZ RTU Gas and DX Coils and Hot Water Baseboard
  03-vav-reheat-chiller                MZ BU RTU Electric Heating Coil Scroll Chiller and Electric Baseboard
  04-fancoil-chiller                   FPFC MAU DX Coils with Scroll Chiller
  05-ptac-electric                     PTAC with baseboard electric
  06-unit-heaters-gas                  Gas unit heaters
  07-furnace-forced-air                Forced air furnace
  08-vrf                               VRF
  09-water-source-hp                   Water source heat pumps
  10-ashp-pthp                         hs11_ashp_pthp

REFERENCE-LOGIC CASES — these make the NECB rules visibly do something
--------------------------------------------------------------
Run each with --simulate none first and read audit.txt; the interesting part is
the decision, not the energy number.

  11-staged-boilers-gas-lead
    system: staged boilers: NaturalGas lead, Electricity second stage
    tests:  8.4.4.9.(5)/8.4.4.10.(4) multi-energy capacity ratios (a DECLARED gap: the reference keeps the mixed-fuel plant unchanged)

  12-staged-boilers-electric-lead
    system: staged boilers: Electricity lead, NaturalGas second stage
    tests:  8.4.4.9.(5)/8.4.4.10.(4) multi-energy capacity ratios (a DECLARED gap: the reference keeps the mixed-fuel plant unchanged)

  13-district-heating
    system: DOAS with fan coil air-cooled chiller with district hot water
    tests:  8.4.4.6.(1)(a) — purchased heating: the reference grows a gas-fired boiler where the proposed has none. MUST be a single-group system: with several single-zone groups the district loop survives the per-group teardown and is adopted by name, so the article is only half-applied.

  14-general-2storey
    system: Baseboard gas boiler
    tests:  Table 8.4.4.7.-A — General Area at 2 storeys selects reference System 3. Pairs with 15; one sample cannot show a flip.

  15-general-3storey
    system: Baseboard gas boiler
    tests:  Table 8.4.4.7.-A — the same building at 3 storeys crosses the threshold and selects System 6 instead.

  16-ashp-electric-supp-hw-baseboard
    system: PSZ RTU ASHP with Electric and ASHP with Electric Supp. Heat Coils and Hot Water Baseboard
    tests:  8.4.4.13.(2)(g) / D-52 — the auxiliary-fuel election. Needs --simulate annual: under :none it cannot run and the structural 8.4.4.9.(4) proxy answers instead. Proof that it RAN is the (g)(i) suffix on the article and the ELECTED wording, not the answer itself — this building delivers more gas (baseboard) than electric (supp coil), so the election and the proxy happen to agree on gas. A mixed-fuel heat pump is required for the election to be reachable at all; on an all-electric one there is nothing to elect between.

