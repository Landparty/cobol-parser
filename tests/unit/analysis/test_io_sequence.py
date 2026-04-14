"""Unit tests for IOSequenceAnalyzer.

Covers every violation kind:
  READ_BEFORE_OPEN, WRITE_BEFORE_OPEN, REWRITE_BEFORE_OPEN,
  DELETE_BEFORE_OPEN, START_BEFORE_OPEN,
  DOUBLE_OPEN, CLOSE_NOT_OPEN, DOUBLE_CLOSE,
  FILE_LEFT_OPEN (at STOP RUN, at GOBACK, at end-of-program).

Also covers:
  - Happy path (no violations)
  - Multiple files in same program
  - to_dict() serialization
  - Empty program (no IO at all)
  - Unknown / empty file names (must be skipped, not crash)
  - Full COBOL source round-trip via parse_cobol()
"""

import json

from cobolparser import parse_cobol
from cobolparser.analysis.io_sequence import (
    IOSequenceAnalyzer,
    IOSequenceReport,
    IOSequenceViolation,
    IOViolationKind,
)
from cobolparser.models.ast_base import SourceLocation
from cobolparser.models.program import CobolDivision, CobolParagraph, CobolProgram
from cobolparser.models.statements.control import StopStatement
from cobolparser.models.statements.io import (
    IOCloseStatement,
    IODeleteStatement,
    IOOpenStatement,
    IOReadStatement,
    IORewriteStatement,
    IOStartStatement,
    IOWriteStatement,
)
from cobolparser.models.statements.misc import GobackStatement

_LOC = SourceLocation(1, 1)


# ---------------------------------------------------------------------------
# AST builder helpers
# ---------------------------------------------------------------------------


def _make_program(*statements) -> CobolProgram:
    """Build a minimal CobolProgram with the given statements in a single paragraph."""
    prog = CobolProgram("TEST-PROG", _LOC)
    id_div = CobolDivision("IDENTIFICATION", _LOC)
    prog.add_division(id_div)
    proc_div = CobolDivision("PROCEDURE", _LOC)
    para = CobolParagraph("MAIN-LOGIC", _LOC)
    for stmt in statements:
        para.add_statement(stmt)
    proc_div.add_paragraph(para)
    prog.add_division(proc_div)
    return prog


def _open(file_name: str, mode: str = "INPUT") -> IOOpenStatement:
    stmt = IOOpenStatement(_LOC)
    stmt.set_open_mode(mode)
    stmt.add_file(file_name)
    return stmt


def _close(file_name: str) -> IOCloseStatement:
    stmt = IOCloseStatement(_LOC)
    stmt.add_file(file_name)
    return stmt


def _read(file_name: str) -> IOReadStatement:
    stmt = IOReadStatement(_LOC)
    stmt.set_file_name(file_name)
    return stmt


def _write(record_name: str, file_name: str | None = None) -> IOWriteStatement:
    stmt = IOWriteStatement(_LOC)
    stmt.set_record_name(record_name)
    if file_name:
        stmt.file_name = file_name
    return stmt


def _rewrite(record_name: str, file_name: str | None = None) -> IORewriteStatement:
    stmt = IORewriteStatement(_LOC)
    stmt.set_record_name(record_name)
    if file_name:
        stmt.file_name = file_name
    return stmt


def _delete(file_name: str) -> IODeleteStatement:
    stmt = IODeleteStatement(_LOC)
    stmt.set_file_name(file_name)
    return stmt


def _start(file_name: str) -> IOStartStatement:
    stmt = IOStartStatement(_LOC)
    stmt.set_file_name(file_name)
    return stmt


def _stop() -> StopStatement:
    return StopStatement(_LOC)


def _goback() -> GobackStatement:
    return GobackStatement(_LOC)


def _analyze(*statements) -> IOSequenceReport:
    prog = _make_program(*statements)
    return IOSequenceAnalyzer().analyze(prog)


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


class TestIOSequenceHappyPath:
    def test_no_io_no_violations(self):
        report = _analyze()
        assert not report.has_violations
        assert report.violations == []

    def test_open_close_no_violations(self):
        report = _analyze(_open("MY-FILE"), _close("MY-FILE"))
        assert not report.has_violations

    def test_open_read_close_no_violations(self):
        report = _analyze(_open("MY-FILE"), _read("MY-FILE"), _close("MY-FILE"))
        assert not report.has_violations

    def test_open_write_close_no_violations(self):
        report = _analyze(
            _open("MY-FILE", "OUTPUT"),
            _write("MY-REC", "MY-FILE"),
            _close("MY-FILE"),
        )
        assert not report.has_violations

    def test_multiple_files_proper_lifecycle(self):
        report = _analyze(
            _open("FILE-A"),
            _open("FILE-B", "OUTPUT"),
            _read("FILE-A"),
            _write("REC-B", "FILE-B"),
            _close("FILE-A"),
            _close("FILE-B"),
        )
        assert not report.has_violations

    def test_stop_run_after_close(self):
        report = _analyze(_open("F"), _close("F"), _stop())
        assert not report.has_violations


