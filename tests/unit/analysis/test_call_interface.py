"""CallInterfaceChecker: every CALL against the interface of its callee."""

import json
import sys
from pathlib import Path

import pytest

from cobolparser import parse_cobol
from cobolparser.analysis.call_interface import (
    KIND_ARGUMENT_COUNT,
    KIND_LENGTH,
    KIND_PASSING_MODE,
    KIND_RETURNING,
    KIND_USAGE,
    CallInterfaceChecker,
)
from cobolparser.cli.parse import main

CALLEE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. CALLEE.
       DATA DIVISION.
       LINKAGE SECTION.
       01 LK-REC.
          05 LK-ID    PIC X(10).
          05 LK-AMT   PIC S9(7)V99 COMP-3.
          05 LK-NAME  PIC X(15).
       01 LK-COUNT    PIC S9(4) COMP.
       01 LK-FLAG     PIC X.
       PROCEDURE DIVISION USING LK-REC LK-COUNT BY VALUE LK-FLAG.
           MOVE 1 TO LK-COUNT
           GOBACK.
"""


def _caller(body: str, data: str = "") -> str:
    return f"""\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. CALLER.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-REC.
          05 WS-ID    PIC X(10).
          05 WS-AMT   PIC S9(7)V99 COMP-3.
          05 WS-NAME  PIC X(15).
       01 WS-COUNT    PIC S9(4) COMP.
       01 WS-FLAG     PIC X.
{data}       PROCEDURE DIVISION.
{body}           GOBACK.
"""


def _check(*sources: tuple[str, str]):
    programs = [(path, parse_cobol(source).ast) for path, source in sources]
    return CallInterfaceChecker().check_programs(programs)


def _kinds(report):
    return [(f.kind, f.severity, f.position) for f in report.findings]


class TestMatchingInterface:
    def test_matching_call_is_clean(self):
        report = _check(
            ("CALLEE.cbl", CALLEE),
            (
                "CALLER.cbl",
                _caller(
                    "           CALL 'CALLEE' USING WS-REC WS-COUNT BY VALUE WS-FLAG\n"
                ),
            ),
        )
        assert report.findings == []
        assert report.checked_calls == 1
        assert report.external_calls == {}

    def test_external_call_is_counted_not_reported(self):
        report = _check(
            ("CALLER.cbl", _caller("           CALL 'CEE3ABD' USING WS-COUNT\n"))
        )
        assert report.findings == []
        assert report.external_calls == {"CEE3ABD": 1}
        assert report.checked_calls == 0


class TestMismatches:
    def test_argument_count(self):
        report = _check(
            ("CALLEE.cbl", CALLEE),
            ("CALLER.cbl", _caller("           CALL 'CALLEE' USING WS-REC WS-COUNT\n")),
        )
        assert (KIND_ARGUMENT_COUNT, "error", None) in _kinds(report)

    def test_by_reference_to_by_value(self):
        report = _check(
            ("CALLEE.cbl", CALLEE),
            (
                "CALLER.cbl",
                _caller("           CALL 'CALLEE' USING WS-REC WS-COUNT WS-FLAG\n"),
            ),
        )
        assert _kinds(report) == [(KIND_PASSING_MODE, "error", 3)]

    def test_by_value_to_by_reference(self):
        report = _check(
            ("CALLEE.cbl", CALLEE),
            (
                "CALLER.cbl",
                _caller(
                    "           CALL 'CALLEE' USING WS-REC BY VALUE WS-COUNT WS-FLAG\n"
                ),
            ),
        )
        assert _kinds(report) == [(KIND_PASSING_MODE, "error", 2)]

    def test_by_content_is_fine_for_by_reference(self):
        report = _check(
            ("CALLEE.cbl", CALLEE),
            (
                "CALLER.cbl",
                _caller(
                    "           CALL 'CALLEE' USING BY CONTENT WS-REC WS-COUNT\n"
                    "                BY VALUE WS-FLAG\n"
                ),
            ),
        )
        assert report.findings == []

    def test_short_argument_is_an_error_long_is_info(self):
        data = "       01 WS-SHORT PIC X(20).\n       01 WS-LONG PIC X(40).\n"
        report = _check(
            ("CALLEE.cbl", CALLEE),
            (
                "CALLER.cbl",
                _caller(
                    "           CALL 'CALLEE' USING WS-SHORT WS-COUNT BY VALUE WS-FLAG\n"
                    "           CALL 'CALLEE' USING WS-LONG WS-COUNT BY VALUE WS-FLAG\n",
                    data,
                ),
            ),
        )
        short, long_ = (f for f in report.findings if f.kind == KIND_LENGTH)
        assert (short.severity, short.argument.byte_length) == ("error", 20)
        assert short.parameter.byte_length == 30
        assert "10 byte(s) past it" in short.message
        assert (long_.severity, long_.argument.byte_length) == ("info", 40)

    def test_usage_mismatch(self):
        data = "       01 WS-ZONED PIC S9(4).\n"
        report = _check(
            ("CALLEE.cbl", CALLEE),
            (
                "CALLER.cbl",
                _caller(
                    "           CALL 'CALLEE' USING WS-REC WS-ZONED BY VALUE WS-FLAG\n",
                    data,
                ),
            ),
        )
        usage = [f for f in report.findings if f.kind == KIND_USAGE]
        assert len(usage) == 1
        assert usage[0].argument.storage == "DISPLAY"
        assert usage[0].parameter.storage == "BINARY"
        # S9(4) DISPLAY is 4 bytes against a 2-byte halfword: also longer.
        assert (KIND_LENGTH, "info", 2) in _kinds(report)

    def test_comp_and_comp_4_and_binary_are_the_same_storage(self):
        data = "       01 WS-BIN PIC S9(4) BINARY.\n"
        report = _check(
            ("CALLEE.cbl", CALLEE),
            (
                "CALLER.cbl",
                _caller(
                    "           CALL 'CALLEE' USING WS-REC WS-BIN BY VALUE WS-FLAG\n",
                    data,
                ),
            ),
        )
        assert report.findings == []

    def test_returning_on_one_side(self):
        callee = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. RETPGM.
       DATA DIVISION.
       LINKAGE SECTION.
       01 LK-RC PIC S9(9) COMP.
       PROCEDURE DIVISION RETURNING LK-RC.
           GOBACK.
"""
        report = _check(
            ("RETPGM.cbl", callee),
            ("CALLER.cbl", _caller("           CALL 'RETPGM'\n")),
        )
        assert _kinds(report) == [(KIND_RETURNING, "warning", None)]


