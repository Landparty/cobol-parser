"""Tests for the `redundancy` and `scan` CLI subcommands.

Covers:
- Both are registered in argparse AND in the legacy-syntax `_SUBCOMMANDS`
  set -- and, more usefully, that NO subcommand can ever be in one and not
  the other again (see TestSubcommandRegistrationInvariant)
- `redundancy` emits the full report the `health` score only summarizes,
  including the per-paragraph fingerprints nothing else exposes
- `scan` runs many files in one invocation, isolates a bad one, and groups
  clones across files under --clones
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from cobolparser.cli.parse import _SUBCOMMANDS, _build_parser, main

SAMPLES = Path(__file__).parents[2] / "samples"
_SIMPLE = str(SAMPLES / "simple_calculation.cbl")

_BODY = """\
           MOVE 1 TO WS-A
           MOVE 2 TO WS-B
           DISPLAY "DONE"
           STOP RUN.
"""


def _program(name: str, paragraph: str, body: str = _BODY) -> str:
    return f"""\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. {name}.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-A PIC 9 VALUE 0.
       01 WS-B PIC 9 VALUE 0.
       01 WS-C PIC 9 VALUE 0.
       PROCEDURE DIVISION.
       {paragraph}.
{body}
"""


def _write(tmp_path: Path, filename: str, source: str) -> str:
    path = tmp_path / filename
    path.write_text(source)
    return str(path)


class TestSubcommandRegistrationInvariant:
    """`_SUBCOMMANDS` is a hand-maintained copy of the registered subparser
    names, and `main()` silently misreads any name missing from it: the
    backward-compatibility shim decides the name is a *filename* and prepends
    "parse", so `cobol-parser redundancy foo.cbl` fails with
    "File not found: redundancy".

    Every subcommand so far has been guarded by its own one-line membership
    assertion in its own test file, which only ever catches the omission for
    a subcommand someone remembered to write that assertion for. This derives
    the truth from the parser instead, so the next subcommand is covered
    whether or not its author knows this hazard exists.
    """

    @staticmethod
    def _registered() -> set[str]:
        """The subparser names argparse actually knows.

        A subparsers action is the only one whose `choices` is a dict (name
        -> parser); every other `choices` is a plain sequence. Reading it is
        what makes this test derive the truth rather than restate it.
        """
        for action in _build_parser()._actions:
            choices = getattr(action, "choices", None)
            if isinstance(choices, dict):
                return set(choices)
        raise AssertionError("no subparsers action found on the top-level parser")

    def test_every_registered_subcommand_is_in_the_legacy_set(self) -> None:
        missing = self._registered() - set(_SUBCOMMANDS)
        assert not missing, (
            f"registered but absent from _SUBCOMMANDS: {sorted(missing)}. "
            "main() will treat these names as filenames and prepend 'parse'."
        )

    def test_the_legacy_set_names_no_subcommand_that_does_not_exist(self) -> None:
        extra = set(_SUBCOMMANDS) - self._registered()
        assert not extra, f"in _SUBCOMMANDS but not registered: {sorted(extra)}"


@pytest.mark.parametrize("subcmd", ["redundancy", "scan"])
class TestSubcommandsRegistered:
    def test_subcommand_in_parser(self, subcmd: str) -> None:
        parser = _build_parser()
        with pytest.raises(SystemExit):
            parser.parse_args([subcmd, "--help"])

    def test_subcommand_in_legacy_set(self, subcmd: str) -> None:
        assert subcmd in _SUBCOMMANDS


class TestRedundancySubcommand:
    def test_shape(self, capsys) -> None:
        with patch("sys.argv", ["cobol-parser", "redundancy", _SIMPLE, "--compact"]):
            main()
        data = json.loads(capsys.readouterr().out)
        assert data["source_file"] == _SIMPLE
        for key in (
            "dead_code",
            "unused_variables",
            "clone_groups",
            "paragraph_fingerprints",
            "summary",
        ):
            assert key in data

    def test_fingerprints_are_the_thing_health_does_not_expose(
        self, tmp_path: Path, capsys
    ) -> None:
        """The reason this subcommand exists: `health` folds redundancy into
        a score and a summary, and drops the digests entirely."""
        path = _write(tmp_path, "A.cbl", _program("PROGA", "ONLY-PARA"))

        with patch("sys.argv", ["cobol-parser", "health", path, "--compact"]):
            main()
        health = json.loads(capsys.readouterr().out)
        assert "paragraph_fingerprints" not in json.dumps(health)

        with patch("sys.argv", ["cobol-parser", "redundancy", path, "--compact"]):
            main()
        redundancy = json.loads(capsys.readouterr().out)
        assert len(redundancy["paragraph_fingerprints"]) == 1

    def test_min_clone_statements_is_honoured(self, tmp_path: Path, capsys) -> None:
        source = _program("PROGA", "BIG-PARA") + ""
        path = _write(tmp_path, "A.cbl", source)

        with patch(
            "sys.argv",
            [
                "cobol-parser",
                "redundancy",
                path,
                "--compact",
                "--min-clone-statements",
                "99",
            ],
        ):
            main()
        assert json.loads(capsys.readouterr().out)["paragraph_fingerprints"] == []


class TestScanSubcommand:
    def test_scans_several_files_in_one_invocation(
        self, tmp_path: Path, capsys
    ) -> None:
        paths = [
            _write(tmp_path, "A.cbl", _program("PROGA", "ONLY-PARA")),
            _write(tmp_path, "B.cbl", _program("PROGB", "OTHER-NAME")),
        ]
        with patch(
            "sys.argv", ["cobol-parser", "scan", *paths, "--compact", "--workers", "1"]
        ):
            main()
        data = json.loads(capsys.readouterr().out)
        assert data["scan_version"] >= 1
        assert data["summary"]["file_count"] == 2
        assert data["summary"]["scanned_file_count"] == 2
        assert data["summary"]["program_unit_count"] == 2

    def test_a_missing_file_is_a_failure_entry_not_an_abort(
        self, tmp_path: Path, capsys
    ) -> None:
        good = _write(tmp_path, "A.cbl", _program("PROGA", "ONLY-PARA"))
        missing = str(tmp_path / "gone.cbl")
        with patch(
            "sys.argv",
            ["cobol-parser", "scan", good, missing, "--compact", "--workers", "1"],
        ):
            main()
        data = json.loads(capsys.readouterr().out)
        assert data["summary"]["scanned_file_count"] == 1
        assert data["summary"]["failed_file_count"] == 1
        assert len(data["failures"]) == 1
        assert "could not read" in data["failures"][0]["error"]

    def test_clones_groups_across_files(self, tmp_path: Path, capsys) -> None:
        paths = [
            _write(tmp_path, "A.cbl", _program("PROGA", "ONLY-PARA")),
            _write(tmp_path, "B.cbl", _program("PROGB", "OTHER-NAME")),
        ]
        with patch(
            "sys.argv",
            ["cobol-parser", "scan", *paths, "--clones", "--compact", "--workers", "1"],
        ):
            main()
        data = json.loads(capsys.readouterr().out)
        groups = data["cross_file_clone_groups"]
        assert data["summary"]["cross_file_clone_group_count"] == len(groups) == 1
        assert groups[0]["clone_type"] == "TYPE_1"
        assert groups[0]["file_count"] == 2
        assert len(groups[0]["members"]) == 2

    def test_without_clones_no_group_key_is_emitted(
        self, tmp_path: Path, capsys
    ) -> None:
        path = _write(tmp_path, "A.cbl", _program("PROGA", "ONLY-PARA"))
        with patch(
            "sys.argv", ["cobol-parser", "scan", path, "--compact", "--workers", "1"]
        ):
            main()
        data = json.loads(capsys.readouterr().out)
        assert "cross_file_clone_groups" not in data

    def test_analyzer_selection(self, tmp_path: Path, capsys) -> None:
        path = _write(tmp_path, "A.cbl", _program("PROGA", "ONLY-PARA"))
        with patch(
            "sys.argv",
            [
                "cobol-parser",
                "scan",
                path,
                "--analyzer",
                "complexity",
                "--compact",
                "--workers",
                "1",
            ],
        ):
            main()
        data = json.loads(capsys.readouterr().out)
        assert data["analyzers"] == ["complexity"]
        assert set(data["files"][0]["units"][0]["reports"]) == {"complexity"}

    def test_unknown_analyzer_exits_nonzero_with_the_known_names(
        self, tmp_path: Path, capsys
    ) -> None:
        path = _write(tmp_path, "A.cbl", _program("PROGA", "ONLY-PARA"))
        with patch(
            "sys.argv",
            ["cobol-parser", "scan", path, "--analyzer", "nope", "--compact"],
        ):
            with pytest.raises(SystemExit) as exit_info:
                main()
        assert exit_info.value.code != 0
        assert "unknown analyzer" in capsys.readouterr().err

    def test_glob_collects_files(self, tmp_path: Path, capsys) -> None:
        _write(tmp_path, "A.cbl", _program("PROGA", "ONLY-PARA"))
        _write(tmp_path, "B.cbl", _program("PROGB", "OTHER-NAME"))
        with patch(
            "sys.argv",
            [
                "cobol-parser",
                "scan",
                "--glob",
                str(tmp_path / "*.cbl"),
                "--compact",
                "--workers",
                "1",
            ],
        ):
            main()
        assert json.loads(capsys.readouterr().out)["summary"]["file_count"] == 2

    def test_the_same_file_named_twice_is_scanned_once(
        self, tmp_path: Path, capsys
    ) -> None:
        path = _write(tmp_path, "A.cbl", _program("PROGA", "ONLY-PARA"))
        with patch(
            "sys.argv",
            ["cobol-parser", "scan", path, path, "--compact", "--workers", "1"],
        ):
            main()
        assert json.loads(capsys.readouterr().out)["summary"]["file_count"] == 1

    def test_no_input_fails_with_guidance(self, capsys) -> None:
        with patch("sys.argv", ["cobol-parser", "scan", "--compact"]):
            with pytest.raises(SystemExit) as exit_info:
                main()
        assert exit_info.value.code != 0
        assert "--glob" in capsys.readouterr().err