# ---------------------------------------------------------------------------
# Violation: use before OPEN
# ---------------------------------------------------------------------------


class TestUseBeforeOpen:
    def test_read_before_open(self):
        report = _analyze(_read("MY-FILE"))
        assert report.has_violations
        assert report.violations[0].kind == IOViolationKind.READ_BEFORE_OPEN
        assert "MY-FILE" in report.violations[0].file_name

    def test_write_before_open(self):
        report = _analyze(_write("MY-REC", "MY-FILE"))
        assert report.has_violations
        assert report.violations[0].kind == IOViolationKind.WRITE_BEFORE_OPEN

    def test_rewrite_before_open(self):
        report = _analyze(_rewrite("MY-REC", "MY-FILE"))
        assert report.has_violations
        assert report.violations[0].kind == IOViolationKind.REWRITE_BEFORE_OPEN

    def test_delete_before_open(self):
        report = _analyze(_delete("MY-FILE"))
        assert report.has_violations
        assert report.violations[0].kind == IOViolationKind.DELETE_BEFORE_OPEN

    def test_start_before_open(self):
        report = _analyze(_start("MY-FILE"))
        assert report.has_violations
        assert report.violations[0].kind == IOViolationKind.START_BEFORE_OPEN

    def test_read_after_close_is_also_violation(self):
        # Open → Read → Close → Read again: the second read must be flagged
        report = _analyze(_open("F"), _read("F"), _close("F"), _read("F"))
        kinds = [v.kind for v in report.violations]
        assert IOViolationKind.READ_BEFORE_OPEN in kinds


# ---------------------------------------------------------------------------
# Violation: DOUBLE_OPEN
# ---------------------------------------------------------------------------


class TestDoubleOpen:
    def test_double_open_same_file(self):
        report = _analyze(_open("MY-FILE"), _open("MY-FILE"))
        assert any(v.kind == IOViolationKind.DOUBLE_OPEN for v in report.violations)

    def test_double_open_different_files_no_violation(self):
        report = _analyze(_open("FILE-A"), _open("FILE-B"))
        assert not any(v.kind == IOViolationKind.DOUBLE_OPEN for v in report.violations)


# ---------------------------------------------------------------------------
# Violation: CLOSE_NOT_OPEN
# ---------------------------------------------------------------------------


class TestCloseNotOpen:
    def test_close_never_opened(self):
        report = _analyze(_close("MY-FILE"))
        assert any(v.kind == IOViolationKind.CLOSE_NOT_OPEN for v in report.violations)

    def test_double_close(self):
        """Second CLOSE of the same file emits DOUBLE_CLOSE, not CLOSE_NOT_OPEN."""
        report = _analyze(_open("F"), _close("F"), _close("F"))
        kinds = [v.kind for v in report.violations]
        assert IOViolationKind.DOUBLE_CLOSE in kinds
        assert IOViolationKind.CLOSE_NOT_OPEN not in kinds


# ---------------------------------------------------------------------------
# Violation: FILE_LEFT_OPEN
# ---------------------------------------------------------------------------


class TestFileLeftOpen:
    def test_open_without_close_at_stop_run(self):
        report = _analyze(_open("MY-FILE"), _stop())
        kinds = [v.kind for v in report.violations]
        assert IOViolationKind.FILE_LEFT_OPEN in kinds

    def test_open_without_close_at_goback(self):
        report = _analyze(_open("MY-FILE"), _goback())
        kinds = [v.kind for v in report.violations]
        assert IOViolationKind.FILE_LEFT_OPEN in kinds

    def test_open_without_close_at_end_of_program(self):
        # No explicit STOP RUN: analyze() adds FILE_LEFT_OPEN for remaining open files
        report = _analyze(_open("MY-FILE"))
        # FILE_LEFT_OPEN emitted either in the body (STOP) or at end of analyze()
        kinds = [v.kind for v in report.violations]
        assert IOViolationKind.FILE_LEFT_OPEN in kinds

    def test_multiple_files_left_open(self):
        report = _analyze(_open("FILE-A"), _open("FILE-B"), _stop())
        left_open = [
            v for v in report.violations if v.kind == IOViolationKind.FILE_LEFT_OPEN
        ]
        file_names = {v.file_name.upper() for v in left_open}
        assert "FILE-A" in file_names
        assert "FILE-B" in file_names


# ---------------------------------------------------------------------------
# Multiple violations
# ---------------------------------------------------------------------------


