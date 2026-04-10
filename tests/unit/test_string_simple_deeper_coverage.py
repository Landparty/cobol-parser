"""Deeper coverage tests for string_unstring_parsers.py and simple_statement_parsers.py.

Targets missing branch coverage across both parser modules.
"""

import pytest

from cobolparser import CobolParser, ErrorRecoveryMode
from cobolparser.models.statements.data import StringStatement, UnstringStatement
from cobolparser.models.statements.misc import (
    AlterStatement,
    CancelStatement,
    ContinueStatement,
    ExitStatement,
    GenerateStatement,
    GobackStatement,
    ReleaseStatement,
    ReturnStatement,
    UseStatement,
)


def _make_source(procedure_body: str, extra_data: str = "") -> str:
    return (
        "       IDENTIFICATION DIVISION.\n"
        "       PROGRAM-ID. TEST-PROG.\n"
        "       DATA DIVISION.\n"
        "       WORKING-STORAGE SECTION.\n"
        "       01 WS-TARGET PIC X(50).\n"
        "       01 WS-SOURCE PIC X(20) VALUE 'HELLO'.\n"
        "       01 WS-SOURCE2 PIC X(20) VALUE 'WORLD'.\n"
        "       01 WS-DELIM PIC X VALUE ','.\n"
        "       01 WS-PTR PIC 9(4) VALUE 1.\n"
        "       01 WS-TALLY PIC 9(4) VALUE 0.\n"
        "       01 WS-OUT1 PIC X(10).\n"
        "       01 WS-OUT2 PIC X(10).\n"
        "       01 WS-DLIM-OUT PIC X(1).\n"
        "       01 WS-CNT PIC 9(4).\n"
        "       01 WS-RC PIC 9(4).\n"
        f"{extra_data}"
        "       PROCEDURE DIVISION.\n"
        "       MAIN-LOGIC.\n"
        f"{procedure_body}\n"
    )


def _parse(src):
    parser = CobolParser(error_recovery=ErrorRecoveryMode.COLLECT_ALL)
    return parser.parse(src)


def _find_stmt(result, stmt_type):
    proc = result.ast.procedure_division
    for p in proc.paragraphs:
        for s in p.statements:
            if isinstance(s, stmt_type):
                return s
    return None


def _find_all_stmts(result, stmt_type):
    found = []
    proc = result.ast.procedure_division
    for p in proc.paragraphs:
        for s in p.statements:
            if isinstance(s, stmt_type):
                found.append(s)
    return found


# =====================================================================
# STRING statement tests
# =====================================================================


