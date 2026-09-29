#!/usr/bin/env python3
"""Stage 2 — answer every typed request in both editions and archive it.

Each request is archived with its exact arguments, a UTC stamp, a SHA-256 and a
STATE. The state is an enum, never a boolean (Sol, `061` item 1):

    present           the tool returned content
    mcp_empty         the tool returned nothing -- NOT proven Code absence
    hierarchy_absent  absence established from the edition hierarchy
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
                    ResearchError, out_dir, read_json, request_key, sha256,
                    write_json)

sys.path.insert(0, str(PYTHON_ROOT))
from btap._mcp import MCPClient  # noqa: E402

EMPTY_MARKERS = ("empty result content", "no content")


def answer(client, request: dict):
    """``(payload, state, note)`` for one exact request."""
    arguments = {k: v for k, v in request.items() if k != "tool"}
    try:
        result = client.call(request["tool"], arguments)
    except Exception as error:                                # noqa: BLE001
        text = str(error)
        if any(marker in text for marker in EMPTY_MARKERS):
            return None, MCP_EMPTY, text
        raise ResearchError(
            f"{request['tool']} {arguments} failed: {text}") from error
    if not result:
        return None, MCP_EMPTY, "tool returned an empty result"
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
    if states.get(ERROR):
        raise ResearchError("errors recorded; corpus is incomplete")


if __name__ == "__main__":
    main()
