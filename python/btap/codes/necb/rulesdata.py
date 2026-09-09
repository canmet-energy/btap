"""The ONE loader for every NECB edition's rule files (multi-edition plan,
Stage 6).

Before this module each domain owned a near-identical seven-line loader: its
own module-level dict, its own cache key, its own ``open(...json.load)``, and
— worst — its own idea of which file name that domain's rules live in. Six
copies of the same code is six places for a seventh edition to be wrong, and
the file name baked into the domain module is exactly the kind of per-edition
fact the manifest exists to own: :func:`load` asks the edition's manifest
which file its ``envelope`` rules are in, so an edition that renames or
splits a rule file changes its manifest and nothing else.

The domain accessors (``loads.rules``, ``lighting.rules``, ``envelope.rules``,
``hvac.reference.rules``, ``hvac.efficiency.data``, and ``shw.rules``)
stay as shims over this: their NAMES are
addresses — the Section 8.4 coverage ``code`` pointers and the removability
gate both call them — so the loader consolidates the mechanism without moving
the doorbell.

One cache, keyed by ``(data root, code id, domain)``. The data root is part of
the key for the same reason it is part of every other cache key in the family:
a test that repoints :func:`btap.codes.necb._set_data_root` at a one-edition
tree must never be served the packaged root's tables.

One error, from :func:`btap.codes.necb.edition_file`, naming the edition, the
domain and the path it wanted. There is NO fallback to another edition and no
default file name — a missing file is a missing snapshot, and answering it
with NECB 2020's rules is the defect the per-edition layout removed.
"""

from __future__ import annotations

import json

from btap.codes.necb import _data_root, edition_file

#: One cache for every domain of every edition, keyed by
#: ``(data root, code id, domain)``.
_CACHE: dict[tuple, dict] = {}


def load(domain: str, code_id: str) -> dict:
    """This edition's rule tables for one domain.

    :param domain: a key of the manifest's ``rules`` map — ``umbrella``,
        ``envelope``, ``hvac``, ``hvac_efficiencies``, ``lighting``,
        ``loads``, ``shw``.
    :param code_id: the edition's code id (``necb2020``).
    :return: the parsed rule file, memoized. The SAME dict object each call:
        callers read it and must not mutate it, exactly as they did when each
        domain memoized its own.
    :raises ValueError: naming the edition, the domain and the path, when the
        edition declares no such domain or the file it names is absent.
    """
    key = (_data_root(), str(code_id), str(domain))
    cached = _CACHE.get(key)
    if cached is not None:
        return cached

    edition = _edition_of(code_id)
    filename = _rule_file(domain, code_id, edition)
    path = edition_file(edition, filename)
    _CACHE[key] = json.loads(path.read_text(encoding="utf-8"))
    return _CACHE[key]


def _edition_of(code_id: str) -> str:
    """The edition string ``edition_file`` takes, from a full code id.

    The inverse of :func:`btap.codes.necb.code_id`. It goes through the
    registry rather than stripping the ``necb`` prefix so an id no edition
    declares fails in the registry's voice, with the registered ids listed.
    """
    from btap.codes import resolve

    return resolve(str(code_id)).edition


def _rule_file(domain: str, code_id: str, edition: str) -> str:
    """The file name this edition's manifest gives ``domain``'s rules."""
    manifest = json.loads(
        edition_file(edition, "manifest.json").read_text(encoding="utf-8")
    )
    rules = manifest.get("rules") or {}
    try:
        return rules[domain]
    except KeyError:
        raise ValueError(
            f"NECB edition '{code_id}' declares no {domain!r} rules — its "
            f"manifest's 'rules' map declares {sorted(rules)}. Every edition "
            f"is a complete, independent snapshot; no other edition's rules "
            f"are substituted."
        ) from None