class TestStringStatementParser:
    """Tests for StringStatementParser covering missing branches."""

    def test_string_delimited_by_into_with_pointer(self):
        """STRING with DELIMITED BY, INTO, and WITH POINTER clauses."""
        src = _make_source(
            "           STRING WS-SOURCE DELIMITED BY WS-DELIM\n"
            "               INTO WS-TARGET\n"
            "               WITH POINTER WS-PTR.\n"
        )
        result = _parse(src)
        stmt = _find_stmt(result, StringStatement)
        assert stmt is not None
        assert stmt.into_target == "WS-TARGET"
        assert stmt.pointer_variable == "WS-PTR"
        assert len(stmt.delimiters) >= 1

    def test_string_on_overflow_with_display(self):
        """STRING with ON OVERFLOW containing a DISPLAY statement."""
        src = _make_source(
            "           STRING WS-SOURCE DELIMITED BY WS-DELIM\n"
            "               INTO WS-TARGET\n"
            "               ON OVERFLOW\n"
            "                   DISPLAY 'OVERFLOW OCCURRED'\n"
            "           END-STRING.\n"
        )
        result = _parse(src)
        stmt = _find_stmt(result, StringStatement)
        assert stmt is not None
        assert stmt.into_target == "WS-TARGET"
        assert stmt.on_overflow is not None
        assert len(stmt.on_overflow) > 0

    def test_string_not_on_overflow_with_display(self):
        """STRING with NOT ON OVERFLOW containing a DISPLAY statement."""
        src = _make_source(
            "           STRING WS-SOURCE DELIMITED BY WS-DELIM\n"
            "               INTO WS-TARGET\n"
            "               NOT ON OVERFLOW\n"
            "                   DISPLAY 'SUCCESS'\n"
            "           END-STRING.\n"
        )
        result = _parse(src)
        stmt = _find_stmt(result, StringStatement)
        assert stmt is not None
        assert stmt.not_on_overflow is not None
        assert len(stmt.not_on_overflow) > 0

    def test_string_end_string_terminator(self):
        """STRING with END-STRING scope terminator."""
        src = _make_source(
            "           STRING WS-SOURCE DELIMITED BY WS-DELIM\n"
            "               INTO WS-TARGET\n"
            "           END-STRING.\n"
        )
        result = _parse(src)
        stmt = _find_stmt(result, StringStatement)
        assert stmt is not None
        assert stmt.into_target == "WS-TARGET"

    def test_string_standalone_overflow(self):
        """STRING with standalone OVERFLOW (no ON prefix)."""
        src = _make_source(
            "           STRING WS-SOURCE DELIMITED BY WS-DELIM\n"
            "               INTO WS-TARGET\n"
            "               OVERFLOW\n"
            "                   DISPLAY 'OVERFLOW'\n"
            "           END-STRING.\n"
        )
        result = _parse(src)
        stmt = _find_stmt(result, StringStatement)
        assert stmt is not None
        assert stmt.on_overflow is not None
        assert len(stmt.on_overflow) > 0

    def test_string_period_terminated(self):
        """STRING terminated by period (no END-STRING)."""
        src = _make_source(
            "           STRING WS-SOURCE DELIMITED BY WS-DELIM\n"
            "               INTO WS-TARGET.\n"
        )
        result = _parse(src)
        stmt = _find_stmt(result, StringStatement)
        assert stmt is not None
        assert stmt.into_target == "WS-TARGET"

    def test_string_multiple_sources(self):
        """STRING with multiple source operands."""
        src = _make_source(
            "           STRING WS-SOURCE WS-SOURCE2\n"
            "               DELIMITED BY WS-DELIM\n"
            "               INTO WS-TARGET\n"
            "           END-STRING.\n"
        )
        result = _parse(src)
        stmt = _find_stmt(result, StringStatement)
        assert stmt is not None
        assert len(stmt.operands) >= 2

    def test_string_on_overflow_and_not_on_overflow(self):
        """STRING with both ON OVERFLOW and NOT ON OVERFLOW."""
        src = _make_source(
            "           STRING WS-SOURCE DELIMITED BY WS-DELIM\n"
            "               INTO WS-TARGET\n"
            "               ON OVERFLOW\n"
            "                   DISPLAY 'ERR'\n"
            "               NOT ON OVERFLOW\n"
            "                   DISPLAY 'OK'\n"
            "           END-STRING.\n"
        )
        result = _parse(src)
        stmt = _find_stmt(result, StringStatement)
        assert stmt is not None
        assert stmt.on_overflow is not None
        assert stmt.not_on_overflow is not None

    def test_string_not_overflow_without_on(self):
        """STRING with NOT OVERFLOW (missing ON keyword)."""
        src = _make_source(
            "           STRING WS-SOURCE DELIMITED BY WS-DELIM\n"
            "               INTO WS-TARGET\n"
            "               NOT OVERFLOW\n"
            "                   DISPLAY 'OK'\n"
            "           END-STRING.\n"
        )
        result = _parse(src)
        stmt = _find_stmt(result, StringStatement)
        assert stmt is not None
        # NOT without ON should still find OVERFLOW and parse it
        assert stmt.not_on_overflow is not None

    def test_string_with_pointer_only(self):
        """STRING WITH POINTER without INTO (edge case)."""
        src = _make_source(
            "           STRING WS-SOURCE DELIMITED BY WS-DELIM\n"
            "               INTO WS-TARGET\n"
            "               WITH POINTER WS-PTR\n"
            "           END-STRING.\n"
        )
        result = _parse(src)
        stmt = _find_stmt(result, StringStatement)
        assert stmt is not None
        assert stmt.pointer_variable == "WS-PTR"

    def test_string_delimited_by_size(self):
        """STRING with DELIMITED BY SIZE (literal keyword as delimiter)."""
        src = _make_source(
            "           STRING WS-SOURCE DELIMITED BY SIZE\n"
            "               INTO WS-TARGET.\n"
        )
        result = _parse(src)
        stmt = _find_stmt(result, StringStatement)
        assert stmt is not None
        assert "SIZE" in stmt.delimiters


