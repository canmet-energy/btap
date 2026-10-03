#!/usr/bin/env python3
"""Stage 0 — check the archive is internally consistent. Offline.

The first version checked only `present` payloads, and Sol falsified its central
claim (`074`): a table ROW inside the one `returned_mismatch` payload could be
changed with its hash untouched, and both `integrity.py` and the offline
`rebuild.py` reported the archive sound. That payload is server-erratum evidence,
so it is among the LEAST safe things to leave unhashed. Three adjacent holes went
with it — a stored `state` could disagree with the index, the index's declared
`request_count` was never read, and a `present` payload could have its `edition`
erased because the check was written `if edition and ...`, treating absent
identity as valid.

The rule now is uniform: **every stored non-null payload is hashed, and every
declared metadata field must agree between the payload and the index.** State is
not a licence to skip verification; it only changes what the payload must SAY.

Checks:

* the request-key set, the index-key set and the payload-file set are EQUAL, and
  the index's own `request_count` matches;
* every declared metadata field agrees between the stored payload and the index —
  not merely the `request` sub-object;
* every state is one of the declared enum values;
* every non-null payload's SHA-256 recomputes, whatever its state;
* a `present` payload identifies itself as the number AND the edition requested,
  with a missing value treated as a failure rather than a pass;
* a `returned_mismatch` payload really does identify itself as something OTHER
  than what was requested — the state has to earn its name;
* no extra and no missing payloads.

Exit code is non-zero on any failure, so this is usable as a gate.
`pipeline/test_method_gates.py` pins the mutations, not just the clean archive.
"""

from __future__ import annotations

import json
import sys

from common import (ERROR, HIERARCHY_ABSENT, MCP_EMPTY, PRESENT,
                    RETURNED_MISMATCH, STATES, out_dir, read_json, request_key,
                    sha256, write_json)

#: Metadata fields the archive declares. Compared in full between the stored
#: payload and the index, because comparing only `request` let a payload's own
#: `state` disagree with the index's (Sol, `074`).
META_FIELDS = ("request", "state", "sha256", "returned_number", "state_note",
               "title", "server_known_issue", "retrieved_utc")
#: States whose payload must be null. Anything else must carry evidence.
EMPTY_STATES = (MCP_EMPTY, ERROR)


def _identity(payload) -> tuple[str, str]:
    """What a payload says it IS: (number, edition), '' when absent."""
    number = (payload.get("table_number") or payload.get("article_number")
              or payload.get("section_number") or "")
    return str(number).rstrip("."), str(payload.get("edition") or "")


def _asked(request) -> tuple[str, str]:
    number = request.get("section_number") or request.get("table_number") or ""
    return str(number).rstrip("."), str(request.get("edition") or "")


