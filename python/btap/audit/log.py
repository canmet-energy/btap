r"""The family-wide decision/audit trail (port of btap-audit's log.rb).

Every consequential step records WHAT was decided, the INPUTS it was decided
from, the model EVIDENCE behind it, and (where applicable) the NECB ARTICLE or
data-table citation that mandates it — so QAQC can answer "why did zone X get
System 6?" from the log instead of diffing models.

Entry schema (all optional except step/action/level):
    {step, target, action, inputs, value, article, ruling, ahj, evidence,
     building, level}     level: 'decision' | 'info' | 'warning'

ruling: WHICH adjudicated project decision(s) govern this code path — the D-XX
ids of the family's decision record. Where `article` cites the CODE that
mandates a value, `ruling` cites OUR judgement call about how that code was
read. Multiple ids are ONE space-separated string ('D-19 D-21'); consumers
scan r'\\bD-\\d+\\b'. Unbounded: `D-01` through `D-99` are all taken, so
the next decision is `D-100` and a two-digit scan would not see it.

ahj: WHICH register disposition applies to THIS runtime choice — the AHJ-NN
ids of `docs/NECB_AHJ_QUESTIONS.md`. The third citation axis: `article` cites
the Code requirement, `ruling` cites our adjudicated reading of it, and `ahj`
cites a question the Code does not settle, a requirement we knowingly do not
meet, a settled ruling that explains this choice, or a tool gap this path
reaches. Multiple ids are ONE space-separated string ('AHJ-1 AHJ-5'), the same
shape as `ruling`; consumers scan r'\bAHJ-\d+\b', de-duplicate, and sort
numerically.

It means "this disposition applies here", NOT "approval is required". All four
register statuses may be cited; only `referral` and `alternative-solution`
make a run conditional, and THIS MODULE DOES NOT KNOW WHICH IS WHICH. That
mapping lives in `btap.codes.ahj`, generated from the authored register:
`btap.audit` is the SDK-free, code-family-neutral floor, so it stores,
serializes and renders the field and decides nothing about it (Sol's `127`).

A static coverage-manifest entry must NOT carry `ahj`. A warning emitted on
every run is not evidence that a building reached the question; only an
executed choice may cite one.

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
                 article=None, ruling=None, ahj=None, evidence=None):
        return self._add("decision", step, action, target, inputs, value,
                         article, ruling, ahj, evidence)

    def info(self, step, action, *, target=None, inputs=None, value=None,
             article=None, ruling=None, ahj=None, evidence=None):
        return self._add("info", step, action, target, inputs, value,
                         article, ruling, ahj, evidence)

    def warn(self, step, action, *, target=None, inputs=None, value=None,
             article=None, ruling=None, ahj=None, evidence=None):
        return self._add("warning", step, action, target, inputs, value,
                         article, ruling, ahj, evidence)

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
            if _truthy(e.get("ahj")):
                line += f" | AHJ {e['ahj']}"
            lines.append(line)
        return "\n".join(lines)

    def _add(self, level, step, action, target, inputs, value, article,
             ruling, ahj, evidence):
        entry = {"step": step, "target": target, "action": action,
                 "inputs": inputs, "value": value, "article": article,
                 "ruling": ruling, "ahj": ahj, "evidence": evidence,
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