class TestArgumentShapes:
    @pytest.mark.parametrize(
        "argument",
        ["OMITTED", "ADDRESS OF WS-REC", "LENGTH OF WS-REC", "42", "ZERO"],
    )
    def test_unknown_lengths_are_reported_unchecked(self, argument):
        report = _check(
            ("CALLEE.cbl", CALLEE),
            (
                "CALLER.cbl",
                _caller(
                    f"           CALL 'CALLEE' USING BY CONTENT {argument} WS-COUNT\n"
                    "                BY VALUE WS-FLAG\n"
                ),
            ),
        )
        assert not [f for f in report.findings if f.kind == KIND_LENGTH]
        if argument != "OMITTED":
            assert any("argument 1: length not compared" in u for u in report.unchecked)

    def test_alphanumeric_literal_length(self):
        report = _check(
            ("CALLEE.cbl", CALLEE),
            (
                "CALLER.cbl",
                _caller(
                    "           CALL 'CALLEE' USING BY CONTENT 'ABC' WS-COUNT\n"
                    "                BY VALUE WS-FLAG\n"
                ),
            ),
        )
        (finding,) = [f for f in report.findings if f.kind == KIND_LENGTH]
        assert finding.argument.byte_length == 3

    def test_qualified_subscripted_and_reference_modified(self):
        data = (
            "       01 GRP-A.\n          05 DUP PIC X(30).\n"
            "       01 GRP-B.\n          05 DUP PIC X(5).\n"
            "       01 TBL-REC.\n          05 TBL PIC X(30) OCCURS 3.\n"
            "       01 BIG PIC X(100).\n"
        )
        report = _check(
            ("CALLEE.cbl", CALLEE),
            (
                "CALLER.cbl",
                _caller(
                    "           CALL 'CALLEE' USING DUP OF GRP-A WS-COUNT BY VALUE WS-FLAG\n"
                    "           CALL 'CALLEE' USING TBL(2) WS-COUNT BY VALUE WS-FLAG\n"
                    "           CALL 'CALLEE' USING BIG(1:30) WS-COUNT BY VALUE WS-FLAG\n"
                    "           CALL 'CALLEE' USING DUP WS-COUNT BY VALUE WS-FLAG\n"
                    "           CALL 'CALLEE' USING TBL WS-COUNT BY VALUE WS-FLAG\n",
                    data,
                ),
            ),
        )
        assert report.findings == []
        assert report.checked_calls == 5
        assert any("declared more than once" in u for u in report.unchecked)
        assert any("without a subscript" in u for u in report.unchecked)