# =====================================================================
# UNSTRING statement tests
# =====================================================================


class TestUnstringStatementParser:
    """Tests for UnstringStatementParser covering missing branches."""

    def test_unstring_delimited_by_all(self):
        """UNSTRING with DELIMITED BY ALL delimiter."""
        src = _make_source(
            "           UNSTRING WS-SOURCE DELIMITED BY ALL WS-DELIM\n"
            "               INTO WS-OUT1 WS-OUT2.\n"
        )
        result = _parse(src)
        stmt = _find_stmt(result, UnstringStatement)
        assert stmt is not None
        assert stmt.source_operand == "WS-SOURCE"
        assert len(stmt.delimiters) >= 1
        assert len(stmt.into_targets) >= 2

    def test_unstring_into_with_delimiter_in_count_in(self):
        """UNSTRING with INTO target DELIMITER IN and COUNT IN."""
        src = _make_source(
            "           UNSTRING WS-SOURCE DELIMITED BY WS-DELIM\n"
            "               INTO WS-OUT1\n"
            "                   DELIMITER IN WS-DLIM-OUT\n"
            "                   COUNT IN WS-CNT.\n"
        )
        result = _parse(src)
        stmt = _find_stmt(result, UnstringStatement)
        assert stmt is not None
        assert len(stmt.into_targets) >= 1
        target_info = stmt.into_targets[0]
        assert target_info["target"] == "WS-OUT1"
        assert target_info["delimiter_var"] == "WS-DLIM-OUT"
        assert target_info["count_var"] == "WS-CNT"

    def test_unstring_on_overflow_and_not_on_overflow(self):
        """UNSTRING with ON OVERFLOW and NOT ON OVERFLOW."""
        src = _make_source(
            "           UNSTRING WS-SOURCE DELIMITED BY WS-DELIM\n"
            "               INTO WS-OUT1\n"
            "               ON OVERFLOW\n"
            "                   DISPLAY 'OVERFLOW'\n"
            "               NOT ON OVERFLOW\n"
            "                   DISPLAY 'OK'\n"
            "           END-UNSTRING.\n"
        )
        result = _parse(src)
        stmt = _find_stmt(result, UnstringStatement)
        assert stmt is not None
        assert stmt.on_overflow is not None
        assert len(stmt.on_overflow) > 0
        assert stmt.not_on_overflow is not None
        assert len(stmt.not_on_overflow) > 0

    def test_unstring_end_unstring_terminator(self):
        """UNSTRING with END-UNSTRING scope terminator."""
        src = _make_source(
            "           UNSTRING WS-SOURCE DELIMITED BY WS-DELIM\n"
            "               INTO WS-OUT1\n"
            "           END-UNSTRING.\n"
        )
        result = _parse(src)
        stmt = _find_stmt(result, UnstringStatement)
        assert stmt is not None
        assert stmt.source_operand == "WS-SOURCE"

    def test_unstring_with_pointer_and_tallying(self):
        """UNSTRING with WITH POINTER and TALLYING IN."""
        src = _make_source(
            "           UNSTRING WS-SOURCE DELIMITED BY WS-DELIM\n"
            "               INTO WS-OUT1\n"
            "               WITH POINTER WS-PTR\n"
            "               TALLYING IN WS-TALLY.\n"
        )
        result = _parse(src)
        stmt = _find_stmt(result, UnstringStatement)
        assert stmt is not None
        assert stmt.pointer_variable == "WS-PTR"

    def test_unstring_multiple_into_targets(self):
        """UNSTRING with multiple INTO targets each with DELIMITER IN and COUNT IN."""
        src = _make_source(
            "           UNSTRING WS-SOURCE DELIMITED BY WS-DELIM\n"
            "               INTO WS-OUT1\n"
            "                   DELIMITER IN WS-DLIM-OUT\n"
            "                   COUNT IN WS-CNT\n"
            "               WS-OUT2.\n"
        )
        result = _parse(src)
        stmt = _find_stmt(result, UnstringStatement)
        assert stmt is not None
        assert len(stmt.into_targets) >= 2
        # First target should have delimiter and count vars
        first = stmt.into_targets[0]
        assert first["target"] == "WS-OUT1"
        assert first["delimiter_var"] == "WS-DLIM-OUT"
        assert first["count_var"] == "WS-CNT"
        # Second target
        second = stmt.into_targets[1]
        assert second["target"] == "WS-OUT2"

    def test_unstring_period_terminated(self):
        """UNSTRING terminated by period (no END-UNSTRING)."""
        src = _make_source(
            "           UNSTRING WS-SOURCE DELIMITED BY WS-DELIM\n"
            "               INTO WS-OUT1.\n"
        )
        result = _parse(src)
        stmt = _find_stmt(result, UnstringStatement)
        assert stmt is not None
        assert stmt.source_operand == "WS-SOURCE"

    def test_unstring_not_overflow_without_on(self):
        """UNSTRING with NOT OVERFLOW (missing ON keyword)."""
        src = _make_source(
            "           UNSTRING WS-SOURCE DELIMITED BY WS-DELIM\n"
            "               INTO WS-OUT1\n"
            "               NOT OVERFLOW\n"
            "                   DISPLAY 'OK'\n"
            "           END-UNSTRING.\n"
        )
        result = _parse(src)
        stmt = _find_stmt(result, UnstringStatement)
        assert stmt is not None
        # NOT without ON should still find OVERFLOW and parse it
        assert stmt.not_on_overflow is not None

    def test_unstring_into_delimiter_without_in(self):
        """UNSTRING with DELIMITER (no IN keyword) in INTO target."""
        src = _make_source(
            "           UNSTRING WS-SOURCE DELIMITED BY WS-DELIM\n"
            "               INTO WS-OUT1\n"
            "                   DELIMITER WS-DLIM-OUT.\n"
        )
        result = _parse(src)
        stmt = _find_stmt(result, UnstringStatement)
        assert stmt is not None
        assert len(stmt.into_targets) >= 1

    def test_unstring_into_count_without_in(self):
        """UNSTRING with COUNT (no IN keyword) in INTO target."""
        src = _make_source(
            "           UNSTRING WS-SOURCE DELIMITED BY WS-DELIM\n"
            "               INTO WS-OUT1\n"
            "                   COUNT WS-CNT.\n"
        )
        result = _parse(src)
        stmt = _find_stmt(result, UnstringStatement)
        assert stmt is not None
        assert len(stmt.into_targets) >= 1


