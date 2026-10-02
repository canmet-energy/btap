#!/usr/bin/env python3
"""Stage 0 — check the archive is internally consistent. Offline.

`rebuild.py` previously checked four derived JSON files and nothing else, while
printing "byte-for-byte" and actually calling a semantic comparison. Neither
`hbix/` nor `hbix_index.json` was validated at all, so a changed table row or a
new `known_issue` could pass the gate — especially since the comparator did not
read table rows (Sol, `065` item 5).

Every invariant here was independently checked by Sol by hand; this is those
checks, mechanised, so they hold on every run instead of once:

* the request-key set, the index-key set and the payload-file set are EQUAL;
* each payload's stored `request` matches the index's, exactly;
* every state is one of the declared enum values;
* every `present` payload's SHA-256 recomputes;
* every `present` payload identifies itself as the number and edition requested;
* no extra and no missing payloads.

Exit code is non-zero on any failure, so this is usable as a gate.
"""

from __future__ import annotations

import sys

from common import (ERROR, PRESENT, RETURNED_MISMATCH, STATES, out_dir,
                    read_json, request_key, sha256, write_json)


def check(out):
    """``(findings, summary)`` — findings is empty when the archive is sound."""
    findings = []
    citations = read_json(out / "citations.json")
    index_doc = read_json(out / "hbix_index.json")
    index = index_doc["index"]

    expected = {request_key(request): request for request in citations["requests"]}
    archive = out / "hbix"
    on_disk = {path.stem: path for path in sorted(archive.glob("*.json"))}

    # 1. three sets, equal
    for label, missing in (
            ("requested but not indexed", sorted(set(expected) - set(index))),
            ("indexed but not requested", sorted(set(index) - set(expected))),
            ("indexed but no payload file", sorted(set(index) - set(on_disk))),
            ("payload file but not indexed", sorted(set(on_disk) - set(index)))):
        if missing:
            findings.append(f"{label}: {len(missing)} {missing[:5]}")

    states = {}
    for key, meta in sorted(index.items()):
        path = on_disk.get(key)
        if path is None:
            continue
        stored = read_json(path)
        payload, stored_meta = stored.get("payload"), stored.get("meta", {})

        # 2. the payload's own record of the request matches the index's
        if stored_meta.get("request") != meta.get("request"):
            findings.append(f"{key}: payload request disagrees with the index")
        # and both match what was actually asked for
        if key in expected and meta.get("request") != expected[key]:
            findings.append(f"{key}: indexed request disagrees with citations.json")

        # 3. declared states only
        state = meta.get("state")
        states[state] = states.get(state, 0) + 1
        if state not in STATES:
            findings.append(f"{key}: undeclared state {state!r}")

        if state != PRESENT:
            if payload is not None and state != RETURNED_MISMATCH:
                findings.append(f"{key}: state {state} but a payload is stored")
            continue

        if payload is None:
            findings.append(f"{key}: state present but no payload")
            continue
        # 4. the hash recomputes
        import json as _json
        recomputed = sha256(_json.dumps(payload, ensure_ascii=False, sort_keys=True))
        if recomputed != meta.get("sha256"):
            findings.append(f"{key}: sha256 does not recompute")
        # 5. the payload identifies itself as what was requested
        request = meta.get("request", {})
        asked = str(request.get("section_number") or request.get("table_number") or "")
        returned = str(payload.get("table_number") or payload.get("article_number")
                       or payload.get("section_number") or "")
        if returned.rstrip(".") != asked.rstrip("."):
            findings.append(
                f"{key}: present, but identifies itself as {returned!r} not {asked!r}")
        edition = str(payload.get("edition") or "")
        if edition and edition != str(request.get("edition")):
            findings.append(
                f"{key}: present, but edition {edition} not {request.get('edition')}")

    if states.get(ERROR):
        findings.append(f"{states[ERROR]} request(s) in state 'error'")

    summary = {
        "requests": len(expected), "indexed": len(index),
        "payload_files": len(on_disk), "states": states,
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
    for state in sorted(summary["states"]):
        print(f"  {state:20} {summary['states'][state]}")
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
