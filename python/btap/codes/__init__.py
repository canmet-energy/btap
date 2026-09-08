"""btap.codes — the code-compliance layer (port of the btap-necb gem).

One subpackage per code family: ``btap.codes.necb`` holds every NECB 2020/2025
Part 8 rule as five domains (loads, lighting, shw, envelope, hvac), which
compose btap.modeling's authoring machinery and btap.costing into the full
Part 8 determination driven from ``compliance`` here. This is the ONLY package
allowed to run EnergyPlus (through btap.simulation) — the domains are SDK-only.

``data/`` here is deliberately code-family-NEUTRAL: the decisions registry, and
the Section 8.4 disposition and attribution that speak for the family as a
whole rather than for one edition. Everything an edition owns — its rule files,
its transcribed tables and its Section 8.4 article text — lives in that
edition's own snapshot under ``btap/codes/necb/data/<code id>/`` (Stage 3).

Two citation axes run through every audit entry here (D-44): ``article``
cites the code that mandates a value; ``ruling`` cites the adjudicated
decision (D-XX) recording how we read it. Audit text convention: violations
SHOUTED, passes lowercase — the report's checklist classifier is
deliberately case-SENSITIVE.

Editions are '2020' and '2025' only. Import domains directly
(``from btap.codes.necb import loads``). The umbrella pipeline is
``performance_compliance`` (M6); the CLI is ``btap.codes.cli`` (console
script ``btap-compliance``).

This module is also the **ruleset registry** (multi-edition plan, Stage 2).
One :class:`Ruleset` per edition, discovered from the per-edition manifests at
``btap/codes/<family>/data/<code id>/manifest.json``: every edition-specific
article number a rule cites comes from :meth:`Ruleset.article`, which raises
rather than falling back, so an edition that forgets a key fails loudly
instead of emitting another edition's citation into an AHJ report. The same
manifest binds this edition's own CODE (Stage 5): :meth:`Ruleset.behaviour`
resolves a behaviour name to the module implementing it here, or ``None``
when this edition has no such feature — which is what replaced the
``edition == "2025"`` tests in the pipeline.

Three edition lists exist deliberately and must stay separate:

* :func:`editions` — "has a manifest here". The editions of one family,
  as edition strings; the CLI selects with ``--code`` and :func:`code_ids`.
* :func:`btap.codes.coverage.editions` — "has packaged Section 8.4 article
  text". A different, narrower question; never redefine it in terms of this
  one.
* the frozen-scenario corpus's own code list in ``verification/scenarios``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

DATA_DIR = Path(__file__).parent / "data"

#: The code families that register editions here, by family name. Each module
#: owns a ``_data_root()`` returning the directory that holds one subdirectory
#: per edition of that family, so a test can repoint one family's data without
#: the registry hardcoding a filesystem layout (multi-edition plan, Stage 3).
#: Stage 9 adds the second family by adding a line here.
_FAMILY_MODULES = {"necb": "btap.codes.necb"}

_REQUIRED_FIELDS = ("id", "family", "edition", "label")

#: Every behaviour name product code is allowed to ask an edition for
#: (multi-edition plan, Stage 5). Deliberately a CODE-side vocabulary rather
#: than "whatever the manifests on this disk happen to declare", because the
#: two answers a caller can get are different facts:
#:
#: * a name IN this set that an edition does not bind -> ``None``, "this
#:   edition has no such feature". A one-edition install (the removability
#:   gate ships exactly that) must still answer ``None`` for a behaviour some
#:   OTHER edition owns — deriving the vocabulary from the present manifests
#:   would turn that into a crash.
#: * a name NOT in this set -> ``KeyError``, "no such behaviour exists".
#:
#: ``tests/necb/test_behaviour_binding.py`` closes the loop in both
#: directions: every name here is bound by at least one manifest and asked
#: for by product code, and every manifest binding names one of these.
BEHAVIOURS = frozenset({"archetype_eui_path", "part11_ghg"})


class UnknownRuleset(KeyError, ValueError):
    """No edition is registered under the requested id (or family).

    Deliberately both a :class:`KeyError` (a failed lookup in the registry)
    and a :class:`ValueError` (a bad caller-supplied value), so code written
    against either reading catches it. ``KeyError.__str__`` would print the
    message's ``repr``, so it is overridden.
    """

    def __str__(self) -> str:
        return str(self.args[0]) if self.args else ""


@dataclass(frozen=True)
class Ruleset:
    """One code edition — the thing a determination is run against.

    Constructed from a manifest by :func:`resolve`; the dataclass itself is
    plain data so a test can build one without touching the disk.
    """

    id: str
    family: str
    edition: str
    label: str
    #: Edition-specific article numbers, by stable key. The keys name what the
    #: citing rule needs ("the reference subsection"), never the number itself,
    #: because the number is exactly what moves between editions.
    articles: Mapping[str, str] = field(default_factory=dict)
    #: How this edition renumbers article literals that source code writes in
    #: another edition's numbering (``{"8.4.4.": "8.4.5."}``). Empty when the
    #: edition needs no rewriting. Consumed by the Section 8.4 coverage
    #: scanner; product code cites through :meth:`article` instead.
    literal_remaps: Mapping[str, str] = field(default_factory=dict)

    def article(self, key: str) -> str:
        """This edition's number for the article registered under ``key``.

        Raises :class:`KeyError` on a missing key — NEVER a default. A default
        here is the original defect this registry exists to remove: a third
        edition silently emitting NECB 2020 article numbers.
        """
        try:
            return self.articles[key]
        except KeyError:
            raise KeyError(
                f"{self.id} declares no article key {key!r} — add it to "
                f"btap/codes/{self.family}/data/{self.id}/manifest.json "
                f"(it declares {sorted(self.articles)})"
            ) from None

    #: The edition-specific implementation modules this edition binds, by
    #: behaviour name (``{"part11_ghg": "btap.codes.necb.editions.necb2025.
    #: part11_ghg"}``). Empty when the edition owns no code of its own —
    #: which is the whole point: the pipeline asks for the behaviour and gets
    #: ``None``, instead of testing the edition's name.
    behaviours: Mapping[str, str] = field(default_factory=dict)

    def behaviour(self, name: str) -> Any:
        """The module this edition binds under ``name``, or ``None``.

        ``None`` means "this edition registers no such behaviour", and every
        call site treats that as "the feature does not exist here" — the 2025
        archetype-EUI path and the Part 11 GHG scoring are absent from 2020
        that way, with no edition literal anywhere in the pipeline.

        An unregistered ``name`` raises :class:`KeyError`: asking for a
        behaviour nobody implements is a typo, not an edition without it.
        """
        if name not in BEHAVIOURS:
            raise KeyError(
                f"unknown behaviour name {name!r} — the vocabulary is "
                f"{sorted(BEHAVIOURS)}. Add the name to btap.codes.BEHAVIOURS "
                "and bind it in at least one manifest; do not spell it "
                "differently at the call site."
            )
        dotted = self.behaviours.get(name)
        return None if dotted is None else _import_behaviour(dotted)

    def rules(self, domain: str) -> dict:
        """This edition's rule tables for one domain ('hvac', 'envelope', …).

        ``domain`` is a key of the manifest's ``rules`` map — ``umbrella``,
        ``envelope``, ``hvac``, ``hvac_efficiencies``, ``lighting``,
        ``loads``, ``shw``. The edition's manifest says which file each one
        lives in, so the file name is a per-edition fact rather than a
        constant baked into a domain module (multi-edition plan, Stage 6).

        The SAME memoized dict comes back every call — read it, never mutate
        it. A domain this edition does not declare, or a declared file that is
        absent, raises :class:`ValueError` naming the edition, the domain and
        the path: no other edition's rules are ever substituted.
        """
        return _rules_loader(self.family).load(domain, self.id)


def _read_manifest(path: Path) -> Ruleset:
    data = json.loads(path.read_text(encoding="utf-8"))
    missing = [name for name in _REQUIRED_FIELDS if not data.get(name)]
    if missing:
        raise ValueError(f"{path} is missing required field(s): {', '.join(missing)}")
    if data["id"] != path.parent.name:
        raise ValueError(
            f"{path} declares id {data['id']!r} but sits in "
            f"{path.parent.name!r} — the directory name IS the code id"
        )
    behaviours = dict(data.get("behaviours") or {})
    unknown = sorted(set(behaviours) - BEHAVIOURS)
    if unknown:
        raise ValueError(
            f"{path} binds unknown behaviour name(s) {unknown} — the "
            f"vocabulary is {sorted(BEHAVIOURS)}. A binding no call site can "
            "ask for is an orphan; add the name to btap.codes.BEHAVIOURS "
            "together with the code that resolves it."
        )
    return Ruleset(
        id=data["id"],
        family=data["family"],
        edition=data["edition"],
        label=data["label"],
        articles=MappingProxyType(dict(data.get("articles") or {})),
        literal_remaps=MappingProxyType(dict(data.get("literal_remaps") or {})),
        behaviours=MappingProxyType(behaviours),
    )


@lru_cache(maxsize=None)
def _import_behaviour(dotted: str):
    """The module a manifest binds, imported once per process.

    Cached HERE rather than on the :class:`Ruleset` so the dataclass stays
    frozen plain data: a determination resolves a behaviour on every phase
    that has one, and re-entering ``import_module`` each time would be the
    only cost of routing through the registry.
    """
    from importlib import import_module

    try:
        return import_module(dotted)
    except ImportError as exc:
        raise ImportError(
            f"a manifest binds the behaviour module {dotted!r}, which does not "
            f"import: {exc}"
        ) from exc


@lru_cache(maxsize=None)
def _rules_loader(family: str):
    """The module that loads one family's per-edition rule files.

    Resolved through the family table for the same reason :func:`_family_roots`
    is: Stage 9's second family adds a line to ``_FAMILY_MODULES``, not a
    branch here.
    """
    from importlib import import_module

    try:
        module = _FAMILY_MODULES[family]
    except KeyError:
        raise UnknownRuleset(
            f"no code family {family!r} is registered — known families: "
            f"{sorted(_FAMILY_MODULES)}"
        ) from None
    return import_module(f"{module}.rulesdata")


def _family_roots() -> tuple[tuple[str, Path], ...]:
    """(family, data root) for every registered family, resolved AT CALL TIME.

    Import-time resolution would freeze the packaged path into the module and
    make the test-only data-root hook a no-op for discovery.
    """
    from importlib import import_module

    return tuple(
        (family, import_module(module)._data_root())
        for family, module in sorted(_FAMILY_MODULES.items())
    )


@lru_cache(maxsize=None)
def _registry_for(roots: tuple[tuple[str, Path], ...]) -> Mapping[str, Ruleset]:
    """Every edition with a manifest under ``roots``, by code id.

    Cached on the roots, not on nothing: the citation sites resolve per call and
    a determination makes thousands of them, but a test that swaps a family's
    data root must not be served another root's registry.
    """
    rulesets: dict[str, Ruleset] = {}
    for family, root in roots:
        for path in sorted(root.glob("*/manifest.json")):
            ruleset = _read_manifest(path)
            if ruleset.family != family:
                raise ValueError(
                    f"{path} declares family {ruleset.family!r} but sits under "
                    f"the {family!r} family's data root {root}"
                )
            rulesets[ruleset.id] = ruleset
    if not rulesets:
        raise ValueError(
            "no edition manifests found under "
            f"{', '.join(f'{root}/*/manifest.json' for _family, root in roots)}"
            " — the packaged data went missing from the wheel"
        )
    return MappingProxyType(rulesets)


def _registry() -> Mapping[str, Ruleset]:
    """Every registered edition, by code id."""
    return _registry_for(_family_roots())


def code_ids() -> list[str]:
    """Every registered code id, sorted (``['necb2020', 'necb2025']``)."""
    return sorted(_registry())


def editions(family: str) -> list[str]:
    """The editions of one code family that HAVE a manifest here, sorted.

    The CLI offers :func:`code_ids` (full code ids) as its ``--code``
    choices; this is the edition-string view of the same registry, for the
    per-edition data accessors. It is NOT
    ``btap.codes.coverage.editions()``, which answers the narrower "has
    packaged Section 8.4 article text" — an edition may be a first-class
    ruleset long before its article text is cached.
    """
    found = sorted(rs.edition for rs in _registry().values() if rs.family == family)
    if not found:
        raise UnknownRuleset(
            f"no code family {family!r} is registered — known families: "
            f"{sorted({rs.family for rs in _registry().values()})}"
        )
    return found


def resolve(code_id: str) -> Ruleset:
    """The :class:`Ruleset` registered under ``code_id`` (e.g. ``necb2025``)."""
    try:
        return _registry()[code_id]
    except KeyError:
        raise UnknownRuleset(
            f"unknown code id {code_id!r} — registered ids are {code_ids()}. "
            "An edition becomes available by adding "
            "btap/codes/<family>/data/<code id>/manifest.json, not by "
            "widening a fallback."
        ) from None


def performance_compliance(model, **kwargs):
    """The NECB Part 8 performance-path pipeline — see
    :func:`btap.codes.compliance.performance_compliance`. Imported lazily so
    ``btap.codes`` stays importable without the SDK."""
    from btap.codes import compliance

    return compliance.performance_compliance(model, **kwargs)