def check(out):
    """``(findings, summary)`` — findings is empty when the archive is sound."""
    findings = []
    citations = read_json(out / "citations.json")
    index_doc = read_json(out / "hbix_index.json")
    index = index_doc["index"]

    expected = {request_key(request): request for request in citations["requests"]}
    on_disk = {path.stem: path for path in sorted((out / "hbix").glob("*.json"))}

    # 1. three sets, equal — and the index's own declared count
    for label, missing in (
            ("requested but not indexed", sorted(set(expected) - set(index))),
            ("indexed but not requested", sorted(set(index) - set(expected))),
            ("indexed but no payload file", sorted(set(index) - set(on_disk))),
            ("payload file but not indexed", sorted(set(on_disk) - set(index)))):
        if missing:
            findings.append(f"{label}: {len(missing)} {missing[:5]}")
    declared = index_doc.get("request_count")
    if declared != len(index):
        findings.append(
            f"index declares request_count={declared} but holds {len(index)} entries")

    states = {}
    for key, meta in sorted(index.items()):
        path = on_disk.get(key)
        if path is None:
            continue
        stored = read_json(path)
        payload, stored_meta = stored.get("payload"), stored.get("meta", {})

        # 2. EVERY declared metadata field agrees, not just `request`
        for field in META_FIELDS:
            if stored_meta.get(field) != meta.get(field):
                findings.append(
                    f"{key}: stored meta.{field} disagrees with the index "
                    f"({stored_meta.get(field)!r} vs {meta.get(field)!r})")
        if key in expected and meta.get("request") != expected[key]:
            findings.append(f"{key}: indexed request disagrees with citations.json")

        # 3. declared states only
        state = meta.get("state")
        states[state] = states.get(state, 0) + 1
        if state not in STATES:
            findings.append(f"{key}: undeclared state {state!r}")

        # `hierarchy_absent` is advertised by the state enum but has no
        # validated evidence structure, so it is refused outright rather than
        # trusted. Sol forged an absence in it two ways (`076`): a null payload
        # was rejected for the wrong reason, and an arbitrary POSITIVE payload
        # with a synchronised hash passed clean. Neither carried hierarchy
        # proof. No committed request uses this state; it fails closed until
        # that proof has a structure worth checking.
        if state == HIERARCHY_ABSENT:
            findings.append(
                f"{key}: state hierarchy_absent is not accepted — no validated "
                "structure exists for hierarchy evidence, so an absence in this "
                "state cannot be told apart from a forged one")
            continue

        # 4. a state dictates whether evidence exists, never whether it is checked
        if state in EMPTY_STATES:
            if payload is not None:
                findings.append(f"{key}: state {state} but a payload is stored")
            continue
        if payload is None:
            findings.append(f"{key}: state {state} but no payload is stored")
            continue

        recomputed = sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        if recomputed != meta.get("sha256"):
            findings.append(f"{key}: sha256 does not recompute (state {state})")

        # 5. what the payload must SAY, per state
        asked_number, asked_edition = _asked(meta.get("request", {}))
        got_number, got_edition = _identity(payload)
        if state == PRESENT:
            if got_number != asked_number:
                findings.append(
                    f"{key}: present, but identifies itself as {got_number!r} "
                    f"not {asked_number!r}")
            # absent identity is a FAILURE, not a pass: `if edition and ...`
            # treated an erased edition as valid (Sol, `074`)
            if not got_edition:
                findings.append(f"{key}: present, but declares no edition")
            elif got_edition != asked_edition:
                findings.append(
                    f"{key}: present, but edition {got_edition} not {asked_edition}")
        elif state == RETURNED_MISMATCH:
            # The state must be established AFFIRMATIVELY. Comparing for an exact
            # pair of equal strings let a payload that states the requested
            # number and says NOTHING about its edition pass: `_identity()` turns
            # a missing edition into "", which is unequal to "2020" and so looked
            # like a mismatch (Sol, `076`). Silence is not a mismatch.
            differs_number = bool(got_number) and got_number != asked_number
            differs_edition = bool(got_edition) and got_edition != asked_edition
            if not (differs_number or differs_edition):
                findings.append(
                    f"{key}: state returned_mismatch, but the payload establishes "
                    f"no mismatch — it says number {got_number!r} and edition "
                    f"{got_edition!r} against a request for {asked_number!r} / "
                    f"{asked_edition!r}. A mismatch needs a NONEMPTY differing "
                    "number or edition.")
            if meta.get("returned_number") and \
                    str(meta["returned_number"]).rstrip(".") != got_number:
                findings.append(
                    f"{key}: meta.returned_number {meta['returned_number']!r} is not "
                    f"what the payload says it is ({got_number!r})")

    if states.get(ERROR):
        findings.append(f"{states[ERROR]} request(s) in state 'error'")

    summary = {
        "requests": len(expected), "indexed": len(index),
        "payload_files": len(on_disk), "states": states,
        "declared_request_count": declared,
        "payloads_hashed": sum(1 for k, m in index.items()
                               if m.get("state") not in EMPTY_STATES),
        "server_known_issue_count": sum(
            1 for m in index.values() if m.get("server_known_issue")),
    }
    return findings, summary


def main(argv=None):
    out = out_dir(argv, __doc__)
    findings, summary = check(out)
    write_json(out / "integrity.json",
               {"summary": summary, "findings": findings})
    print("archive integrity")
    print(f"  requests / indexed / payload files : {summary['requests']} / "
          f"{summary['indexed']} / {summary['payload_files']}")
    print(f"  index declares                     : "
          f"{summary['declared_request_count']}")
    for state in sorted(summary["states"]):
        print(f"  {state:20} {summary['states'][state]}")
    print(f"  payloads hashed (every non-null)   : {summary['payloads_hashed']}")
    print(f"  server_known_issue_count           : "
          f"{summary['server_known_issue_count']}")
    if findings:
        print(f"\nNOT SOUND ({len(findings)}):")
        for finding in findings:
            print(f"  {finding}")
        return 1
    print("\nevery archive invariant holds")
    return 0


if __name__ == "__main__":
    sys.exit(main())
