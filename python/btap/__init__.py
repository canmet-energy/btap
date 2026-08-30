"""btap — the NECB 2020/2025 Part 8 performance path, one distribution.

Five subpackages mirror the Ruby gem family and keep its one-way dependency
direction (D-77): necb -> costing -> modeling -> audit, simulation beside.
Import subpackages directly (``from btap.audit import AuditLog``); this root
deliberately imports none of them, so ``import btap`` never pulls the SDK.
"""

__version__ = "0.2.0"
