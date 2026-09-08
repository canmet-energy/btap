"""Installed, offline access to the NECB Section 8.4 coverage references."""

from __future__ import annotations

import argparse
import copy
import json
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
    except (KeyError, TypeError, ValueError) as exc:
        print(f"error: {exc}", file=err)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())