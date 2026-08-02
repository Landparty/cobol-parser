"""PERFORM THRU support for all-digit procedure names.

COBOL allows procedure names made entirely of digits, and ``PERFORM 1000
THRU 1999`` numbering is idiomatic in THRU-style code. These names lex as
NUMERIC_LITERAL (or LEVEL_NUMBER for 1-2 digit values), never IDENTIFIER,
so both the paragraph-boundary detection and the PERFORM parser need
explicit support. Before that support existed, ``PERFORM 1000 THRU 1999``
consumed the numeric as a failed TIMES count and misparsed the rest of the
statement (target became the literal word ``THRU``), and the numeric
paragraph headers themselves were skipped as unsupported statements.
"""

from __future__ import annotations

from cobolparser import CobolParser, DeadCodeAnalyzer, ErrorRecoveryMode
from cobolparser.analysis.program_flow import ProgramFlowAnalyzer
from cobolparser.models.statements import PerformStatement


def _parse(source: str):
    return CobolParser(error_recovery=ErrorRecoveryMode.COLLECT_ALL).parse(source)


def _performs(result) -> list[PerformStatement]:
    return [
        s for s in result.ast.get_all_statements() if isinstance(s, PerformStatement)
    ]


NUMERIC_RANGE_SRC = """
       IDENTIFICATION DIVISION.
       PROGRAM-ID. NUMTHRU.
       PROCEDURE DIVISION.
       MAIN-PARA.
           PERFORM 1000 THRU 1999.
           STOP RUN.
       1000.
           DISPLAY 'A'.
       1500.
           DISPLAY 'B'.
       1999.
           DISPLAY 'C'.
"""


