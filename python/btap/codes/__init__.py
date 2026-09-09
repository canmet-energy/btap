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

Vintages are '2020' and '2025' only. Import domains directly
(``from btap.codes.necb import loads``). The umbrella pipeline is
``performance_compliance`` (M6); the CLI is ``btap.codes.cli`` (console
script ``btap-compliance``).

This module is also the **ruleset registry** (multi-edition plan, Stage 2).
One :class:`Ruleset` per edition, discovered from the per-edition manifests at
``btap/codes/<family>/data/<code id>/manifest.json``: every edition-specific
article number a rule cites comes from :meth:`Ruleset.article`, which raises
rather than falling back, so an edition that forgets a key fails loudly
instead of emitting another edition's citation into an AHJ report.

Three edition lists exist deliberately and must stay separate:

* :func:`editions` — "has a manifest here". Backs the CLI's ``--vintage``
  choices.
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

    def behaviour(self, name: str) -> Any:
        """The edition-specific implementation registered under ``name``.

        STAGE 5 of the multi-edition plan binds these through the manifest.
        Until then this always returns ``None`` — "this edition registers no
        override" — which is the answer for both editions today.
        """
        return None

    def rules(self, domain: str) -> dict:
        """The rule tables for one domain ('hvac', 'envelope', …).

        STAGE 6 of the multi-edition plan moves the per-edition rule files
        under this edition's directory and makes this the single loader.
        Until then the domains load their own tables and this raises.
        """
        raise NotImplementedError(
            "Ruleset.rules() lands in Stage 6 of the multi-edition plan; "
            f"load {self.family} {domain} rules through the domain module "
            "until then"
        )

    @classmethod
    def from_edition(cls, edition: str) -> "Ruleset":
        """TRANSITIONAL — the NECB edition ('2020'/'2025') as the ``vintage``
        parameter still carries it.

        Deleted in Stage 7 together with ``vintage``, when the public API takes
        a code id. New code should call :func:`resolve` with a full id.
        """
        return resolve(f"necb{edition}")


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
    return Ruleset(
        id=data["id"],
        family=data["family"],
        edition=data["edition"],
        label=data["label"],
        articles=MappingProxyType(dict(data.get("articles") or {})),
        literal_remaps=MappingProxyType(dict(data.get("literal_remaps") or {})),
    )


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

    This is the list the CLI offers as ``--vintage`` choices. It is NOT
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