class TestTargets:
    def test_dynamic_call_checks_every_known_target(self):
        data = "       01 WS-PGM PIC X(8) VALUE 'CALLEE'.\n"
        report = _check(
            ("CALLEE.cbl", CALLEE),
            (
                "CALLER.cbl",
                _caller("           CALL WS-PGM USING WS-REC WS-COUNT\n", data),
            ),
        )
        assert (KIND_ARGUMENT_COUNT, "error", None) in _kinds(report)

    def test_entry_statement_interface(self):
        callee = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. MULTI.
       DATA DIVISION.
       LINKAGE SECTION.
       01 LK-A PIC X(4).
       01 LK-B PIC X(8).
       PROCEDURE DIVISION USING LK-A.
           GOBACK.
           ENTRY 'ALT' USING LK-B.
           GOBACK.
"""
        data = "       01 WS-4 PIC X(4).\n"
        report = _check(
            ("MULTI.cbl", callee),
            (
                "CALLER.cbl",
                _caller(
                    "           CALL 'MULTI' USING WS-4\n"
                    "           CALL 'ALT' USING WS-4\n",
                    data,
                ),
            ),
        )
        (finding,) = report.findings
        assert (finding.kind, finding.severity) == (KIND_LENGTH, "error")
        assert "CALL 'ALT'" in finding.message
        assert finding.parameter.byte_length == 8

    def test_program_declared_in_two_files_is_unchecked(self):
        report = _check(
            ("CALLEE.cbl", CALLEE),
            ("COPY/CALLEE.cbl", CALLEE),
            ("CALLER.cbl", _caller("           CALL 'CALLEE' USING WS-REC\n")),
        )
        assert report.findings == []
        assert any("declared in 2 files" in u for u in report.unchecked)

    def test_nested_program_by_scope(self):
        source = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. OUTER.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-X PIC X(2).
       PROCEDURE DIVISION.
           CALL 'INNER' USING WS-X
           GOBACK.
       IDENTIFICATION DIVISION.
       PROGRAM-ID. INNER.
       DATA DIVISION.
       LINKAGE SECTION.
       01 LK-X PIC X(9).
       PROCEDURE DIVISION USING LK-X.
           GOBACK.
       END PROGRAM INNER.
       END PROGRAM OUTER.
"""
        report = _check(("OUTER.cbl", source))
        (finding,) = report.findings
        assert finding.callee == "OUTER/INNER"
        assert finding.kind == KIND_LENGTH


