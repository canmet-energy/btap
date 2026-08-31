# The R5 release checklist (D-83)

The path to `pip install canmet-btap[tbd]` on PyPI and the v0.2.1 Python
Windows installer. Owner of each step in CAPS.

## Published already — nothing to redo

Three of the four distributions are LIVE on PyPI, each promoted
same-bytes (sha256 identical on TestPyPI and PyPI), each published from
its OWN repository:

| Distribution | Version | Repository |
|---|---|---|
| py-topolys | 0.1.0 | canmet-energy/py-topolys |
| canmet-tbd | 3.5.2 | canmet-energy/py-tbd |
| canmet-energyplus | 25.2.0.2 | canmet-energy/canmet-energyplus |

Provenance sentences for release notes:

- py-topolys 0.1.0 IS commit 36470305 (the D-79 Option A pin).
- canmet-tbd 3.5.2 IS the pinned verification tree bfb23e6 plus one
  diff-proven dependency-metadata commit; baseline: upstream Ruby TBD
  3.5.2 (95156a92) / OSut 0.8.2 oracle triplet. Published as
  `canmet-tbd` because PyPI's similarity check refused `py-tbd`.
- canmet-energyplus 25.2.0.2 carries the sha256-verified official NREL
  EnergyPlus 25.2.0 asset, pruned of the PythonPlugin host,
  Documentation, ExampleFiles and PreProcess; the manylinux tag is
  earned by an auditwheel grade on the finished wheel.

**Names, learned the expensive way.** PyPI's similarity check refused
`btap` and `py-tbd`; PyPI has no rename, and a published filename can
NEVER be reused, on either index. `canmet-btap 0.2.0` was consumed by a
TestPyPI rehearsal, so **the release is 0.2.1**. Never use
`skip-existing: true` to get past a name clash: the upload goes green
and the verify step then installs a STALE wheel.

**One project per repository.** A trusted-publishing exchange mints a
token for ONE project and resolves the run's claims against every
registered publisher, so two projects sharing a repo+workflow collide.
That is why canmet-energyplus moved out, and why every publisher here is
registered with an EXPLICIT environment rather than "(Any)".

## What remains

### USER — one-time, both indexes

Register `canmet-btap`: repo `canmet-energy/btap`, workflow
`publish.yml`, environment `testpypi` on test.pypi.org and `pypi` on
pypi.org. Keep `pypi` protected by required approval.

### PR-B (this repo) — consume the published engine

Done in this PR: the companion pin flips to `canmet-energyplus==25.2.0.2`
from the index; wheel_smoke's companion checks and H-6 stop depending on
a local wheelhouse and gate on a COMPUTED platform predicate instead;
the two repositories' EnergyPlus identity is cross-checked in the one
environment with a real installed companion; version 0.2.1.

### PR-4 — the Windows installer succession

`stage_python.py` (embedded CPython 3.12 embeddable zip, sha-pinned;
`python312._pth` + site-packages via cross-platform pip; record the
exact openstudio cp312 wheel filename+digest); launcher rewrite; iss
AppVersion 0.2.1; README-windows licence rewrite + generated
third-party licence inventory (**HUMAN LEGAL REVIEW** before release —
the installer redistributes CPython, OpenStudio, EnergyPlus and the tbd
chain); `release_guards.py`; standalone `installer_smoke.py`
(windows-latest, checkout absent); release.yml rewrite (no nrel
container; DRY_RUN kept); Rakefile `windows:*` dormancy
(`BTAP_RUBY_INSTALLER=1`, R6 deletes).

### PR-5 — docs + THE RELEASE

README: `pip install canmet-btap[tbd]` as the product; the promise
scoped to "Windows x86-64 and glibc-2.35+ Linux x86-64"; musl and older
glibc fail resolution BY DESIGN with the tested escape procedure; macOS
falls to the NREL-download rung. Then dispatch `publish.yml` with
`mode: publish`, approve the two gates, tag `v0.2.1`, and accept on a
clean Windows machine plus the ubuntu:22.04 (glibc-2.35 floor)
container: `pip install canmet-btap[tbd]`, sizing + annual runs with NO
environment variables — the goal sentence, executed and logged here.
