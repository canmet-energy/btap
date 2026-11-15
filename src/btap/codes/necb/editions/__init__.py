"""Edition-specific NECB modules.

Everything under ``btap.codes.necb`` applies to every supported edition unless
it sits here. One subpackage per edition (``necb2025`` today).

Nothing here is imported by name from the pipeline: each module is BOUND
through its edition's ``manifest.json`` ``behaviours`` map and reached through
:meth:`btap.codes.Ruleset.behaviour`, so an edition that binds nothing simply
has no such feature (multi-edition plan, Stage 5). When a later edition comes
to share one of these implementations, promote the module into the shared tree
and point both manifests at it — that promotion needs a D-XX entry; see
``btap/codes/necb/data/README.md``.
"""