# =====================================================================
# SIMPLE STATEMENT PARSER tests
# =====================================================================


class TestContinueStatementParser:
    """Tests for ContinueStatementParser."""

    def test_continue_basic(self):
        """CONTINUE statement - basic case."""
        src = _make_source("           CONTINUE.\n")
        result = _parse(src)
        stmt = _find_stmt(result, ContinueStatement)
        assert stmt is not None


class TestExitStatementParser:
    """Tests for ExitStatementParser covering missing branches."""

    def test_exit_program(self):
        """EXIT PROGRAM."""
        src = _make_source("           EXIT PROGRAM.\n")
        result = _parse(src)
        stmt = _find_stmt(result, ExitStatement)
        assert stmt is not None
        assert stmt.exit_type == "PROGRAM"

    def test_exit_section(self):
        """EXIT SECTION."""
        src = _make_source("           EXIT SECTION.\n")
        result = _parse(src)
        stmt = _find_stmt(result, ExitStatement)
        assert stmt is not None
        assert stmt.exit_type == "SECTION"

    def test_exit_paragraph(self):
        """EXIT PARAGRAPH."""
        src = _make_source("           EXIT PARAGRAPH.\n")
        result = _parse(src)
        stmt = _find_stmt(result, ExitStatement)
        assert stmt is not None
        assert stmt.exit_type == "PARAGRAPH"

    def test_exit_perform_cycle(self):
        """EXIT PERFORM CYCLE."""
        src = _make_source("           EXIT PERFORM CYCLE.\n")
        result = _parse(src)
        stmt = _find_stmt(result, ExitStatement)
        assert stmt is not None
        assert stmt.exit_type == "PERFORM CYCLE"

    def test_exit_perform_without_cycle(self):
        """EXIT PERFORM (without CYCLE)."""
        src = _make_source("           EXIT PERFORM.\n")
        result = _parse(src)
        stmt = _find_stmt(result, ExitStatement)
        assert stmt is not None
        assert stmt.exit_type == "PERFORM"

    def test_exit_bare(self):
        """EXIT (bare, no qualifier)."""
        src = _make_source("           EXIT.\n")
        result = _parse(src)
        stmt = _find_stmt(result, ExitStatement)
        assert stmt is not None
        assert stmt.exit_type is None


