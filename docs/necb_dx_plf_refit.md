# Refitting the reference DX part-load curves — open work, not adopted

This is the study D-102 refers to and deliberately does not carry. The
polynomials shipped in `efficiencies.json` are NOT these; adopting a refit
moves reference energy results and so needs its own adjudication and its own
frozen-scenario re-freeze.

It lives here, with the script that produces it, because D-102's evidence was
corrected eight times in two days and roughly a third of the figures involved
described this unadopted work. A number nobody will act on still has to be
kept right, so the honest place for it is beside the code that regenerates it.

## Why a refit is on the table

Each curve's shipped polynomial was fitted over a range that is not its
representable set. The cooling curve's own note records a fit over PLR
0.25-1.0, while its representable region starts at its lower root — so part of
the domain it is judged on was never in the fit. The heating polynomial is
inherited from NECB 2011 Table 8.4.4.21.-E and was never fitted to these
editions' Article at all.

## Two candidate accounts, and why they differ

The heating curve's representable set is DISCONNECTED: a primary interval, then
an isolated point at full load (D-102 explains why). A single cubic cannot
serve both, so there are two defensible fitting sets and they are not
interchangeable:

- **Account 1** fits the primary interval only. The isolated point is then
  carried by the engine's output clamp rather than by the fit, and is exact as
  applied because the clamp lands on a target that is itself exactly the
  ceiling.
- **Account 2** includes the isolated point as one observation. Its
  coefficients differ, and its governing maximum is slightly worse at the
  lower end.

Both are exact at full load once the ceiling applies, so the full-load point
does not distinguish them; their maxima, both at the LOWER root, do.

## Regenerating the figures

```bash
python3 docs/scripts/necb_dx_plf_refit.py            # human-readable
python3 docs/scripts/necb_dx_plf_refit.py --json     # machine-readable
```

The script derives the roots, both accounts' coefficients, their maxima and
the sampling progression from the Article cubics and the shipped curves. **Run
it rather than quoting it.** The sampling density matters — the maxima move in
the third decimal between 200 and 100 000 intervals, and the ARGMAX's fourth
decimal is decided by where grid points fall rather than by convergence, which
is why D-102 publishes no location at all.

## What it would buy

Both curves improve materially over the shipped polynomials' as-applied
maxima, which D-102's evidence block states. The cooling improvement is the
larger of the two, because its fit range excluded part of its own region.

## What has to happen before adopting it

1. Choose Account 1 or Account 2 and record why, in a decision.
2. Re-fit, update `efficiencies.json` for BOTH editions, refresh the
   provenance hashes.
3. Re-freeze the frozen scenarios on a clean tree — this moves reference
   energy, so baselines WILL move, and the moves must be attributed.
4. Decide whether the modeling layer's second copy of these curves
   (`btap/modeling/hvac/data/curves.json`) is corrected in the same change;
   D-102 records it as a proposed-side bias and open work.
