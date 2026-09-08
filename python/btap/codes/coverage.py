"""Installed, offline access to the NECB Section 8.4 coverage references, and
the checked provenance of every packaged rule file and table.

Each edition's ``manifest.json`` carries a ``provenance`` block covering exactly
its declared outputs; ``verify-source`` re-checks one of them against the
artifact its entry pins (a retained MCP payload, the pinned oracle at a
revision, or neither, which the entry says out loud).
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import subprocess
import sys
from functools import cache
from importlib import resources
from pathlib import Path
from typing import Any, TextIO

#: Inside an edition's snapshot: the packaged Section 8.4 article text. Each
#: edition carries its OWN copy (Stage 3); nothing here reads another
#: edition's file, and an edition without this file simply is not listed.
_ARTICLE_TEXT = ("coverage", "articles_8_4.json")
#: Code-family-neutral, and deliberately NOT per-edition: the disposition is
#: one curated responsibility map the generator reads across editions, and the
#: attribution is one Crown-copyright notice covering all cached text.
_DISPOSITION_FILE = "necb_8_4_disposition.json"
_ATTRIBUTION_FILE = "ATTRIBUTION.md"
#: Inside an edition's snapshot: the retained canonical source payloads the
#: manifest's ``provenance`` block hashes. Deliberately NOT covered by that
#: block itself — an archived artifact needing its own provenance recurses.
_PROVENANCE_DIR = "provenance"


def _resource(name: str):
    return resources.files("btap.codes").joinpath("data", "coverage", name)


@cache
def _load_json(name: str) -> dict[str, Any]:
    return json.loads(_resource(name).read_text(encoding="utf-8"))


@cache
def _load_path(path: Path) -> dict[str, Any]:
    """Cached on the resolved PATH, so repointing the family's data root in a
    test is never served the previous root's article text."""
    return json.loads(path.read_text(encoding="utf-8"))


def _edition(value: str | int) -> str:
    edition = str(value)
    known = editions()
    if edition not in known:
        raise ValueError(
            f"unsupported NECB edition {edition!r}; the installed reference "
            f"carries {', '.join(known) or '(none)'}"
        )
    return edition


def _article_document(edition: str | int) -> dict[str, Any]:
    from btap.codes.necb import edition_file

    return _load_path(edition_file(_edition(edition), *_ARTICLE_TEXT))


def _number_key(number: str) -> tuple[int, ...]:
    return tuple(int(part) for part in number.split("."))


def editions() -> tuple[str, ...]:
    """NECB editions whose snapshot carries packaged Section 8.4 article text.

    Deliberately NARROWER than :func:`btap.codes.editions`, which answers "has
    a manifest here": an edition is a first-class ruleset long before its
    article text is cached, and conflating the two would make a missing cache
    look like a missing code edition.
    """
    from btap.codes import editions as _registered
    from btap.codes.necb import _data_root, code_id

    root = _data_root()
    return tuple(
        edition for edition in _registered("necb")
        if root.joinpath(code_id(edition), *_ARTICLE_TEXT).is_file()
    )


def article_numbers(edition: str | int) -> tuple[str, ...]:
    """Section 8.4 article numbers included for ``edition``, in code order."""
    numbers = _article_document(edition)["articles"]
    return tuple(sorted(numbers, key=_number_key))


def get_article(edition: str | int, number: str) -> dict[str, Any]:
    """Return one article record.

    Raises:
        ValueError: If the edition is unsupported or the article is absent.
    """
    edition = _edition(edition)
    normalized = str(number).rstrip(".")
    try:
        article = _article_document(edition)["articles"][normalized]
    except KeyError as exc:
        raise ValueError(
            f"article {number!r} is not included in the NECB {edition} reference"
        ) from exc
    return copy.deepcopy(article)


def provenance(edition: str | int) -> dict[str, Any]:
    """Return retrieval and source metadata for an edition's article cache."""
    return copy.deepcopy(_article_document(edition)["provenance"])


def disposition(number: str | None = None) -> dict[str, Any] | None:
    """Return the disposition document, or one article's disposition.

    A missing individual article returns ``None`` because only articles needing
    an explicit responsibility determination appear in the disposition map.
    """
    document = _load_json(_DISPOSITION_FILE)
    if number is None:
        return copy.deepcopy(document)
    value = document["dispositions"].get(str(number).rstrip("."))
    return copy.deepcopy(value)


def dispositions() -> dict[str, dict[str, Any]]:
    """Return the article-number-to-disposition mapping."""
    return copy.deepcopy(_load_json(_DISPOSITION_FILE)["dispositions"])


def attribution() -> str:
    """Return the attribution and licensing notice for the cached NECB text."""
    return _resource(_ATTRIBUTION_FILE).read_text(encoding="utf-8")


def _write_json(value: Any, out: TextIO) -> None:
    print(json.dumps(value, indent=2, ensure_ascii=False), file=out)