class TestReport:
    def test_to_dict_and_text(self):
        report = _check(
            ("CALLEE.cbl", CALLEE),
            ("CALLER.cbl", _caller("           CALL 'CALLEE' USING WS-REC WS-COUNT\n")),
        )
        data = report.to_dict()
        assert data["summary"]["error"] == 1
        assert data["summary"]["checked_calls"] == 1
        assert data["findings"][0]["kind"] == KIND_ARGUMENT_COUNT
        text = report.to_text()
        assert text.startswith("CALLER.cbl:")
        assert "[argument-count]" in text
        assert report.worst_severity() == "error"


class TestCheckFiles:
    def test_files_and_parse_failures(self, tmp_path: Path):
        (tmp_path / "CALLEE.cbl").write_text(CALLEE)
        (tmp_path / "CALLER.cbl").write_text(
            _caller("           CALL 'CALLEE' USING WS-REC WS-COUNT\n")
        )
        report = CallInterfaceChecker().check_files(
            [str(tmp_path / "CALLEE.cbl"), str(tmp_path / "CALLER.cbl")]
        )
        assert [f.kind for f in report.findings] == [KIND_ARGUMENT_COUNT]

    def test_unparsed_and_erroneous_files_are_reported(self, tmp_path: Path):
        (tmp_path / "BAD.cbl").write_text("       THIS IS NOT COBOL.\n")
        report = CallInterfaceChecker().check_files(
            [str(tmp_path / "BAD.cbl"), str(tmp_path / "MISSING.cbl")]
        )
        assert {Path(e["path"]).name for e in report.errors} == {
            "BAD.cbl",
            "MISSING.cbl",
        }
        assert any("MISSING.cbl: not parsed" in u for u in report.unchecked)

    def test_copybook_paths(self, tmp_path: Path):
        (tmp_path / "LKREC.cpy").write_text(
            "       01 LK-REC.\n          05 LK-ID PIC X(10).\n"
        )
        (tmp_path / "CALLEE.cbl").write_text(
            "       IDENTIFICATION DIVISION.\n       PROGRAM-ID. CALLEE.\n"
            "       DATA DIVISION.\n       LINKAGE SECTION.\n"
            "       COPY LKREC.\n"
            "       PROCEDURE DIVISION USING LK-REC.\n           GOBACK.\n"
        )
        (tmp_path / "CALLER.cbl").write_text(
            "       IDENTIFICATION DIVISION.\n       PROGRAM-ID. CALLER.\n"
            "       DATA DIVISION.\n       WORKING-STORAGE SECTION.\n"
            "       01 WS-ID PIC X(4).\n"
            "       PROCEDURE DIVISION.\n"
            "           CALL 'CALLEE' USING WS-ID\n           GOBACK.\n"
        )
        report = CallInterfaceChecker(copybook_paths=[str(tmp_path)]).check_files(
            [str(tmp_path / "CALLEE.cbl"), str(tmp_path / "CALLER.cbl")]
        )
        (finding,) = report.findings
        assert finding.parameter.byte_length == 10

    def test_cli(self, tmp_path: Path, capsys, monkeypatch):
        (tmp_path / "CALLEE.cbl").write_text(CALLEE)
        (tmp_path / "CALLER.cbl").write_text(
            _caller("           CALL 'CALLEE' USING WS-REC WS-COUNT\n")
        )

        def run(*argv: str) -> int:
            monkeypatch.setattr(sys, "argv", ["cobol-parser", "call-check", *argv])
            try:
                main()
            except SystemExit as exc:
                return int(exc.code or 0)
            return 0

        assert run(str(tmp_path)) == 0
        assert json.loads(capsys.readouterr().out)["summary"]["error"] == 1
        assert run(str(tmp_path), "--fail-on", "error", "--format", "text") == 3
        assert "[argument-count]" in capsys.readouterr().out
        assert run(str(tmp_path), "--min-severity", "error", "--fail-on", "never") == 0
        capsys.readouterr()
        assert run(str(tmp_path / "NOPE.cbl")) == 2
        assert "no such file" in capsys.readouterr().err
        assert run(str(tmp_path), str(tmp_path / "CALLER.cbl")) == 1
