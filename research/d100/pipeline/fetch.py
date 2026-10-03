#!/usr/bin/env python3
"""Stage 2 — answer every typed request in both editions and archive it.

Each request is archived with its exact arguments, a UTC stamp, a SHA-256 and a
STATE. The state is an enum, never a boolean (Sol, `061` item 1):

    present           the tool returned content
    mcp_empty         the tool returned nothing -- NOT proven Code absence
    hierarchy_absent  advertised, but REFUSED by the integrity gate: no
                      validated structure exists for hierarchy evidence
    returned_mismatch a payload identifying itself as something OTHER than what
                      was requested -- neither present nor a transport error
    error             transport/auth/protocol failure -- FAILS THE RUN

A transport failure must not produce a successful-looking corpus with a hole in
it, so it raises rather than being recorded as an absence. `mcp_empty` is
recorded and reported as exactly itself: an empty answer, which can mean the
provision is not at that address OR that the extraction has a gap, and only the
hierarchy can tell those apart.

Requires HBIX_API_KEY exported (`set -a && source .env && set +a`). The key is
never printed.
"""

from __future__ import annotations

import datetime
import json
import os
import sys
import time
from pathlib import Path

from common import (ARTIFACT_ROOT, ERROR, MCP_EMPTY, PRESENT, PYTHON_ROOT,
                    RETURNED_MISMATCH,
                    ResearchError, out_dir, read_json, request_key, sha256,
                    write_json)

sys.path.insert(0, str(PYTHON_ROOT))
from btap._mcp import MCPClient, MCPError  # noqa: E402

#: The ONE message `btap._mcp` raises when the server answered with an empty
#: content array — matched EXACTLY, per tool, never as a substring. Substring
#: matching classified transport failures as absence: a
#: `MCPError("get_table: HTTP 503: empty result content")` and a
#: `"network error: no content"` both became `mcp_empty`, contradicting this
#: module's own "transport failures fail the run" contract (Sol, `074`).
EMPTY_RESULT_SUFFIX = ": empty result content"


def is_empty_result(error, tool: str) -> bool:
    """True only for the MCP client's exact empty-content error, for THIS tool.

    TYPED, not merely exact-text. The first fix matched the full message, which
    still let `TimeoutError("get_table: empty result content")` be read as an
    absence, because `answer()` catches `Exception` and a transport exception
    cannot establish Code absence however its text reads (Sol, `076`). The error
    must BE an `MCPError` and say exactly the one thing the client says when the
    server returned an empty content array.

    The type check matters beyond this corpus: #67 vendors a new client
    implementation, and a condition keyed on an arbitrary exception's string
    would silently start classifying its errors.
    """
    return isinstance(error, MCPError) and \
        str(error) == f"{tool}{EMPTY_RESULT_SUFFIX}"


def answer(client, request: dict):
    """``(payload, state, note)`` for one exact request."""
    arguments = {k: v for k, v in request.items() if k != "tool"}
    try:
        result = client.call(request["tool"], arguments)
    except Exception as error:                                # noqa: BLE001
        text = str(error)
        if is_empty_result(error, request["tool"]):
            return None, MCP_EMPTY, text
        # Everything else is a transport or protocol failure and fails the run,
        # including a message whose text happens to mention empty content.
        raise ResearchError(
            f"{request['tool']} {arguments} failed: {text}") from error
    if not result:
        return None, MCP_EMPTY, "tool returned an empty result"

    # A non-empty payload is not success unless it identifies itself as what was
    # requested. HBIX answers the 2020 request for 8.4.4.1 with Table 8.4.4.12.
    asked_number = str(request.get("section_number") or request.get("table_number"))
    returned = str(result.get("table_number") or result.get("article_number")
                   or result.get("section_number") or "")
    asked_edition, returned_edition = str(request["edition"]), str(result.get("edition") or "")
    if returned.rstrip(".") != asked_number.rstrip("."):
        return result, RETURNED_MISMATCH, (
            f"requested {asked_number!r} but the payload identifies itself as "
            f"{returned!r}")
    if returned_edition and returned_edition != asked_edition:
        return result, RETURNED_MISMATCH, (
            f"requested edition {asked_edition} but the payload says "
            f"{returned_edition}")
    return result, PRESENT, ""


def main(argv=None):
    out = out_dir(argv, __doc__)
    if not os.environ.get("HBIX_API_KEY"):
        raise SystemExit("HBIX_API_KEY not exported; "
                         "use: set -a && source .env && set +a")
    requests = read_json(out / "citations.json")["requests"]
    archive = out / "hbix"
    archive.mkdir(parents=True, exist_ok=True)
    client = MCPClient("codes")
    stamp = datetime.datetime.now(datetime.timezone.utc).isoformat()

    index = {}
    for request in requests:
        key = request_key(request)
        path = archive / f"{key}.json"
        if path.exists():
            index[key] = read_json(path)["meta"]
            continue
        payload, state, note = answer(client, request)
        body = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        meta = {
            "request": request,
            "retrieved_utc": stamp,
            "state": state,
            "state_note": note,
            "sha256": sha256(body) if payload is not None else None,
            "server_known_issue": (payload or {}).get("known_issue"),
            "title": (payload or {}).get("title"),
            "returned_number": ((payload or {}).get("article_number")
                                or (payload or {}).get("table_number")),
        }
        write_json(path, {"meta": meta, "payload": payload})
        index[key] = meta
        time.sleep(0.15)

    # every count below is derived from this one index, so no report can name a
    # number the corpus does not contain (Sol, `061` item 2)
    write_json(out / "hbix_index.json",
               {"retrieved_utc": stamp, "request_count": len(index),
                "index": index})

    states = {}
    for meta in index.values():
        states[meta["state"]] = states.get(meta["state"], 0) + 1
    known = [k for k, m in index.items() if m.get("server_known_issue")]
    print(f"requests answered: {len(index)} of {len(requests)}")
    for state in sorted(states):
        print(f"  {state:18} {states[state]}")
    print(f"  server_known_issue_count: {len(known)}  {known[:4]}")
    print("  (that count is the SERVER's own flag. Locally observed extraction "
          "findings are recorded separately in README.md and never folded into "
          "it.)")
    print(f"written: {out / 'hbix_index.json'}")
    mismatched = [k for k, m in index.items() if m["state"] == RETURNED_MISMATCH]
    if mismatched:
        print(f"\n  RETURNED-NUMBER MISMATCHES ({len(mismatched)}) — the server "
              "answered with something other than what was asked:")
        for key in mismatched:
            print(f"    {key}: {index[key]['state_note']}")
    if states.get(ERROR):
        raise ResearchError("errors recorded; corpus is incomplete")
    if mismatched:
        # The archive is written and inspectable; the RUN is not clean.
        raise ResearchError(
            f"{len(mismatched)} request(s) answered with a different number or "
            "edition than requested; record each as a local HBIX finding before "
            "relying on the corpus")


if __name__ == "__main__":
    main()