def _fetch(edition: str, output: Path | None, err: TextIO) -> int:
    """Run the maintainer fetcher when this package is in a source checkout."""
    python_root = Path(__file__).resolve().parents[2]
    fetcher = python_root / "scripts" / "fetch_necb_8_4_text.py"
    if not fetcher.is_file():
        print(
            "error: fetching requires a canmet-btap source checkout; "
            "installed references remain available offline",
            file=err,
        )
        return 2
    from btap.codes.necb import _data_root, code_id

    destination = output or _data_root().joinpath(code_id(edition), *_ARTICLE_TEXT)
    return subprocess.run(
        [
            sys.executable,
            str(fetcher),
            "--edition",
            edition,
            "--out",
            str(destination),
        ],
        check=False,
    ).returncode


def source_provenance(code_id: str) -> dict[str, Any]:
    """The checked ``provenance`` block of one edition's manifest.

    Keyed by the edition-relative path of every manifest-DECLARED output. The
    archived payload for an entry, when it has one, sits beside the manifest at
    ``provenance/<basename>.result.json``.
    """
    return copy.deepcopy(_manifest(code_id).get("provenance") or {})


def _manifest(code_id: str) -> dict[str, Any]:
    return json.loads(
        (_snapshot(code_id) / "manifest.json").read_text(encoding="utf-8")
    )


