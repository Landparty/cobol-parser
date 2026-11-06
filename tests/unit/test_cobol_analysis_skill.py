"""The `cobol-analysis` agent skill (.claude/skills/cobol-analysis/SKILL.md)
tells an AI assistant which subcommand answers which question. A stale
subcommand or flag there sends the assistant to a command that fails, so
every one it names is checked against the real argument parser here.
mocky-mock ships this file verbatim, so it reaches users of both repos."""

import argparse
import re
from pathlib import Path

import pytest

from cobolparser.analysis.lint import RULES
from cobolparser.cli.parse import _build_parser

SKILL_PATH = (
    Path(__file__).resolve().parents[2]
    / ".claude"
    / "skills"
    / "cobol-analysis"
    / "SKILL.md"
)


def _subparsers() -> dict[str, argparse.ArgumentParser]:
    parser = _build_parser()
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            return dict(action.choices)
    raise AssertionError("cobol-parser has no subcommands")


def _skill_text() -> str:
    return SKILL_PATH.read_text(encoding="utf-8")


def _table_commands() -> list[tuple[str, list[str]]]:
    """(subcommand, flags) for every command cell of the question table."""
    commands = []
    for line in _skill_text().splitlines():
        if not line.startswith("|") or "`" not in line:
            continue
        cell = line.rstrip("|").rsplit("|", 1)[-1]
        for snippet in re.findall(r"`([^`]+)`", cell):
            words = snippet.split()
            if words and re.fullmatch(r"[a-z][a-z0-9-]+", words[0]):
                commands.append((words[0], re.findall(r"--[a-z][a-z0-9-]*", snippet)))
    return commands


def test_skill_frontmatter_names_the_skill():
    text = _skill_text()
    assert text.startswith("---\nname: cobol-analysis\ndescription: ")


def test_question_table_is_not_empty():
    assert len(_table_commands()) >= 20


@pytest.mark.parametrize(("command", "flags"), _table_commands())
def test_every_table_command_and_flag_exists(command, flags):
    subparsers = _subparsers()
    assert command in subparsers, f"no `cobol-parser {command}` subcommand"
    known = {
        option
        for action in subparsers[command]._actions
        for option in action.option_strings
    }
    for flag in flags:
        assert flag in known, f"`cobol-parser {command}` has no {flag}"


def test_lint_rule_list_matches_the_analyzer():
    text = " ".join(_skill_text().split())
    words = {
        9: "nine",
        10: "ten",
        11: "eleven",
        12: "twelve",
        16: "sixteen",
        17: "seventeen",
        18: "eighteen",
        26: "twenty-six",
        27: "twenty-seven",
        28: "twenty-eight",
    }
    # Any other count is written in digits.
    assert f"`lint` runs {words.get(len(RULES), str(len(RULES)))} rules" in text
    for rule in RULES:
        assert f"`{rule}`" in text
