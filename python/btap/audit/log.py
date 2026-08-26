"""The family-wide decision/audit trail (port of btap-audit's log.rb).

Every consequential step records WHAT was decided, the INPUTS it was decided
from, the model EVIDENCE behind it, and (where applicable) the NECB ARTICLE or
data-table citation that mandates it — so QAQC can answer "why did zone X get
System 6?" from the log instead of diffing models.

Entry schema (all optional except step/action/level):
    {step, target, action, inputs, value, article, ruling, evidence,
     building, level}     level: 'decision' | 'info' | 'warning'

ruling: WHICH adjudicated project decision(s) govern this code path — the D-XX
ids of the family's decision record. Where `article` cites the CODE that
mandates a value, `ruling` cites OUR judgement call about how that code was
read. Multiple ids are ONE space-separated string ('D-19 D-21'); consumers
scan r'\\bD-\\d{2}\\b'.

building: WHICH model the entry is about ('input model', 'proposed building',
'reference building'), stamped from the current building context a pipeline
sets at phase boundaries. None = cross-building comparison or verdict.

Port notes (D-79): entries are str-keyed dicts throughout — Ruby's
symbol-keys-in-memory / string-keys-in-JSON dualism collapses to str, which
leaves the serialized audit.json IDENTICAL (the Leg-B contract). None-valued
fields are dropped at insert (Ruby's `.compact`): consumers use
``e.get('article')`` truthiness, never key presence with a None fallback
difference. Contract: warnings are never silent.
"""

from __future__ import annotations

import json
from contextlib import contextmanager

from btap._compat import ruby_str


class AuditLog:
    def __init__(self):
        self.entries: list[dict] = []
        self.building: str | None = None

    @contextmanager
    def with_building(self, name):
        """Stamp every entry recorded inside the block with the given building
        context; restores the previous context afterwards (nestable)."""
        previous = self.building
        self.building = name
        try:
            yield self
        finally:
            self.building = previous

    def decision(self, step, action, *, target=None, inputs=None, value=None,
                 article=None, ruling=None, evidence=None):
        return self._add("decision", step, action, target, inputs, value,
                         article, ruling, evidence)

    def info(self, step, action, *, target=None, inputs=None, value=None,
             article=None, ruling=None, evidence=None):
        return self._add("info", step, action, target, inputs, value,
                         article, ruling, evidence)

    def warn(self, step, action, *, target=None, inputs=None, value=None,
             article=None, ruling=None, evidence=None):
        return self._add("warning", step, action, target, inputs, value,
                         article, ruling, evidence)

    @property
    def warnings(self):
        """Warning entries only. The recorded level is 'warning', not 'warn'."""
        return [e for e in self.entries if e["level"] == "warning"]

    def to_json(self) -> str:
        return json.dumps(self.entries, indent=2, ensure_ascii=False)

    def __str__(self):
        """Human-readable narrative, one line per entry — same fixed-width
        shape as Ruby's to_s (the umbrella's checklist classifier parses the
        action text case-SENSITIVELY: violations SHOUTED, passes lowercase)."""
        lines = []
        for e in self.entries:
            line = "[%-8s] %-13s %s" % (e["level"], e["step"], e["action"])
            # Segment gates are RUBY truthiness (only nil/false falsy — '' and
            # 0 print), not Python truthiness.
            if _truthy(e.get("building")):
                line += f" | building: {e['building']}"
            if _truthy(e.get("target")):
                line += f" | target: {e['target']}"
            if _truthy(e.get("inputs")):
                line += f" | inputs: {_compact_hash(e['inputs'])}"
            if _truthy(e.get("value")):
                line += f" | value: {ruby_str(e['value'])}"
            if _truthy(e.get("evidence")):
                line += f" | evidence: {e['evidence']}"
            if _truthy(e.get("article")):
                line += f" | per {e['article']}"
            if _truthy(e.get("ruling")):
                line += f" | ruling {e['ruling']}"
            lines.append(line)
        return "\n".join(lines)

    def _add(self, level, step, action, target, inputs, value, article,
             ruling, evidence):
        entry = {"step": step, "target": target, "action": action,
                 "inputs": inputs, "value": value, "article": article,
                 "ruling": ruling, "evidence": evidence,
                 "building": self.building, "level": level}
        self.entries.append({k: v for k, v in entry.items() if v is not None})
        return self


def _truthy(value) -> bool:
    """Ruby truthiness: everything except nil and false."""
    return value is not None and value is not False


def _compact_hash(inputs: dict) -> str:
    """Ruby's inputs rendering: 'k=v, k=v', arrays joined with '/'."""
    return ", ".join(
        f"{k}={'/'.join(ruby_str(x) for x in v) if isinstance(v, list) else ruby_str(v)}"
        for k, v in inputs.items()
    )
