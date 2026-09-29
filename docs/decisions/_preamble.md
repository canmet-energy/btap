# canmet-btap NECB — decision record

> **This file is GENERATED. Do not edit it.** The canonical source of every
> decision is `docs/decisions/D-NN.md`. See **Maintenance** below.

Adjudicated interpretations and product decisions for the `canmet-btap` NECB
implementation (`btap.codes.necb`). The five `btap-*` Ruby gems this record
began under retired at R6 (D-84), and the package was renamed at D-86; entries
written before those points keep their period wording. Machine-checkable
coverage lives elsewhere — article dispositions in
`python/btap/codes/data/coverage/necb_8_4_disposition.json`, per-domain
`article_coverage` manifests, the
generated `NECB_8_4_COVERAGE.html`, and the evidence rules in
`docs/necb_rule_verification.md`. **This file records the judgement calls**: the
code-interpretation and design decisions a reviewer cannot re-derive from the
code alone, who made them, and why. Entries are in numeric id order. Add an
entry whenever an interpretation of code text is adopted, a deviation is
accepted, or a product-shaping call is made.

Format per entry: **what was decided / who / when / why / evidence & commit**.

**Maintenance (D-44, D-81, D-84):** one decision is one file,
`docs/decisions/D-NN.md`, and that file is CANONICAL. It carries TOML front
matter — `id`, `title`, `kind`, `articles`, `summary` — followed by the
authored Markdown body, whose first line is the section's own `## D-NN —`
heading. Two artifacts are generated from those sources and are never
hand-edited: this document, and the runtime registry
`python/btap/codes/data/decisions.json`. The full editing workflow for a
decision: (1) add or edit the one source file; (2) run `python3
python/scripts/generate_decisions.py`; (3) run the Python registry/citation
tests. `python3 python/scripts/generate_decisions.py --check` is the drift gate
and runs in CI. The front-matter `title` is the compact title this index and
the runtime registry carry; the body's heading is authored prose and the two
deliberately differ for most decisions. Anchors and this index are inserted by
the generator, so a source body never declares its own `d-NN` anchor. A
`kind: "runtime"` entry must be cited by at least one Python `ruling:` tag.
Registry summaries are PARAPHRASE — never NECB text verbatim (D-01 scopes
verbatim reproduction to the generated coverage docs).

**Live registers:** D (decisions, here) and L (legacy findings,
`legacy_findings.md`). The A/T registers of the 2026-07-25 reference-systems
audit are drained and archived — see `docs/README.md`.

---
