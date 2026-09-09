"""btap.codes.necb — the NECB code family (National Energy Code of Canada for
Buildings, 2020 and 2025).

The five rule domains (loads, lighting, shw, envelope, hvac) live here and
compose btap.modeling's authoring machinery and btap.costing into the Part 8
determination driven from ``btap.codes.compliance``. Import domains directly
(``from btap.codes.necb import loads``).

``editions/`` holds the modules that belong to one edition only —
``editions/necb2025/`` today.

**Data lives by EDITION, code by DOMAIN** (multi-edition plan, Stage 3). Every
file an edition needs sits under ``data/<code id>/`` and nothing at runtime
reads another edition's files: no ``extends``, no alias, no fallback rung. Two
editions whose tables agree ship two byte-identical copies, because "identical
today" is a verified finding about two snapshots, not a dependency between
them. Removing an edition is ``git rm -r`` of one directory.

::

    data/necb2020/
        manifest.json               the edition's identity, rule map and tables
        necb_rules.json  envelope_rules.json  reference_rules.json
        efficiencies.json  lighting_rules.json  loads_rules.json  shw_rules.json
        tables/                     the transcribed code tables
        coverage/articles_8_4.json  the packaged Section 8.4 article text

Every loader in the family resolves its path through :func:`_data_root` **at
call time**, and every cache is keyed by the root it was filled from, so a test
can point the family at a temporary tree holding one edition and prove nothing
reaches outside it. The hook is :func:`_set_data_root`, which is test-only on
purpose: an environment variable would let a deployed run silently replace
adjudicated package data.
"""

from __future__ import annotations

from pathlib import Path

#: Where the packaged per-edition snapshots live. The code-family-neutral data
#: (the decisions registry, the Section 8.4 disposition and attribution) lives
#: in ``btap.codes.DATA_DIR`` instead.
DEFAULT_DATA_ROOT = Path(__file__).parent / "data"

_DATA_ROOT: Path | None = None


def _data_root() -> Path:
    """The directory holding one subdirectory per NECB edition.

    Call this inside the loader, never at import time: a test that swaps the
    root after import must be seen by every subsequent load.
    """
    return DEFAULT_DATA_ROOT if _DATA_ROOT is None else _DATA_ROOT


def _set_data_root(path: Path | None, *, _testing: bool = False) -> None:
    """TEST-ONLY: point the family at ``path`` instead of the packaged data.

    ``None`` restores the packaged default. Deliberately NOT an environment
    variable and deliberately guarded: a production override would let a
    deployed run silently substitute unadjudicated rule data for the packaged
    tables an AHJ report is built on.

    :raises RuntimeError: unless ``_testing=True`` is passed explicitly.
    """
    if not _testing:
        raise RuntimeError(
            "btap.codes.necb._set_data_root is a TEST-ONLY hook — pass "
            "_testing=True to acknowledge that. There is no production data-root "
            "override (and no environment variable): a deployed run must read "
            "the adjudicated packaged tables."
        )
    global _DATA_ROOT
    _DATA_ROOT = None if path is None else Path(path)


def code_id(vintage) -> str:
    """The code id for an NECB edition ('2025' -> 'necb2025').

    TRANSITIONAL alongside ``vintage``; Stage 7 of the multi-edition plan makes
    the id the parameter the public API takes.
    """
    return f"necb{vintage}"


def edition_file(vintage, *parts: str) -> Path:
    """One file inside one edition's snapshot, or a loud error.

    :param vintage: the NECB edition ('2020', '2025')
    :param parts: the path inside the snapshot ('tables', 'schedules.json')
    :raises ValueError: naming BOTH the edition and the path it wanted. Never a
        fallback to another edition — that is the defect this layout removes.
    """
    edition_id = code_id(vintage)
    path = _data_root().joinpath(edition_id, *parts)
    if not path.exists():
        raise ValueError(
            f"NECB edition '{edition_id}' has no {'/'.join(parts)} — expected "
            f"{path}. Every edition is a complete, independent snapshot; no "
            f"other edition's copy is substituted."
        )
    return path