class TestMultipleViolations:
    def test_read_and_write_before_open(self):
        report = _analyze(_read("A"), _write("B-REC", "B"))
        assert len(report.violations) >= 2

    def test_open_then_left_open_plus_read_on_another(self):
        report = _analyze(
            _open("FILE-A"),
            _read("FILE-B"),  # before open
            _stop(),  # FILE-A left open
        )
        kinds = {v.kind for v in report.violations}
        assert IOViolationKind.READ_BEFORE_OPEN in kinds
        assert IOViolationKind.FILE_LEFT_OPEN in kinds


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_empty_file_name_skipped(self):
        """Operations with empty file names should not emit violations."""
        report = _analyze(_read(""))
        assert not report.has_violations

    def test_case_insensitive_tracking(self):
        """File names should be tracked case-insensitively."""
        report = _analyze(_open("my-file"), _read("MY-FILE"), _close("MY-FILE"))
        assert not report.has_violations

    def test_open_stores_via_file_names_list(self):
        """Verify _get_open_files reads IOOpenStatement.file_names correctly."""
        stmt = _open("TEST-FILE")
        assert "TEST-FILE" in stmt.file_names


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------


class TestIOSequenceSerialization:
    def test_violation_to_dict(self):
        v = IOSequenceViolation(
            kind=IOViolationKind.READ_BEFORE_OPEN,
            file_name="MY-FILE",
            location=_LOC,
            message="READ on file 'MY-FILE' before it was OPENed",
        )
        d = v.to_dict()
        assert d["kind"] == "READ_BEFORE_OPEN"
        assert d["file_name"] == "MY-FILE"
        assert d["location"]["line"] == 1
        assert "READ" in d["message"]

    def test_violation_to_dict_no_location(self):
        v = IOSequenceViolation(
            kind=IOViolationKind.FILE_LEFT_OPEN,
            file_name="F",
            location=None,
            message="left open",
        )
        d = v.to_dict()
        assert d["location"] is None

    def test_report_to_dict_is_json_serializable(self):
        report = _analyze(_open("F"), _stop())
        json.dumps(report.to_dict())  # must not raise

    def test_report_to_dict_structure(self):
        report = _analyze()
        d = report.to_dict()
        assert "has_violations" in d
        assert "violation_count" in d
        assert "violations" in d
        assert d["has_violations"] is False
        assert d["violation_count"] == 0

    def test_exported_from_package(self):
        from cobolparser import IOSequenceAnalyzer as A
        from cobolparser import IOSequenceReport as R
        from cobolparser import IOSequenceViolation as V
        from cobolparser import IOViolationKind as K

        assert A is IOSequenceAnalyzer
        assert R is IOSequenceReport
        assert V is IOSequenceViolation
        assert K is IOViolationKind


# ---------------------------------------------------------------------------
# Round-trip via parse_cobol()
# ---------------------------------------------------------------------------


class TestIOSequenceRoundTrip:
    def test_well_formed_program_no_violations(self):
        src = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TESTPROG.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT MY-FILE ASSIGN TO 'MYFILE.DAT'.
       DATA DIVISION.
       FILE SECTION.
       FD MY-FILE.
       01 MY-REC PIC X(80).
       PROCEDURE DIVISION.
       MAIN-LOGIC.
           OPEN INPUT MY-FILE
           READ MY-FILE
           CLOSE MY-FILE
           STOP RUN.
