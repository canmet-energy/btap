"""SDK-touching cross-cutting helpers.

Separate from ``_compat`` on purpose: ``_compat`` is stdlib-only so that
``btap.audit`` — which the family contract keeps SDK-free, and which CI
exercises on a bare runner with no OpenStudio — can depend on it. Anything
that needs ``import openstudio`` lives here instead, and the import-linter
contract enforces the split.
"""

from __future__ import annotations

_sdk_hash_patched = False


def ensure_sdk_hashable() -> None:
    """Make SDK model objects usable as dict keys (idempotent).

    The openstudio wheel's ModelObject/IdfObject define __eq__ (handle
    equality) WITHOUT __hash__, so Python marks them unhashable — but the
    ported code keys dicts by SpaceType/BuildingStory/ThermalZone exactly as
    the Ruby did. This patches a handle-based __hash__ consistent with the
    wheel's __eq__. Call it at the top of any module that keys a dict or set
    by SDK objects.
    """
    global _sdk_hash_patched
    if _sdk_hash_patched:
        return
    import openstudio

    def _handle_hash(self):
        return hash(str(self.handle()))

    openstudio.model.ModelObject.__hash__ = _handle_hash
    openstudio.IdfObject.__hash__ = _handle_hash
    _sdk_hash_patched = True