class TestNumericPerformThru:
    def test_numeric_range_target_and_thru_captured(self) -> None:
        result = _parse(NUMERIC_RANGE_SRC)
        assert result.success, f"Parse failed: {result.errors}"
        stmt = _performs(result)[0]
        assert stmt.target_paragraph == "1000"
        assert stmt.thru_paragraph == "1999"

    def test_numeric_paragraph_headers_become_procedures(self) -> None:
        result = _parse(NUMERIC_RANGE_SRC)
        proc_div = result.ast.get_division("PROCEDURE")
        names = [s.section_name for s in proc_div.sections]
        for expected in ("1000", "1500", "1999"):
            assert expected in names, f"paragraph {expected} missing from {names}"

    def test_numeric_thru_end_with_identifier_start(self) -> None:
        src = """
       IDENTIFICATION DIVISION.
       PROGRAM-ID. MIXTHRU.
       PROCEDURE DIVISION.
       MAIN-PARA.
           PERFORM PARA-A THRU 9999.
           STOP RUN.
       PARA-A.
           DISPLAY 'A'.
       9999.
           DISPLAY 'EXIT'.
"""
        result = _parse(src)
        assert result.success, f"Parse failed: {result.errors}"
        stmt = _performs(result)[0]
        assert stmt.target_paragraph == "PARA-A"
        assert stmt.thru_paragraph == "9999"

    def test_numeric_range_with_times(self) -> None:
        src = """
       IDENTIFICATION DIVISION.
       PROGRAM-ID. NUMTIMES.
       PROCEDURE DIVISION.
       MAIN-PARA.
           PERFORM 1000 THRU 1999 3 TIMES.
           STOP RUN.
       1000.
           DISPLAY 'A'.
       1999.
           DISPLAY 'B'.
"""
        result = _parse(src)
        assert result.success, f"Parse failed: {result.errors}"
        stmt = _performs(result)[0]
        assert stmt.target_paragraph == "1000"
        assert stmt.thru_paragraph == "1999"
        assert stmt.times_count == 3
        assert stmt.perform_type == "TIMES"

    def test_numeric_range_with_until(self) -> None:
        src = """
       IDENTIFICATION DIVISION.
       PROGRAM-ID. NUMUNTIL.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-X PIC 9 VALUE 0.
       PROCEDURE DIVISION.
       MAIN-PARA.
           PERFORM 1000 THRU 1999 UNTIL WS-X > 3.
           STOP RUN.
       1000.
           ADD 1 TO WS-X.
       1999.
           EXIT.
"""
        result = _parse(src)
        assert result.success, f"Parse failed: {result.errors}"
        stmt = _performs(result)[0]
        assert stmt.target_paragraph == "1000"
        assert stmt.thru_paragraph == "1999"
        assert stmt.perform_type == "UNTIL"
        assert stmt.until_condition is not None

    def test_numeric_range_through_synonym(self) -> None:
        src = """
       IDENTIFICATION DIVISION.
       PROGRAM-ID. NUMTHROUGH.
       PROCEDURE DIVISION.
       MAIN-PARA.
           PERFORM 2000 THROUGH 2999.
           STOP RUN.
       2000.
           DISPLAY 'A'.
       2999.
           DISPLAY 'B'.
"""
        result = _parse(src)
        assert result.success, f"Parse failed: {result.errors}"
        stmt = _performs(result)[0]
        assert stmt.target_paragraph == "2000"
        assert stmt.thru_paragraph == "2999"

    def test_simple_numeric_target_without_thru(self) -> None:
        src = """
       IDENTIFICATION DIVISION.
       PROGRAM-ID. NUMSIMPLE.
       PROCEDURE DIVISION.
       MAIN-PARA.
           PERFORM 2000.
           STOP RUN.
       2000.
           DISPLAY 'A'.
"""
        result = _parse(src)
        assert result.success, f"Parse failed: {result.errors}"
        stmt = _performs(result)[0]
        assert stmt.target_paragraph == "2000"
        assert stmt.thru_paragraph is None

    def test_small_numeric_names_level_number_tokens(self) -> None:
        # 1-2 digit values tokenize as LEVEL_NUMBER rather than
        # NUMERIC_LITERAL -- both must be accepted as procedure names.
        src = """
       IDENTIFICATION DIVISION.
       PROGRAM-ID. LVLTHRU.
       PROCEDURE DIVISION.
       MAIN-PARA.
           PERFORM 03 THRU 05.
           STOP RUN.
       03.
           DISPLAY 'A'.
       05.
           DISPLAY 'B'.
"""
        result = _parse(src)
        assert result.success, f"Parse failed: {result.errors}"
        stmt = _performs(result)[0]
        assert stmt.target_paragraph == "03"
        assert stmt.thru_paragraph == "05"

    def test_thru_end_on_continuation_line(self) -> None:
        # NIST NC107A shape: the THRU end name sits on the next source line
        # (and both names are long all-digit paragraph names), followed by a
        # TIMES clause. The parser must skip the newline after THRU instead
        # of reporting a missing end paragraph.
        src = """
       IDENTIFICATION DIVISION.
       PROGRAM-ID. NISTTHRU.
       PROCEDURE DIVISION.
       MAIN-PARA.
           PERFORM  000000000000000000000000001 THRU
                    00000000000000000000000000001 2 TIMES.
           STOP RUN.
       000000000000000000000000001.
           DISPLAY 'A'.
       00000000000000000000000000001.
           DISPLAY 'B'.
"""
        result = _parse(src)
        assert result.success, f"Parse failed: {result.errors}"
        stmt = _performs(result)[0]
        assert stmt.target_paragraph == "000000000000000000000000001"
        assert stmt.thru_paragraph == "00000000000000000000000000001"
        assert stmt.times_count == 2

    def test_inline_perform_n_times_still_works(self) -> None:
        # Regression guard: the numeric token followed by TIMES is still an
        # inline TIMES count, not a procedure name.
        src = """
       IDENTIFICATION DIVISION.
       PROGRAM-ID. INLINETIMES.
       PROCEDURE DIVISION.
       MAIN-PARA.
           PERFORM 5 TIMES
               DISPLAY 'LOOP'
           END-PERFORM.
           STOP RUN.
"""
        result = _parse(src)
        assert result.success, f"Parse failed: {result.errors}"
        stmt = _performs(result)[0]
        assert stmt.times_count == 5
        assert stmt.target_paragraph is None


class TestNumericThruAnalysis:
    def test_flow_graph_expands_numeric_range_members(self) -> None:
        result = _parse(NUMERIC_RANGE_SRC)
        report = ProgramFlowAnalyzer().analyze(result.ast)
        thru_edges = [e for e in report.edges if e.thru_target]
        assert thru_edges, "expected PERFORM/PERFORM_THRU edges with thru_target"
        for edge in thru_edges:
            assert edge.range_members == ["1000", "1500", "1999"]

    def test_dead_code_marks_numeric_range_referenced(self) -> None:
        result = _parse(NUMERIC_RANGE_SRC)
        report = DeadCodeAnalyzer().analyze(result.ast)
        dead_names = {item.name for item in report.dead_items}
        # The intermediate paragraph executes as part of the THRU range.
        assert "1500" not in dead_names

    def test_dead_code_still_flags_numeric_paragraph_outside_range(self) -> None:
        src = """
       IDENTIFICATION DIVISION.
       PROGRAM-ID. NUMDEAD.
       PROCEDURE DIVISION.
       MAIN-PARA.
           PERFORM 1000 THRU 1999.
           STOP RUN.
       1000.
           DISPLAY 'A'.
       1999.
           GO TO 9000.
       3000.
           DISPLAY 'NEVER'.
       9000.
           EXIT.
"""
        result = _parse(src)
        assert result.success, f"Parse failed: {result.errors}"
        report = DeadCodeAnalyzer().analyze(result.ast)
        dead_names = {item.name for item in report.dead_items}
        assert "3000" in dead_names
        # GO TO with a numeric target still counts as a reference.
        assert "9000" not in dead_names
