"""Tests for the ``cobol-parser gen-fixtures`` CLI subcommand."""

from __future__ import annotations

import json
import os

import pytest

from cobolparser.cli.parse import _build_parser, main

FILE_OPERATIONS = "tests/samples/file_operations.cbl"
REPORT_TEST = "examples/cobol/shamrice/report_test.cbl"


def _run(monkeypatch, *argv: str) -> None:
    monkeypatch.setattr("sys.argv", ["cobol-parser", "gen-fixtures", *argv])
    main()


class TestGenFixturesParser:
    def test_subcommand_is_registered(self):
        args = _build_parser().parse_args(["gen-fixtures", FILE_OPERATIONS])
        assert args.command == "gen-fixtures"
        assert args.rows == 10
        assert args.format == "json"
        assert args.scenarios == "happy"

    def test_max_occurs_flag_defaults_to_none(self):
        args = _build_parser().parse_args(["gen-fixtures", FILE_OPERATIONS])
        assert args.max_occurs is None

    def test_max_occurs_flag_parses(self):
        args = _build_parser().parse_args(
            ["gen-fixtures", FILE_OPERATIONS, "--max-occurs", "5"]
        )
        assert args.max_occurs == 5

    def test_repeatable_path_flags(self):
        args = _build_parser().parse_args(
            [
                "gen-fixtures",
                FILE_OPERATIONS,
                "--copybook-path",
                "a",
                "--copybook-path",
                "b",
                "--callee-path",
                "c",
            ]
        )
        assert args.copybook_path == ["a", "b"]
        assert args.callee_path == ["c"]


class TestGenFixturesOutput:
    def test_emits_json_bundle_on_stdout(self, monkeypatch, capsys):
        _run(monkeypatch, FILE_OPERATIONS, "--seed", "1", "--compact")
        out = json.loads(capsys.readouterr().out)
        assert out["source_file"] == FILE_OPERATIONS
        assert out["bundle_version"] == 1
        assert out["program_name"] == "FILETEST"
        assert out["seed"] == 1

    def test_output_is_reproducible_for_a_seed(self, monkeypatch, capsys):
        _run(monkeypatch, FILE_OPERATIONS, "--seed", "7", "--compact")
        first = capsys.readouterr().out
        _run(monkeypatch, FILE_OPERATIONS, "--seed", "7", "--compact")
        second = capsys.readouterr().out
        assert first == second

    def test_rows_flag_controls_read_sequence_length(self, monkeypatch, capsys):
        _run(monkeypatch, FILE_OPERATIONS, "--seed", "1", "--rows", "3", "--compact")
        out = json.loads(capsys.readouterr().out)
        reads = [
            f
            for s in out["scenarios"]
            for f in s["fixtures"]
            if f["category"] == "READ"
        ]
        assert reads
        assert all(len(f["sequence"]) == 3 for f in reads)

    def test_max_occurs_flag_is_accepted_end_to_end(self, monkeypatch, capsys):
        _run(
            monkeypatch,
            FILE_OPERATIONS,
            "--seed",
            "1",
            "--max-occurs",
            "5",
            "--compact",
        )
        out = json.loads(capsys.readouterr().out)
        assert out["source_file"] == FILE_OPERATIONS

    def test_list_boundaries(self, monkeypatch, capsys):
        _run(monkeypatch, FILE_OPERATIONS, "--list-boundaries", "--compact")
        out = json.loads(capsys.readouterr().out)
        assert out["source_file"] == FILE_OPERATIONS
        categories = {b["category"] for b in out["boundaries"]}
        assert "READ" in categories
        assert "OPEN" in categories
        # --list-boundaries must not generate any values -- just the shape.
        assert "sequence" not in out["boundaries"][0]

    def test_writes_to_output_file(self, monkeypatch, tmp_path):
        out_path = tmp_path / "bundle.json"
        _run(
            monkeypatch,
            FILE_OPERATIONS,
            "--seed",
            "1",
            "--output",
            str(out_path),
        )
        data = json.loads(out_path.read_text())
        assert data["bundle_version"] == 1

    def test_csv_dir_format_writes_directory(self, monkeypatch, tmp_path):
        out_dir = tmp_path / "fixtures"
        _run(
            monkeypatch,
            FILE_OPERATIONS,
            "--seed",
            "1",
            "--format",
            "csv-dir",
            "--output",
            str(out_dir),
        )
        assert (out_dir / "MANIFEST.json").is_file()
        assert (out_dir / "happy-path").is_dir()
        assert len(os.listdir(out_dir / "happy-path")) > 0


class TestGenFixturesErrors:
    def test_missing_file(self, monkeypatch, capsys):
        with pytest.raises(SystemExit) as exc:
            _run(monkeypatch, "does-not-exist.cbl")
        assert exc.value.code == 1
        assert "no such file" in capsys.readouterr().err

    def test_csv_dir_without_output_fails(self, monkeypatch, capsys):
        with pytest.raises(SystemExit) as exc:
            _run(monkeypatch, FILE_OPERATIONS, "--format", "csv-dir")
        assert exc.value.code == 1
        assert "--output" in capsys.readouterr().err

    def test_strict_exits_2_when_unresolved(self, monkeypatch, capsys):
        with pytest.raises(SystemExit) as exc:
            _run(monkeypatch, REPORT_TEST, "--strict")
        assert exc.value.code == 2
        assert "unresolved item" in capsys.readouterr().err

    def test_strict_exits_0_when_clean(self, monkeypatch, capsys, tmp_path):
        # file_operations.cbl has a known OPT-FILE gap (see
        # test_program_fixtures.py); use a fixture with none of its own.
        source = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. CLEANPROG.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-MSG              PIC X(10) VALUE 'HELLO'.
       PROCEDURE DIVISION.
       MAIN-PARA.
           DISPLAY WS-MSG.
"""
        cbl_path = tmp_path / "clean.cbl"
        cbl_path.write_text(source)
        # Should not raise.
        _run(monkeypatch, str(cbl_path), "--seed", "1", "--strict", "--compact")
        assert capsys.readouterr().out


class TestGenFixturesInvalidOptions:
    """#327: a bad row count / max-occurs is a usage error, not a traceback."""

    @pytest.mark.parametrize(
        ("flags", "message"),
        [
            (("--rows", "-1"), "rows must be non-negative"),
            (("--max-occurs", "0"), "max_occurs must be at least 1"),
            (("--max-occurs", "-1"), "max_occurs must be at least 1"),
        ],
    )
    def test_bad_flag_is_a_one_line_error(self, monkeypatch, capsys, flags, message):
        with pytest.raises(SystemExit) as exc:
            _run(monkeypatch, "--no-config", FILE_OPERATIONS, *flags)
        assert exc.value.code == 1
        err = capsys.readouterr().err
        assert err.strip() == f"error: {message}"

    def test_negative_rows_in_project_config_is_a_one_line_error(
        self, tmp_path, monkeypatch, capsys
    ):
        program = os.path.abspath(FILE_OPERATIONS)
        (tmp_path / "cobol.yml").write_text("data:\n  rows: -5\n")
        monkeypatch.chdir(tmp_path)

        with pytest.raises(SystemExit) as exc:
            _run(monkeypatch, program)
        assert exc.value.code == 1
        assert capsys.readouterr().err.strip() == "error: rows must be non-negative"
