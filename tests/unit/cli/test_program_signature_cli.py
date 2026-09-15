"""Tests for the `program-signature` CLI subcommand.

The subcommand exists to be read by another program -- the COBOL Analyzer
extension's signature help, which shows a caller what the callee it is
about to CALL expects. So these tests pin the JSON contract that consumer
reads, not just that the command runs.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest

from cobolparser.cli.parse import _build_parser, _cmd_program_signature

SUBPGM = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. SUBPGM.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-TEMP PIC X(10).
       LINKAGE SECTION.
       01 LK-ACCT-ID PIC X(10).
       01 LK-RESULT  PIC 9(4).
       PROCEDURE DIVISION USING LK-ACCT-ID LK-RESULT.
       MAIN-PARA.
           MOVE LK-ACCT-ID TO WS-TEMP
           MOVE 42 TO LK-RESULT
           GOBACK.
"""

NESTED = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. OUTERP.
       DATA DIVISION.
       LINKAGE SECTION.
       01 LK-OUT PIC X(4).
       PROCEDURE DIVISION USING LK-OUT.
       OUTER-MAIN.
           GOBACK.
       IDENTIFICATION DIVISION.
       PROGRAM-ID. INNERP.
       DATA DIVISION.
       LINKAGE SECTION.
       01 LK-IN PIC X(4).
       PROCEDURE DIVISION USING LK-IN.
       INNER-MAIN.
           GOBACK.
       END PROGRAM INNERP.
       END PROGRAM OUTERP.
"""


def _args(filepath: str, **kwargs: object) -> argparse.Namespace:
    defaults: dict[str, object] = {
        "file": filepath,
        "compact": True,
        "free_form": False,
        "source_format": "auto",
        "dialect": "ibm-enterprise",
        "error_recovery": "collect-all",
        "copybook_path": [],
        "program": None,
        "define": [],
        "output": None,
        "profile": False,
    }
    defaults.update(kwargs)
    return argparse.Namespace(**defaults)


def _run(tmp_path: Path, source: str, capsys, **kwargs: object) -> dict:
    path = tmp_path / "SUBPGM.cbl"
    path.write_text(source, encoding="utf-8")
    _cmd_program_signature(_args(str(path), **kwargs))
    return json.loads(capsys.readouterr().out)


class TestSubcommandRegistration:
    def test_program_signature_is_a_known_subcommand(self):
        parsed = _build_parser().parse_args(["program-signature", "prog.cbl"])

        assert parsed.func is _cmd_program_signature
        assert parsed.file == "prog.cbl"

    def test_it_accepts_the_shared_analyzer_flags(self):
        parsed = _build_parser().parse_args(
            ["program-signature", "prog.cbl", "--compact", "--copybook-path", "./cpy"]
        )

        assert parsed.compact is True
        assert parsed.copybook_path == ["./cpy"]


class TestJsonContract:
    def test_output_carries_the_identification_header(self, tmp_path, capsys):
        payload = _run(tmp_path, SUBPGM, capsys)

        assert payload["source_file"].endswith("SUBPGM.cbl")
        assert payload["program_id"] == "SUBPGM"

    def test_every_key_the_extension_reads_is_present(self, tmp_path, capsys):
        payload = _run(tmp_path, SUBPGM, capsys)

        signature = payload["signatures"][0]
        assert signature["program_id"] == "SUBPGM"
        entry = signature["entry_points"][0]
        assert entry["kind"] == "procedure-division"
        assert entry["parameter_count"] == 2
        assert entry["call_example"] == 'CALL "SUBPGM" USING LK-ACCT-ID, LK-RESULT'

        first, second = entry["parameters"]
        assert first["name"] == "LK-ACCT-ID"
        assert first["position"] == 1
        assert first["picture"] == "X(10)"
        assert first["byte_length"] == 10
        assert first["direction"] == "input"
        assert first["declaration"] == "01 LK-ACCT-ID PIC X(10)"
        assert second["direction"] == "output"

    def test_the_gap_lists_are_always_present_even_when_empty(self, tmp_path, capsys):
        # A consumer must be able to distinguish "nothing was unresolved"
        # from "the key is missing", so these are never omitted.
        signature = _run(tmp_path, SUBPGM, capsys)["signatures"][0]

        assert signature["unreferenced_linkage"] == []
        assert signature["undeclared_parameters"] == []
        assert signature["unchecked"] == []


class TestMultipleProgramUnits:
    def test_every_callable_unit_gets_a_signature(self, tmp_path, capsys):
        payload = _run(tmp_path, NESTED, capsys)

        names = [s["program_id"] for s in payload["signatures"]]
        assert "OUTERP" in names
        assert "INNERP" in names

    def test_program_flag_narrows_to_one_unit(self, tmp_path, capsys):
        # The default above reports every unit, which is what a signature-help
        # consumer wants. --program is for a caller that already knows which
        # unit it means, and narrows through the shared parse path like every
        # other analyzer subcommand.
        payload = _run(tmp_path, NESTED, capsys, program="INNERP")

        names = [s["program_id"] for s in payload["signatures"]]
        assert names == ["INNERP"]


class TestFailureModes:
    def test_a_missing_file_exits_nonzero(self, tmp_path, capsys):
        with pytest.raises(SystemExit) as exc:
            _cmd_program_signature(_args(str(tmp_path / "nope.cbl")))

        assert exc.value.code != 0
