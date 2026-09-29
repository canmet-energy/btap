#!/usr/bin/env python3
"""Fetch every cited article/table in BOTH editions and archive the payloads.

Sol's `058` requires, per packet: the exact request, the retrieval date, any
returned ``known_issue``, and a retained canonical payload. Doing that one
conversation call at a time for 144 fetches is not viable, so this batches them
through ``btap._mcp.MCPClient`` and writes each payload to disk with a hash.

The key is read from the environment and never printed.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, "/workspaces/openstudio-necb-gems/python")
from btap._mcp import MCPClient  # noqa: E402

TMP = Path("/home/vscode/.claude/jobs/a100f076/tmp")
ARCHIVE = TMP / "hbix"
ARCHIVE.mkdir(parents=True, exist_ok=True)
EDITIONS = ("2020", "2025")


def slug(number: str) -> str:
    return number.replace(".", "_").replace("/", "_").replace(" ", "")


def main():
    if not os.environ.get("HBIX_API_KEY"):
        raise SystemExit("HBIX_API_KEY not exported; use: set -a && source .env && set +a")
    bases = json.loads((TMP / "articles.json").read_text(encoding="utf-8"))["bases"]
    client = MCPClient("codes")
    index, stamp = {}, datetime.datetime.now(datetime.timezone.utc).isoformat()
    misses = []

    for number in bases:
        for edition in EDITIONS:
            key = f"{number}@{edition}"
            path = ARCHIVE / f"{slug(number)}__{edition}.json"
            if path.exists():
                index[key] = json.loads(path.read_text(encoding="utf-8"))["meta"]
                continue
            request = {"tool": "get_section", "code": "necb",
                       "section_number": number, "edition": edition}
            try:
                result = client.call("get_section", {
                    "code": "necb", "section_number": number, "edition": edition})
            except Exception as error:                        # noqa: BLE001
                # "empty result content" is how this server reports an article
                # that does not exist in the requested edition -- which for
                # 8.4.4.* @ 2025 is the renumbering itself, and is EVIDENCE,
                # not a transport failure. Anything else is recorded as an
                # error so it cannot be mistaken for absence.
                text = str(error)
                absent = "empty result content" in text
                meta = {"request": request, "retrieved_utc": stamp,
                        "exists": False, "absence_reported_as": text,
                        "sha256": None, "known_issue": None,
                        "title": None, "article_number": None}
                path.write_text(json.dumps({"meta": meta, "payload": None},
                                           ensure_ascii=False, indent=2) + "\n",
                                encoding="utf-8")
                index[key] = meta
                misses.append((key, "absent in this edition" if absent
                               else f"ERROR: {text}"))
                continue
            # MCPClient.call already unwraps content[0].text, so the parsed
            # tool result IS the section object -- there is no "result" key to
            # reach through. Reaching for one nulled all 109 fetches silently.
            body = result if isinstance(result, dict) and result else None
            payload = json.dumps(body, ensure_ascii=False, sort_keys=True)
            meta = {
                "request": request,
                "retrieved_utc": stamp,
                "exists": body is not None,
                "sha256": hashlib.sha256(payload.encode("utf-8")).hexdigest(),
                "known_issue": (body or {}).get("known_issue"),
                "title": (body or {}).get("title"),
                "article_number": (body or {}).get("article_number"),
            }
            path.write_text(json.dumps({"meta": meta, "payload": body},
                                       ensure_ascii=False, indent=2) + "\n",
                            encoding="utf-8")
            index[key] = meta
            if body is None:
                misses.append((key, "does not exist in this edition"))
            time.sleep(0.15)

    (TMP / "hbix_index.json").write_text(
        json.dumps({"retrieved_utc": stamp, "index": index}, indent=2,
                   ensure_ascii=False) + "\n", encoding="utf-8")

    present = sum(1 for m in index.values() if m["exists"])
    issues = [k for k, m in index.items() if m.get("known_issue")]
    print(f"fetched {len(index)} of {len(bases) * len(EDITIONS)}")
    print(f"  present in that edition : {present}")
    print(f"  absent in that edition  : {len(index) - present}")
    print(f"  carrying a known_issue  : {len(issues)} {issues[:6]}")
    if misses:
        print(f"\n  notable ({len(misses)}):")
        for key, why in misses[:20]:
            print(f"    {key}: {why}")


if __name__ == "__main__":
    main()