class TestGobackStatementParser:
    """Tests for GobackStatementParser covering missing branches."""

    def test_goback_basic(self):
        """GOBACK - basic."""
        src = _make_source("           GOBACK.\n")
        result = _parse(src)
        stmt = _find_stmt(result, GobackStatement)
        assert stmt is not None
        assert stmt.returning_value is None

    def test_goback_returning(self):
        """GOBACK RETURNING value."""
        src = _make_source("           GOBACK RETURNING WS-RC.\n")
        result = _parse(src)
        stmt = _find_stmt(result, GobackStatement)
        assert stmt is not None
        assert stmt.returning_value == "WS-RC"


class TestCancelStatementParser:
    """Tests for CancelStatementParser covering missing branches."""

    def test_cancel_single(self):
        """CANCEL with single program name."""
        src = _make_source("           CANCEL 'PROG1'.\n")
        result = _parse(src)
        stmt = _find_stmt(result, CancelStatement)
        assert stmt is not None
        assert len(stmt.program_names) >= 1

    def test_cancel_multiple_programs(self):
        """CANCEL with multiple program names."""
        src = _make_source("           CANCEL 'PROG1' 'PROG2'.\n")
        result = _parse(src)
        stmt = _find_stmt(result, CancelStatement)
        assert stmt is not None
        assert len(stmt.program_names) >= 2

    def test_cancel_identifier(self):
        """CANCEL with identifier program name."""
        src = _make_source("           CANCEL WS-SOURCE.\n")
        result = _parse(src)
        stmt = _find_stmt(result, CancelStatement)
        assert stmt is not None
        assert len(stmt.program_names) >= 1


