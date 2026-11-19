"""btap — the NECB 2020/2025 Part 8 performance path, one distribution.

Six subpackages keep a one-way dependency direction (D-77): codes -> costing
-> modeling -> audit, with simulation beside and stock a sibling of codes.
Import subpackages directly (``from btap.audit import AuditLog``); this root
deliberately imports none of them, so ``import btap`` never pulls the SDK.
Each subpackage's ``__all__`` is its public API (src/README.md, "Public API").
"""

__version__ = "0.4.0.dev0"

#: The root re-exports nothing but the version: import a subpackage directly.
__all__ = ["__version__"]
