"""Recursive golden inventory (D-80).

The request manifest freezes, per golden group, a SKELETON: the golden's
recursive structure with every leaf value replaced by its JSON type and
every list wrapped in an explicit comparison-mode node. Validating a golden
against its skeleton proves the complete recursive key inventory — nested
shrinkage, list shrinkage, and type drift all fail with the exact path named.

Skeleton grammar (every node is one of):
  {"__dict__": {key: node, ...}}                       - mapping, exact key set
  {"__list__": "ordered", "items": [node, ...]}        - compare by index
  {"__list__": "keyed", "key": [field, ...],
   "items": {"<canonical key>": node}}                 - compare by stable field(s)
  {"__list__": "set", "members": [scalar, ...]}        - canonicalized membership
  "num" | "str" | "bool" | "null"                      - leaf, by JSON type

List modes are declared at build time via path rules; the default is
"ordered" — an undeclared list neither freezes incidental oracle iteration
order silently (the mode is visible in the manifest) nor hides a real
ordering contract (ordered is the strict interpretation).
"""

from __future__ import annotations

import json


# Path rules: (path prefix tuple) -> ("keyed", [fields]) or ("set", None).
# Paths are the JSON keys from the group root; list traversal contributes
# "*" segments. Anything unmatched is "ordered".
def _leaf_type(value):
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, (int, float)):
        return "num"
    if isinstance(value, str):
        return "str"
    raise TypeError(f"unsupported leaf {type(value).__name__}")


def _key_of(item, fields, path):
    if not isinstance(item, dict):
        raise TypeError(f"{path}: keyed list item is not a mapping")
    return "|".join(str(item[f]) for f in fields)


def build_skeleton(value, rules=None, path=()):
    """Build the skeleton for ``value``; ``rules`` maps path tuples to
    ("keyed", [fields]) / ("set", None)."""
    rules = rules or {}
    if isinstance(value, dict):
        return {"__dict__": {k: build_skeleton(v, rules, path + (k,))
                             for k, v in value.items()}}
    if isinstance(value, list):
        mode, fields = rules.get(path, ("ordered", None))
        if mode == "keyed":
            items = {}
            for item in value:
                key = _key_of(item, fields, "/".join(path))
                if key in items:
                    raise ValueError(f"{'/'.join(path)}: duplicate key {key!r}")
                items[key] = build_skeleton(item, rules, path + ("*",))
            return {"__list__": "keyed", "key": fields, "items": items}
        if mode == "set":
            return {"__list__": "set", "members": sorted(value, key=json.dumps)}
        return {"__list__": "ordered",
                "items": [build_skeleton(v, rules, path + ("*",)) for v in value]}
    return _leaf_type(value)


def validate(value, skeleton, path="$"):
    """Return a list of human-readable inventory violations (empty = valid)."""
    errors = []
    if isinstance(skeleton, str):
        if not isinstance(value, (dict, list)):
            try:
                actual = _leaf_type(value)
            except TypeError:
                actual = type(value).__name__
            if actual != skeleton:
                errors.append(f"{path}: expected {skeleton}, got {actual}")
        else:
            errors.append(f"{path}: expected {skeleton} leaf, got container")
        return errors
    if "__dict__" in skeleton:
        if not isinstance(value, dict):
            return [f"{path}: expected mapping, got {type(value).__name__}"]
        want, have = set(skeleton["__dict__"]), set(value)
        for k in sorted(want - have):
            errors.append(f"{path}: missing key {k!r}")
        for k in sorted(have - want):
            errors.append(f"{path}: unexpected key {k!r}")
        for k in sorted(want & have):
            errors.extend(validate(value[k], skeleton["__dict__"][k], f"{path}/{k}"))
        return errors
    mode = skeleton["__list__"]
    if not isinstance(value, list):
        return [f"{path}: expected list ({mode}), got {type(value).__name__}"]
    if mode == "ordered":
        if len(value) != len(skeleton["items"]):
            errors.append(f"{path}: ordered list length {len(value)} != {len(skeleton['items'])}")
        for i, (v, s) in enumerate(zip(value, skeleton["items"])):
            errors.extend(validate(v, s, f"{path}[{i}]"))
        return errors
    if mode == "keyed":
        fields = skeleton["key"]
        try:
            have = {_key_of(item, fields, path): item for item in value}
        except (TypeError, KeyError) as exc:
            return [f"{path}: keyed list items lack key fields {fields}: {exc}"]
        want = skeleton["items"]
        for k in sorted(set(want) - set(have)):
            errors.append(f"{path}: missing item {k!r} (key {fields})")
        for k in sorted(set(have) - set(want)):
            errors.append(f"{path}: unexpected item {k!r} (key {fields})")
        for k in sorted(set(want) & set(have)):
            errors.extend(validate(have[k], want[k], f"{path}[{k}]"))
        return errors
    if mode == "set":
        want = skeleton["members"]
        have = sorted(value, key=json.dumps)
        if want != have:
            errors.append(f"{path}: set membership differs "
                          f"(missing {[m for m in want if m not in have][:5]}, "
                          f"extra {[m for m in have if m not in want][:5]})")
        return errors
    return [f"{path}: unknown list mode {mode!r}"]