class TestAlterStatementParser:
    """Tests for AlterStatementParser covering missing branches."""

    def test_alter_basic(self):
        """ALTER para-1 TO para-2."""
        src = _make_source(
            "           ALTER PARA-1 TO PARA-2.\n"
            "       PARA-1.\n"
            "           DISPLAY 'A'.\n"
            "       PARA-2.\n"
            "           DISPLAY 'B'.\n"
        )
        result = _parse(src)
        stmt = _find_stmt(result, AlterStatement)
        assert stmt is not None
        assert len(stmt.alterations) >= 1
        assert stmt.alterations[0]["from_paragraph"] == "PARA-1"
        assert stmt.alterations[0]["to_paragraph"] == "PARA-2"

    def test_alter_proceed_to(self):
        """ALTER para-1 TO PROCEED TO para-2."""
        src = _make_source(
            "           ALTER PARA-1 TO PROCEED TO PARA-2.\n"
            "       PARA-1.\n"
            "           DISPLAY 'A'.\n"
            "       PARA-2.\n"
            "           DISPLAY 'B'.\n"
        )
        result = _parse(src)
        stmt = _find_stmt(result, AlterStatement)
        assert stmt is not None
        assert len(stmt.alterations) >= 1
        assert stmt.alterations[0]["from_paragraph"] == "PARA-1"
        assert stmt.alterations[0]["to_paragraph"] == "PARA-2"


class TestGenerateStatementParser:
    """Tests for GenerateStatementParser covering missing branches."""

    def test_generate_report(self):
        """GENERATE report-name."""
        src = _make_source("           GENERATE SALES-REPORT.\n")
        result = _parse(src)
        stmt = _find_stmt(result, GenerateStatement)
        assert stmt is not None
        assert stmt.report_name == "SALES-REPORT"


class TestReleaseStatementParser:
    """Tests for ReleaseStatementParser covering missing branches."""

    def test_release_basic(self):
        """RELEASE record-name."""
        src = _make_source("           RELEASE SORT-REC.\n")
        result = _parse(src)
        stmt = _find_stmt(result, ReleaseStatement)
        assert stmt is not None
        assert stmt.record_name == "SORT-REC"
        assert stmt.from_source is None

    def test_release_from_source(self):
        """RELEASE record-name FROM source."""
        src = _make_source("           RELEASE SORT-REC FROM WS-SOURCE.\n")
        result = _parse(src)
        stmt = _find_stmt(result, ReleaseStatement)
        assert stmt is not None
        assert stmt.record_name == "SORT-REC"
        assert stmt.from_source == "WS-SOURCE"


class TestReturnStatementParser:
    """Tests for ReturnStatementParser covering missing branches."""

    def test_return_with_at_end(self):
        """RETURN file-name RECORD INTO target AT END DISPLAY 'done'."""
        src = _make_source(
            "           RETURN SORT-FILE RECORD INTO WS-TARGET\n"
            "               AT END\n"
            "                   DISPLAY 'DONE'.\n"
        )
        result = _parse(src)
        stmt = _find_stmt(result, ReturnStatement)
        assert stmt is not None
        assert stmt.file_name == "SORT-FILE"
        assert stmt.into_target == "WS-TARGET"
        assert stmt.at_end_clause is not None
        assert len(stmt.at_end_clause) > 0

    def test_return_with_not_at_end(self):
        """RETURN with NOT AT END clause."""
        src = _make_source(
            "           RETURN SORT-FILE RECORD INTO WS-TARGET\n"
            "               AT END\n"
            "                   DISPLAY 'END'\n"
            "               NOT AT END\n"
            "                   DISPLAY 'MORE'.\n"
        )
        result = _parse(src)
        stmt = _find_stmt(result, ReturnStatement)
        assert stmt is not None
        assert stmt.at_end_clause is not None
        assert stmt.not_at_end_clause is not None

    def test_return_without_into(self):
        """RETURN file-name AT END (no INTO clause)."""
        src = _make_source(
            "           RETURN SORT-FILE\n"
            "               AT END\n"
            "                   DISPLAY 'DONE'.\n"
        )
        result = _parse(src)
        stmt = _find_stmt(result, ReturnStatement)
        assert stmt is not None
        assert stmt.file_name == "SORT-FILE"
        assert stmt.into_target is None
        assert stmt.at_end_clause is not None

    def test_return_with_record_keyword(self):
        """RETURN with RECORD keyword (no INTO)."""
        src = _make_source(
            "           RETURN SORT-FILE RECORD\n"
            "               AT END\n"
            "                   DISPLAY 'DONE'.\n"
        )
        result = _parse(src)
        stmt = _find_stmt(result, ReturnStatement)
        assert stmt is not None
        assert stmt.file_name == "SORT-FILE"

    def test_return_not_at_end_without_at(self):
        """RETURN with NOT END (missing AT keyword) edge case."""
        src = _make_source(
            "           RETURN SORT-FILE\n"
            "               NOT END\n"
            "                   DISPLAY 'OK'.\n"
        )
        result = _parse(src)
        stmt = _find_stmt(result, ReturnStatement)
        assert stmt is not None
        # The parser should handle NOT without AT followed by END

    def test_return_period_terminated(self):
        """RETURN terminated by period only."""
        src = _make_source("           RETURN SORT-FILE.\n")
        result = _parse(src)
        stmt = _find_stmt(result, ReturnStatement)
        assert stmt is not None
        assert stmt.file_name == "SORT-FILE"


