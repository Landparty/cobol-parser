"""The top-level help screen, typo suggestions and first-run error messages."""

from __future__ import annotations

import argparse
import sys
from unittest.mock import patch

import pytest

from cobolparser.cli import _help
from cobolparser.cli.parse import _SUBCOMMANDS, _build_parser, main


def _registered() -> set[str]:
    for action in _build_parser()._actions:
        if isinstance(action, argparse._SubParsersAction):
            return set(action.choices)
    raise AssertionError("no subcommands")


def _run(argv: list[str]) -> int:
    with patch.object(sys, "argv", ["cobol-parser", *argv]):
        with pytest.raises(SystemExit) as exc:
            main()
    return int(exc.value.code or 0)


class TestGroupedOverview:
    def test_every_command_is_in_exactly_one_group(self):
        grouped = _help.grouped_command_names()
        assert len(grouped) == len(set(grouped)), "a command is listed twice"
        assert set(grouped) == _registered()

    def test_help_lists_groups_not_the_flat_choice_block(self, capsys):
        assert _run(["--help"]) == 0
        out = capsys.readouterr().out
        assert "usage: cobol-parser <command> [options] FILE ..." in out
        assert "Analyze one program:" in out
        assert "Quick start:" in out
        assert "Exit codes:" in out
        # argparse's own `{parse,batch,...}` block is gone
        assert "{parse,batch" not in out

    def test_bare_invocation_prints_overview_and_exits_2(self, capsys):
        assert _run([]) == 2
        out = capsys.readouterr().out
        assert "Commands:" in out
        assert "lint" in out


class TestMistypedCommand:
    def test_close_typo_gets_a_suggestion(self, capsys):
        assert _run(["dead-cod", "prog.cbl"]) == 2
        err = capsys.readouterr().err
        assert "unknown command 'dead-cod'" in err
        assert "did you mean 'dead-code'?" in err

    def test_file_like_word_is_still_a_file(self, capsys):
        # The legacy `cobol-parser FILE` form: a name with an extension is
        # never second-guessed as a command.
        assert _run(["pars.cbl"]) == 1
        assert "File not found: pars.cbl" in capsys.readouterr().err

    def test_existing_file_named_like_a_command_typo_is_parsed(
        self, tmp_path, monkeypatch, capsys
    ):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "pars").write_text(
            "       IDENTIFICATION DIVISION.\n       PROGRAM-ID. P.\n"
        )
        with patch.object(sys, "argv", ["cobol-parser", "pars"]):
            main()
        assert '"program_id": "P"' in capsys.readouterr().out

    def test_suggestion_ignores_unrelated_words(self):
        assert _help.suggest_command("zzzzzz", _SUBCOMMANDS) is None
        assert _help.suggest_command("lnt", _SUBCOMMANDS) == "lint"


class TestFirstRunErrors:
    def test_directory_instead_of_file(self, tmp_path, capsys):
        assert _run(["dead-code", str(tmp_path)]) == 1
        err = capsys.readouterr().err
        assert "is a directory" in err
        assert "lint --glob" in err
        assert "Errno" not in err

    def test_missing_copybook_dir_is_warned(self, tmp_path, capsys):
        prog = tmp_path / "p.cbl"
        prog.write_text("       IDENTIFICATION DIVISION.\n       PROGRAM-ID. P.\n")
        missing = tmp_path / "nope"
        with patch.object(
            sys,
            "argv",
            [
                "cobol-parser",
                "--no-config",
                "parse",
                str(prog),
                "--copybook-path",
                str(missing),
            ],
        ):
            main()
        err = capsys.readouterr().err
        assert f"--copybook-path {missing} is not an existing directory" in err

    def test_unexpanded_copy_without_copybook_path_is_hinted(self, tmp_path, capsys):
        prog = tmp_path / "p.cbl"
        prog.write_text(
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. P.\n"
            "       PROCEDURE DIVISION.\n"
            "           COPY MISSING.\n"
            "           STOP RUN.\n"
        )
        with patch.object(
            sys, "argv", ["cobol-parser", "--no-config", "dead-code", str(prog)]
        ):
            main()
        err = capsys.readouterr().err
        assert "1 copybook(s) not expanded (MISSING)" in err
        assert "--copybook-path" in err