"""
        result = parse_cobol(src)
        assert result.ast is not None
        report = IOSequenceAnalyzer().analyze(result.ast)
        # A well-formed OPEN → READ → CLOSE program has no violations at all.
        assert report.has_violations is False
        assert report.violations == []


# ---------------------------------------------------------------------------
# Additional edge cases
# ---------------------------------------------------------------------------


class TestMultipleFilesInOneStatement:
    """OPEN / CLOSE with multiple files in a single statement."""

    def test_open_two_files_both_tracked(self):
        """A single IOOpenStatement with two files should track both."""
        open_stmt = IOOpenStatement(_LOC)
        open_stmt.set_open_mode("INPUT")
        open_stmt.add_file("FILE-A")
        open_stmt.add_file("FILE-B")
        prog = _make_program(open_stmt, _close("FILE-A"), _close("FILE-B"))
        report = IOSequenceAnalyzer().analyze(prog)
        assert not report.has_violations

    def test_open_two_files_only_one_closed_leaves_other_open(self):
        open_stmt = IOOpenStatement(_LOC)
        open_stmt.set_open_mode("INPUT")
        open_stmt.add_file("FILE-A")
        open_stmt.add_file("FILE-B")
        prog = _make_program(open_stmt, _close("FILE-A"), _stop())
        report = IOSequenceAnalyzer().analyze(prog)
        left_open = [
            v for v in report.violations if v.kind == IOViolationKind.FILE_LEFT_OPEN
        ]
        assert len(left_open) == 1
        assert left_open[0].file_name.upper() == "FILE-B"

    def test_open_two_files_double_open_one(self):
        open_stmt = IOOpenStatement(_LOC)
        open_stmt.set_open_mode("INPUT")
        open_stmt.add_file("FILE-A")
        open_stmt.add_file("FILE-B")
        prog = _make_program(open_stmt, _open("FILE-B"))
        report = IOSequenceAnalyzer().analyze(prog)
        assert any(v.kind == IOViolationKind.DOUBLE_OPEN for v in report.violations)


class TestOpenModes:
    """Different OPEN modes (INPUT / OUTPUT / I-O / EXTEND) should all register the file."""

    def test_open_output_write_close(self):
        report = _analyze(
            _open("OUTFILE", "OUTPUT"),
            _write("REC", "OUTFILE"),
            _close("OUTFILE"),
        )
        assert not report.has_violations

    def test_open_io_read_write_close(self):
        report = _analyze(
            _open("IOFILE", "I-O"),
            _read("IOFILE"),
            _rewrite("REC", "IOFILE"),
            _close("IOFILE"),
        )
        assert not report.has_violations

    def test_open_extend_write_close(self):
        report = _analyze(
            _open("EXTFILE", "EXTEND"),
            _write("REC", "EXTFILE"),
            _close("EXTFILE"),
        )
        assert not report.has_violations


class TestReopenAfterClose:
    """Closing then reopening a file is legal — should not emit violations."""

    def test_reopen_valid(self):
        report = _analyze(
            _open("F"),
            _read("F"),
            _close("F"),
            _open("F"),
            _read("F"),
            _close("F"),
        )
        assert not report.has_violations

    def test_use_after_reopen_valid(self):
        report = _analyze(
            _open("F"),
            _close("F"),
            _open("F", "OUTPUT"),
            _write("REC", "F"),
            _close("F"),
        )
        assert not report.has_violations


class TestAnalyzerStateReset:
    """analyze() must fully reset internal state between calls."""

    def test_second_call_does_not_carry_open_files_from_first(self):
        analyzer = IOSequenceAnalyzer()
        # First call: opens FILE-A but never closes it
        prog1 = _make_program(_open("FILE-A"))
        analyzer.analyze(prog1)

        # Second call: clean program with no IO — should report no violations
        prog2 = _make_program()
        report2 = analyzer.analyze(prog2)
        assert not report2.has_violations

    def test_second_call_independent_violations(self):
        analyzer = IOSequenceAnalyzer()
        analyzer.analyze(_make_program(_open("FILE-A"), _stop()))  # first run
        report2 = analyzer.analyze(_make_program(_read("FILE-B")))  # second run
        # Only FILE-B violation from the second run
        names = {v.file_name.upper() for v in report2.violations}
        assert "FILE-B" in names
        assert "FILE-A" not in names


class TestMismatchedFileName:
    """READ/WRITE with a file name that doesn't match what was opened."""

    def test_read_wrong_file_after_open(self):
        report = _analyze(_open("FILE-A"), _read("FILE-B"))
        assert any(
            v.kind == IOViolationKind.READ_BEFORE_OPEN for v in report.violations
        )
        assert report.violations[0].file_name.upper() == "FILE-B"

    def test_write_wrong_file_after_open(self):
        report = _analyze(_open("FILE-A", "OUTPUT"), _write("REC", "FILE-B"))
        assert any(
            v.kind == IOViolationKind.WRITE_BEFORE_OPEN for v in report.violations
        )


class TestViolationMessages:
    """Violation messages must contain actionable information."""

    def test_read_before_open_message_contains_verb_and_file(self):
        report = _analyze(_read("MY-FILE"))
        msg = report.violations[0].message
        assert "READ" in msg
        assert "MY-FILE" in msg

    def test_double_open_message_contains_file(self):
        report = _analyze(_open("F"), _open("F"))
        v = next(v for v in report.violations if v.kind == IOViolationKind.DOUBLE_OPEN)
        assert "F" in v.message

    def test_file_left_open_message_contains_file(self):
        report = _analyze(_open("BIGFILE"), _stop())
        v = next(
            v for v in report.violations if v.kind == IOViolationKind.FILE_LEFT_OPEN
        )
        assert "BIGFILE" in v.message

    def test_close_not_open_message_contains_file(self):
        report = _analyze(_close("GHOST-FILE"))
        v = next(
            v for v in report.violations if v.kind == IOViolationKind.CLOSE_NOT_OPEN
        )
        assert "GHOST-FILE" in v.message
