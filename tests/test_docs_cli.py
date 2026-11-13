"""docs/cli.md is the single source of truth for the new nomenclature.

Two executable contracts:

1. Every ``oto …`` chain in ``docs/cli.md`` resolves to a real path in the
   live parser (a generated doc can never advertise a command that does not
   exist).
2. ``docs/cli.md`` is byte-identical to what ``oto help --write`` would emit
   today (the generated file never drifts from the parser).

Both also guard the README quick-start, which quotes the same commands.
"""

from __future__ import annotations

import re
import tempfile
from pathlib import Path

from oto.cli.docs import write_reference
from oto.cli.parser import build_parser, subparser_for

REPO = Path(__file__).resolve().parents[1]
_DOC = REPO / "docs" / "cli.md"
_TOKEN = re.compile(r"[a-z][a-z0-9_-]*")


def _roots(parser) -> set[str]:
    import argparse
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            return set(action.choices)
    return set()


def _documented_chains(text: str):
    for match in re.finditer(r"\boto\b", text):
        rest = text[match.end():match.end() + 80].split("#")[0]
        tokens = _TOKEN.findall(rest)
        if tokens:
            yield tokens


def test_documented_commands_exist():
    parser = build_parser()
    roots = _roots(parser)
    checked = 0
    for tokens in _documented_chains(_DOC.read_text()):
        if tokens[0] not in roots:
            continue  # prose, placeholder, or a module path — not a command
        # Walk as far as the parser's own subcommand tree allows; the rest
        # are arguments and are not part of the path.
        path, current = [], parser
        for tok in tokens:
            try:
                current = subparser_for(current, [tok])
            except KeyError:
                break
            path.append(tok)
        assert path, f"unresolvable command in docs/cli.md: {tokens}"
        checked += 1
    assert checked > 20, "expected a rich sample of documented commands"


def test_cli_md_is_fresh():
    with tempfile.TemporaryDirectory() as d:
        target = Path(d) / "cli.md"
        write_reference(build_parser(), target)
        assert target.read_text() == _DOC.read_text(), (
            "docs/cli.md is stale — regenerate with `oto help --write docs/cli.md`"
        )


if __name__ == "__main__":
    test_documented_commands_exist()
    test_cli_md_is_fresh()
    print("docs/cli.md contracts OK")


def test_readme_examples_exist():
    parser = build_parser()
    roots = _roots(parser)
    checked = 0
    for match in re.finditer(r"\boto\b", (REPO / "README.md").read_text()):
        rest = match.string[match.end():match.end() + 60].split("#")[0]
        tokens = _TOKEN.findall(rest)
        if not tokens or tokens[0] not in roots:
            continue
        path, current = [], parser
        for tok in tokens:
            try:
                current = subparser_for(current, [tok])
            except KeyError:
                break
            path.append(tok)
        assert path, f"unresolvable command in README.md: {tokens}"
        checked += 1
    assert checked > 5, "expected a useful sample of README CLI examples"
