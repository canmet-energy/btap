# The R5 release checklist (D-83)

The ordered, auditable path from here to `pip install canmet-btap[tbd]` on PyPI
and the v0.2.0 Python Windows installer. Owner of each step in CAPS.

## 0. Trusted-publisher setup — USER, one-time, web UI

On BOTH pypi.org and test.pypi.org (same steps each):

| Project | Repo | Workflow | Environment |
|---|---|---|---|
| py-topolys | canmet-energy/py-topolys | publish.yml | pypi / testpypi |
| canmet-tbd | canmet-energy/py-tbd | publish.yml | pypi / testpypi |
| canmet-btap | canmet-energy/btap | publish.yml | pypi / testpypi |
| btap-energyplus | canmet-energy/btap | publish.yml | pypi / testpypi |

Add each as a *pending trusted publisher* (Account → Publishing).
Distribution names: PyPI's similarity check blocked `btap` and `py-tbd`
(bta / pytbd / tbd exist), so the published names are `canmet-btap`
and `canmet-tbd`; the import names (`btap`, `tbd`) are unchanged.
PyPI caps PENDING publishers at 3 per account (per index); a pending
entry is consumed when the project's first upload creates it.
TWO PENDING PUBLISHERS FROM ONE REPO NEED DIFFERENT ENVIRONMENTS: PyPI
refuses a second pending entry whose (owner, repo, workflow, environment)
tuple already exists ("already been registered for a different project
name"). btap-energyplus holds the "(Any)" entry, so canmet-btap must name
its environment explicitly — `pypi` on pypi.org, `testpypi` on
test.pypi.org, matching the job each upload runs in. Both still match at
upload time ("(Any)" matches everything).
A trusted-publishing token is scoped to ONE project, so each
distribution needs its own upload invocation ("OIDC scoped token is not
valid for project"). publish.yml uploads the companion first, then the
library, from the same run's artifacts — one run, two exchanges, same
bytes. The companion leads so a size-cap refusal cannot leave the
library on the index without its engine. Sequence:
register py-topolys + btap-energyplus + canmet-tbd; publish py-topolys
(frees a slot on each index); then register canmet-btap; then publish
the rest in order. In
each GitHub repo: Settings → Environments → create `pypi` WITH a
required-reviewer protection rule (the promotion approval); `testpypi`
unprotected. File the PyPI file-size-limit request for `btap-energyplus`
(the Linux wheel is 156.4 MB) at github.com/pypi/support once the
project exists (first TestPyPI upload creates it).

## 1. Upstream publications — THEIR OWN REPOS, in order

1. **py-topolys**: dispatch `publish.yml` with tag `v0.1.0` (the tag
   sits at exactly the D-79 pinned SHA 36470305). TestPyPI stage runs
   automatically; approve the `pypi` environment to promote the SAME
   artifact. Release provenance: "0.1.0 IS commit 36470305".
2. **py-tbd**: after py-topolys is live on PyPI, dispatch `publish.yml`
   with tag `v3.5.2`. The workflow's diff guard proves the release is
   the pinned verification tree bfb23e6 plus exactly one
   dependency-metadata commit (e484597); its verify job installs from
   TestPyPI (canmet packages) + PyPI (third-party). Approve to promote.

## 2. This repository's publication — publish.yml (PR-3)

1. Rehearse machinery any time: dispatch `publish.yml` with
   `mode: build-only` — builds all four files once, digest-manifests,
   auditwheel-gates the Linux companion on the exact artifact, and runs
   the installed-pair REAL sizing on BOTH ubuntu and windows-latest
   with isolated caches (linux additionally proves the cache stayed
   EMPTY — the companion, not provisioning, supplied the engine).
2. After step 1 above is complete: dispatch with `mode: publish` — the
   SAME run's artifacts go to TestPyPI (with the dependency refusal
   gate: btap is refused while py-tbd 3.5.2 / py-topolys 0.1.0 are not
   on PyPI), the TestPyPI-alone canmet install is verified, then the
   protected `pypi` environment approval promotes the identical bytes.
   Production never re-invokes a builder.

## 3. Post-publication pin flips — ONE PR here

Replace the interim tag-sourced installs with plain index installs:
- `.github/workflows/test.yml`: the two py-topolys/py-tbd git-tag
  installs → `pip install "canmet-tbd==3.5.2"` (resolves py-topolys==0.1.0
  transitively from PyPI).
- `python/scripts/wheel_smoke.py`: drop the two tag-install lines (the
  `[tbd]` extra resolves from PyPI).
- Optionally drop the companion build+cache step once
  `btap-energyplus==25.2.0.1` is on PyPI (wheel_smoke can then resolve
  it from the index; keeping the wheelhouse build exercises the builder
  — decide in review).

## 4. PR-4 — the Windows installer succession

Per the R5 plan: `stage_python.py` (embedded CPython 3.12 embeddable
zip, sha-pinned; `python312._pth` + site-packages via cross-platform
pip; record the exact openstudio cp312 wheel filename+digest); launcher
rewrite; iss 0.2.0; README-windows licence rewrite + generated
third-party license inventory (HUMAN LEGAL REVIEW before release);
`release_guards.py`; standalone `installer_smoke.py` (windows-latest,
checkout absent); release.yml rewrite (no nrel container; DRY_RUN
kept); Rakefile `windows:*` dormancy (`BTAP_RUBY_INSTALLER=1`, R6
deletes).

## 5. PR-5 — docs + THE RELEASE

README: `pip install canmet-btap[tbd]` as the product; the promise scoped to
"Windows x86-64 and glibc-2.35+ Linux x86-64"; musl/older glibc fails
resolution BY DESIGN with the tested escape procedure; macOS = the
NREL-download rung. Then: tag `v0.2.0` (= `btap.__version__` = iss
AppVersion); release.yml ships `btap-compliance-setup-0.2.0.exe`;
acceptance = clean Windows machine + the ubuntu:22.04 (glibc-2.35
floor) container, `pip install canmet-btap[tbd]`, sizing + annual runs with
NO env vars — the goal sentence, executed and logged here.

## Provenance sentences (copy into release notes)

- py-topolys 0.1.0 IS commit 36470305 (the D-79 Option A pin).
- py-tbd 3.5.2 IS the pinned verification tree bfb23e6 plus one
  diff-proven dependency-metadata commit (e484597); baseline: upstream
  Ruby TBD 3.5.2 (95156a92) / OSut 0.8.2 oracle triplet.
- btap-energyplus 25.2.0.N carries the sha-verified NREL 25.2.0 asset,
  pruned of the PythonPlugin runtime only, libpython renamed+patchelf'd
  (PEP 600), manylinux tag EARNED by auditwheel on every build.