class TestUseStatementParser:
    """Tests for UseStatementParser covering missing branches."""

    def test_use_global_exception_on_input(self):
        """USE GLOBAL AFTER STANDARD EXCEPTION PROCEDURE ON INPUT."""
        src = _make_source(
            "           USE GLOBAL AFTER STANDARD EXCEPTION\n"
            "               PROCEDURE ON INPUT.\n"
        )
        result = _parse(src)
        stmt = _find_stmt(result, UseStatement)
        assert stmt is not None
        assert stmt.is_global is True
        assert stmt.use_type == "EXCEPTION"
        assert "INPUT" in stmt.file_names

    def test_use_after_exception_on_file(self):
        """USE AFTER EXCEPTION PROCEDURE ON file-name."""
        src = _make_source(
            "           USE AFTER EXCEPTION PROCEDURE ON WS-TARGET.\n"
        )
        result = _parse(src)
        stmt = _find_stmt(result, UseStatement)
        assert stmt is not None
        assert stmt.is_global is False
        assert stmt.use_type == "EXCEPTION"
        assert len(stmt.file_names) >= 1

    def test_use_after_error(self):
        """USE AFTER ERROR PROCEDURE ON OUTPUT."""
        src = _make_source(
            "           USE AFTER ERROR PROCEDURE ON OUTPUT.\n"
        )
        result = _parse(src)
        stmt = _find_stmt(result, UseStatement)
        assert stmt is not None
        assert stmt.use_type == "ERROR"
        assert "OUTPUT" in stmt.file_names

    def test_use_debugging(self):
        """USE AFTER DEBUGGING ON identifier."""
        src = _make_source(
            "           USE AFTER DEBUGGING ON WS-TARGET.\n"
        )
        result = _parse(src)
        stmt = _find_stmt(result, UseStatement)
        assert stmt is not None
        assert stmt.use_type == "DEBUGGING"

    def test_use_after_exception_on_io(self):
        """USE AFTER EXCEPTION PROCEDURE ON I-O."""
        src = _make_source(
            "           USE AFTER EXCEPTION PROCEDURE ON I-O.\n"
        )
        result = _parse(src)
        stmt = _find_stmt(result, UseStatement)
        assert stmt is not None
        assert stmt.use_type == "EXCEPTION"
        assert "I-O" in stmt.file_names

    def test_use_after_exception_on_extend(self):
        """USE AFTER EXCEPTION PROCEDURE ON EXTEND."""
        src = _make_source(
            "           USE AFTER EXCEPTION PROCEDURE ON EXTEND.\n"
        )
        result = _parse(src)
        stmt = _find_stmt(result, UseStatement)
        assert stmt is not None
        assert "EXTEND" in stmt.file_names
