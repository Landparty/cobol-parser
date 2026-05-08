"""Tests for io_sequence.py paths not covered by existing tests.

Targets:
- _get_open_files() legacy open_files (list of dict/str) path (lines 294-303)
- _get_open_files() singular file_name attribute fallback (lines 304-307)
- _get_open_files() operands fallback (lines 308-311)
- Empty/whitespace file_name skipping in _handle_open (line 213) and
  _handle_close (line 233)
"""

from __future__ import annotations

from cobolparser.analysis.io_sequence import IOSequenceAnalyzer
from cobolparser.models.ast_base import SourceLocation
from cobolparser.models.program import CobolDivision, CobolParagraph, CobolProgram
from cobolparser.models.statements.io import IOCloseStatement, IOOpenStatement

_LOC = SourceLocation(1, 1)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_program(*statements) -> CobolProgram:
    prog = CobolProgram("TEST-PROG", _LOC)
    prog.add_division(CobolDivision("IDENTIFICATION", _LOC))
    proc_div = CobolDivision("PROCEDURE", _LOC)
    para = CobolParagraph("MAIN-LOGIC", _LOC)
    for stmt in statements:
        para.add_statement(stmt)
    proc_div.add_paragraph(para)
    prog.add_division(proc_div)
    return prog


def _open_with_legacy_dict(file_name: str) -> IOOpenStatement:
    """Build an IOOpenStatement whose file names are in the legacy open_files list."""
    stmt = IOOpenStatement(_LOC)
    stmt.set_open_mode("INPUT")
    # Simulate legacy open_files attribute (list of dicts)
    stmt.open_files = [{"file_name": file_name}]  # type: ignore[attr-defined]
    return stmt


def _open_with_legacy_dict_name_key(file_name: str) -> IOOpenStatement:
    """Legacy dict using 'name' key instead of 'file_name'."""
    stmt = IOOpenStatement(_LOC)
    stmt.set_open_mode("INPUT")
    stmt.open_files = [{"name": file_name}]  # type: ignore[attr-defined]
    return stmt


def _open_with_legacy_str(file_name: str) -> IOOpenStatement:
    """Legacy open_files is a list of plain strings."""
    stmt = IOOpenStatement(_LOC)
    stmt.set_open_mode("INPUT")
    stmt.open_files = [file_name]  # type: ignore[attr-defined]
    return stmt


def _open_with_singular_file_name(file_name: str) -> IOOpenStatement:
    """IOOpenStatement with file_name (singular) attribute but empty file_names."""
    stmt = IOOpenStatement(_LOC)
    stmt.set_open_mode("INPUT")
    # file_names is populated by add_file(); skip that so we fall through
    # Then set a singular file_name attribute directly:
    stmt.file_name = file_name  # type: ignore[attr-defined]
    return stmt


def _open_with_operands(file_name: str) -> IOOpenStatement:
    """IOOpenStatement with only operands populated (last-resort fallback)."""
    stmt = IOOpenStatement(_LOC)
    stmt.set_open_mode("INPUT")
    stmt.operands = [file_name]
    return stmt


def _close_stmt() -> IOCloseStatement:
    stmt = IOCloseStatement(_LOC)
    stmt.add_file("SOME-FILE")
    return stmt


# ---------------------------------------------------------------------------
# _get_open_files() — legacy dict path
# ---------------------------------------------------------------------------


class TestGetOpenFilesLegacyDict:
    def test_legacy_dict_file_name_key(self):
        stmt = _open_with_legacy_dict("MY-FILE")
        analyzer = IOSequenceAnalyzer()
        names = analyzer._get_open_files(stmt)
        assert "MY-FILE" in names

    def test_legacy_dict_name_key(self):
        stmt = _open_with_legacy_dict_name_key("OTHER-FILE")
        analyzer = IOSequenceAnalyzer()
        names = analyzer._get_open_files(stmt)
        assert "OTHER-FILE" in names

    def test_legacy_dict_empty_name_skipped(self):
        stmt = IOOpenStatement(_LOC)
        stmt.set_open_mode("INPUT")
        stmt.open_files = [{"file_name": ""}]  # type: ignore[attr-defined]
        analyzer = IOSequenceAnalyzer()
        names = analyzer._get_open_files(stmt)
        assert names == []

    def test_legacy_str_entry(self):
        stmt = _open_with_legacy_str("STR-FILE")
        analyzer = IOSequenceAnalyzer()
        names = analyzer._get_open_files(stmt)
        assert "STR-FILE" in names


# ---------------------------------------------------------------------------
# _get_open_files() — singular file_name fallback
# ---------------------------------------------------------------------------


class TestGetOpenFilesSingularFileName:
    def test_singular_file_name_returned(self):
        stmt = _open_with_singular_file_name("SING-FILE")
        analyzer = IOSequenceAnalyzer()
        names = analyzer._get_open_files(stmt)
        assert "SING-FILE" in names


# ---------------------------------------------------------------------------
# _get_open_files() — operands last-resort fallback
# ---------------------------------------------------------------------------


class TestGetOpenFilesOperandsFallback:
    def test_operands_returned_when_no_other_path(self):
        stmt = _open_with_operands("OP-FILE")
        analyzer = IOSequenceAnalyzer()
        names = analyzer._get_open_files(stmt)
        assert "OP-FILE" in names


# ---------------------------------------------------------------------------
# _handle_open() — empty/whitespace file name skipped
# ---------------------------------------------------------------------------


class TestHandleOpenEmptyName:
    def test_empty_string_file_name_skipped(self):
        stmt = IOOpenStatement(_LOC)
        stmt.set_open_mode("INPUT")
        # file_names populated via add_file with empty string — should be skipped
        stmt.file_names = [""]
        prog = _make_program(stmt)
        report = IOSequenceAnalyzer().analyze(prog)
        # No violation about empty names and nothing opened
        assert report.violations == []

    def test_whitespace_only_file_name_skipped(self):
        stmt = IOOpenStatement(_LOC)
        stmt.set_open_mode("INPUT")
        stmt.file_names = ["   "]
        prog = _make_program(stmt)
        report = IOSequenceAnalyzer().analyze(prog)
        assert report.violations == []


# ---------------------------------------------------------------------------
# _handle_close() — empty/whitespace file name skipped
# ---------------------------------------------------------------------------


class TestHandleCloseEmptyName:
    def test_empty_close_file_name_skipped(self):
        close_stmt = IOCloseStatement(_LOC)
        close_stmt.file_names = [""]
        prog = _make_program(close_stmt)
        report = IOSequenceAnalyzer().analyze(prog)
        # Closing an empty name should not generate a violation
        assert report.violations == []

    def test_whitespace_close_file_name_skipped(self):
        close_stmt = IOCloseStatement(_LOC)
        close_stmt.file_names = ["  "]
        prog = _make_program(close_stmt)
        report = IOSequenceAnalyzer().analyze(prog)
        assert report.violations == []
