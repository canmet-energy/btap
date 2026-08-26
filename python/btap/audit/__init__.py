"""btap.audit — the family's shared audit machinery (port of btap-audit).

One AuditLog class (entry schema, building stamping, article:/ruling:
citation axes, JSON + narrative rendering) and one article-coverage emitter.
No domain knowledge, no SDK — the bottom of the family.
"""

from btap.audit.coverage import emit_coverage
from btap.audit.log import AuditLog

__all__ = ["AuditLog", "emit_coverage"]