def _snapshot(code_id: str) -> Path:
    """The directory of one edition's independent snapshot."""
    from btap.codes.necb import _data_root

    root = _data_root() / code_id
    if not (root / "manifest.json").is_file():
        raise ValueError(
            f"no code id {code_id!r} under {_data_root()} — every edition is a "
            "directory holding a manifest.json"
        )
    return root


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical(value: Any) -> str:
    """The canonical form every recorded source hash is taken over."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _oracle_checkout() -> Path | None:
    """The pinned legacy oracle's working tree, if this environment names one.

    Taken from the ENVIRONMENT only, never from an assumed repository layout:
    ``BTAP_ORACLE_CHECKOUT`` wins, and otherwise bundler is asked where it put
    the gem — but only when a ``BUNDLE_GEMFILE`` is already exported, which is
    how the maintainer and the parity job address the pinned oracle. An
    installed wheel has no repository around it, and the self-containment
    invariant is that this package never reaches into one.
    """
    override = os.environ.get("BTAP_ORACLE_CHECKOUT")
    if override:
        return Path(override) if Path(override).is_dir() else None

    if not os.environ.get("BUNDLE_GEMFILE"):
        return None
    try:
        found = subprocess.run(
            ["bundle", "show", "openstudio-standards"],
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    path = Path(found.stdout.strip()) if found.returncode == 0 else None
    return path if path and path.is_dir() else None


def _verify_archived(root: Path, relative: str, entry: dict, out: TextIO) -> int:
    """Re-hash the retained payload against the recorded source hash."""
    payload = root / _PROVENANCE_DIR / (Path(relative).name.removesuffix(".json")
                                        + ".result.json")
    if not payload.is_file():
        if entry["source_sha256"] == entry["result_sha256"]:
            print("  archived    the shipped file IS the retained artifact "
                  "(source_sha256 == result_sha256)", file=out)
            return 0
        print(f"  MISMATCH    archived payload {payload} is missing", file=out)
        return 1
    digest = _digest(payload)
    if digest != entry["source_sha256"]:
        print(f"  MISMATCH    {payload.name} hashes {digest}, "
              f"recorded {entry['source_sha256']}", file=out)
        return 1
    print(f"  archived    {payload.name} matches source_sha256", file=out)
    return 0


def _verify_revision(entry: dict, out: TextIO) -> int:
    """Re-hash the oracle files at the recorded revision, when it is here."""
    checkout = _oracle_checkout()
    request = entry["request"]
    items = request if isinstance(request, list) else [request]
    if checkout is None:
        print("  NOT CHECKABLE HERE — the pinned oracle is not installed", file=out)
        print(f"    revision  {entry['source_revision']}", file=out)
        for item in items:
            print(f"    path      {item['path']}", file=out)
        print("    point BTAP_ORACLE_CHECKOUT at a checkout of that "
              "revision, or export the repository's pinned-oracle "
              "BUNDLE_GEMFILE and install its bundle first", file=out)
        return 3

    problems = []
    for item in items:
        path = checkout / item["path"]
        if not path.is_file():
            problems.append(f"{item['path']} is missing from the checkout")
            continue
        digest = _digest(path)
        recorded = item.get("sha256")
        if recorded is None:
            if digest != entry["source_sha256"]:
                problems.append(
                    f"{item['path']} hashes {digest}, recorded "
                    f"{entry['source_sha256']}")
        elif digest != recorded:
            problems.append(f"{item['path']} hashes {digest}, recorded {recorded}")

    if not problems and isinstance(request, list):
        rebuilt = _canonical([{"path": item["path"],
                               "sha256": _digest(checkout / item["path"])}
                              for item in items])
        digest = hashlib.sha256(rebuilt.encode("utf-8")).hexdigest()
        if digest != entry["source_sha256"]:
            problems.append(
                f"the source set hashes {digest}, recorded {entry['source_sha256']}")

    if problems:
        for problem in problems:
            print(f"  MISMATCH    {problem}", file=out)
        return 1
    print(f"  revision    {len(items)} source file(s) at "
          f"{entry['source_revision'][:12]} match source_sha256 ({checkout})",
          file=out)
    return 0


def verify_source(code_id: str, relative: str, *, out: TextIO) -> int:
    """Re-check one manifest-declared output against its recorded provenance.

    ``0`` verified, ``1`` a hash mismatch, ``3`` not checkable on this machine
    (a live source with no retained payload, an oracle revision that is not
    installed, or a manual transcription with no retrievable artifact).
    """
    root = _snapshot(code_id)
    records = _manifest(code_id).get("provenance") or {}
    entry = records.get(relative)
    if entry is None:
        raise ValueError(
            f"{code_id} declares no provenance for {relative!r} — its manifest "
            f"covers {', '.join(sorted(records))}"
        )

    print(f"{code_id} {relative}", file=out)
    print(f"  source      {entry['source']}", file=out)
    print(f"  method      {entry['method']} "
          f"(source_verification: {entry['source_verification']})", file=out)
    print(f"  retrieved   {entry['retrieved']} "
          f"by {entry['extractor']}", file=out)

    shipped = root / relative
    digest = _digest(shipped)
    if digest != entry["result_sha256"]:
        print(f"  MISMATCH    the shipped file hashes {digest}, recorded "
              f"{entry['result_sha256']}", file=out)
        return 1
    print(f"  result      {relative} matches result_sha256", file=out)

    verification = entry["source_verification"]
    if verification == "archived":
        return _verify_archived(root, relative, entry, out)
    if verification == "revision_addressable":
        return _verify_revision(entry, out)
    if verification == "current_only":
        print("  NOT CHECKABLE HERE — the source is live and nothing was "
              "retained; re-fetch is a maintainer MCP operation, not a CLI one",
              file=out)
        _write_json(entry["request"], out)
        return 3
    if verification == "manual":
        print("  NOT CHECKABLE HERE — transcribed with no retrievable artifact",
              file=out)
        if entry.get("note"):
            print(f"    {entry['note']}", file=out)
        return 3
    raise ValueError(
        f"{code_id} {relative} declares unknown source_verification "
        f"{verification!r}"
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="btap-necb-coverage",
        description="Read the installed NECB Section 8.4 coverage reference",
    )
    installed = editions()
    commands = parser.add_subparsers(dest="command", required=True)

    commands.add_parser("editions", help="list installed NECB editions")

    list_parser = commands.add_parser("list", help="list article numbers")
    list_parser.add_argument("edition", choices=installed)
    list_parser.add_argument("--format", choices=("text", "json"), default="text")

    get_parser = commands.add_parser("get", help="get one article")
    get_parser.add_argument("edition", choices=installed)
    get_parser.add_argument("number")
    get_parser.add_argument("--format", choices=("text", "json"), default="text")

    provenance_parser = commands.add_parser("provenance", help="show cache provenance")
    provenance_parser.add_argument("edition", choices=installed)

    disposition_parser = commands.add_parser(
        "disposition", help="show all dispositions or one article's disposition"
    )
    disposition_parser.add_argument("number", nargs="?")

    commands.add_parser("attribution", help="show NECB attribution and licensing notice")

    fetch_parser = commands.add_parser(
        "fetch", help="maintainer-only: refresh one cache from a source checkout"
    )
    fetch_parser.add_argument("edition", choices=installed)
    fetch_parser.add_argument("--out", type=Path)

    verify_parser = commands.add_parser(
        "verify-source",
        help="re-check one packaged file against its recorded provenance",
    )
    verify_parser.add_argument("code_id", help="the code id, e.g. necb2020")
    verify_parser.add_argument(
        "file", help="the file inside that edition, e.g. tables/space_types.json"
    )
    return parser


def main(
    argv: list[str] | None = None,
    *,
    out: TextIO | None = None,
    err: TextIO | None = None,
) -> int:
    """Run the ``btap-necb-coverage`` console command."""
    out = out or sys.stdout
    err = err or sys.stderr
    args = _parser().parse_args(argv)

    try:
        if args.command == "editions":
            print("\n".join(editions()), file=out)
        elif args.command == "list":
            numbers = article_numbers(args.edition)
            if args.format == "json":
                _write_json(numbers, out)
            else:
                print("\n".join(numbers), file=out)
        elif args.command == "get":
            article = get_article(args.edition, args.number)
            if args.format == "json":
                _write_json(article, out)
            else:
                print(article["raw"], file=out)
        elif args.command == "provenance":
            _write_json(provenance(args.edition), out)
        elif args.command == "disposition":
            value = disposition(args.number)
            if args.number is not None and value is None:
                raise ValueError(f"article {args.number!r} has no explicit disposition")
            _write_json(value, out)
        elif args.command == "attribution":
            print(attribution(), end="", file=out)
        elif args.command == "fetch":
            return _fetch(args.edition, args.out, err)
        elif args.command == "verify-source":
            return verify_source(args.code_id, args.file, out=out)
    except (KeyError, TypeError, ValueError) as exc:
        print(f"error: {exc}", file=err)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())