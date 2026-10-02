# Copilot instructions

Read [CLAUDE.md](../CLAUDE.md) first. It is the repository guide, and its
package contract, commands and traps apply to every agent working here.

## One heavy job at a time

This rule is mandatory, and it matters most when tool calls run without
approval. On 2026-09-08 three concurrent test suites plus two EnergyPlus
runs exhausted the 32 GB WSL2 VM and took it down.

A heavy job is any of these:

- a full or broad `pytest` run (`tests/`, or any run with `-n`);
- an EnergyPlus simulation, an annual or `--simulate` compliance run, or
  `btap-compliance` on a model;
- `verification/scenarios/freeze.py` or a frozen-scenario lane;
- a parity / oracle run (`legacy_pin`, `verification/oracle/`).

Rules:

1. Run at most **one** heavy job at a time. Before starting one, check that
   none is already running (`ps aux | grep -E 'pytest|energyplus|freeze.py'`),
   including runs started by another agent or terminal.
2. Never start a heavy job in the background and then start another.
3. Use `-n auto` or a smaller explicit count, never a larger one, and never
   override `PYTEST_XDIST_AUTO_NUM_WORKERS` (the devcontainer sets it to 8).
   Every xdist worker loads the OpenStudio SDK.
4. Run simulations one at a time.
5. Prefer targeted tests (one file or `-k` expression) while iterating; run
   the full suite once, at the end.
