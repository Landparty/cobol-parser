"""Tests targeting uncovered branches in arithmetic_parsers.py.

Specifically targets:
- _parse_size_error_clauses: NEWLINE skipping between ON/SIZE/ERROR tokens (lines 118-174)
- _parse_nested_statements: MOVE with NEWLINE before target (lines 254-258)
- matches() exception paths (lines 41-42, 300-301, 364-365, 423-424, 484-485)
- SUBTRACT FROM clause (line 336-341)
- ADD TO GIVING combined path (lines 79-84)
- ADD GIVING without TO (lines 85-90)
"""

import pytest

from cobolparser.models.statements import (
    AddStatement,
    ComputeStatement,
    DivideStatement,
    MultiplyStatement,
    SubtractStatement,
)
from cobolparser.parser import CobolParser
from cobolparser.parsers.statements.arithmetic_parsers import (
    AddStatementParser,
    SubtractStatementParser,
)


def parse_procedure(code):
    """Parse COBOL and return procedure division statements."""
    src = (
        "       IDENTIFICATION DIVISION.\n"
        "       PROGRAM-ID. TEST-ARITH.\n"
        "       DATA DIVISION.\n"
        "       WORKING-STORAGE SECTION.\n"
        "       01 A PIC 9(4) VALUE 0.\n"
        "       01 B PIC 9(4) VALUE 10.\n"
        "       01 C PIC 9(4) VALUE 20.\n"
        "       01 D PIC 9(4) VALUE 5.\n"
        "       01 E PIC 9(4) VALUE 3.\n"
        "       PROCEDURE DIVISION.\n"
        f"{code}\n"
    )
    result = CobolParser().parse(src)
    proc = result.ast.procedure_division
    if proc.paragraphs:
        return proc.paragraphs[0].statements, result
    if proc.sections and proc.sections[0].paragraphs:
        return proc.sections[0].paragraphs[0].statements, result
    return [], result


def _find_stmt(stmts, stmt_type):
    for s in stmts:
        if isinstance(s, stmt_type):
            return s
    pytest.fail(f"No {stmt_type.__name__} found in {stmts}")


class TestAddOnSizeErrorWithNewlines:
    """Tests for ON SIZE ERROR with newlines between keywords (lines 118-120, 131-132)."""

    def test_add_on_size_error_newlines_between_keywords(self):
        """ON SIZE ERROR with NEWLINE tokens between ON, SIZE, and ERROR."""
        stmts, _ = parse_procedure(
            "           ADD A TO B\n"
            "               ON\n"
            "               SIZE\n"
            "               ERROR\n"
            '                   DISPLAY "Overflow".'
        )
        add_stmt = _find_stmt(stmts, AddStatement)
        assert add_stmt.on_size_error is not None

    def test_add_not_on_size_error_newlines_between_keywords(self):
        """NOT ON SIZE ERROR with NEWLINE tokens between NOT, ON, SIZE, ERROR."""
        stmts, _ = parse_procedure(
            "           ADD A TO B\n"
            "               NOT\n"
            "               ON\n"
            "               SIZE\n"
            "               ERROR\n"
            '                   DISPLAY "OK".'
        )
        add_stmt = _find_stmt(stmts, AddStatement)
        assert add_stmt.not_on_size_error is not None


class TestAddGivingVariants:
    """Tests for ADD ... GIVING without TO and ADD ... TO ... GIVING paths."""

    def test_add_giving_without_to(self):
        """ADD A B GIVING C (no TO clause) - lines 85-90."""
        stmts, _ = parse_procedure("           ADD A B GIVING C.")
        add_stmt = _find_stmt(stmts, AddStatement)
        d = add_stmt.to_dict()
        assert d["giving"] == "C"

    def test_add_to_giving(self):
        """ADD A TO B GIVING C - lines 79-84."""
        stmts, _ = parse_procedure("           ADD A TO B GIVING C.")
        add_stmt = _find_stmt(stmts, AddStatement)
        d = add_stmt.to_dict()
        assert d["giving"] == "C"


class TestSubtractFromGiving:
    """Test SUBTRACT with FROM and GIVING clauses."""

    def test_subtract_from_giving(self):
        """SUBTRACT A FROM B GIVING C."""
        stmts, _ = parse_procedure("           SUBTRACT A FROM B GIVING C.")
        stmt = _find_stmt(stmts, SubtractStatement)
        assert "A" in stmt.operands
        assert stmt.target == "B"
        assert stmt.giving == "C"

    def test_subtract_from_giving_on_continuation_line(self):
        """SUBTRACT A FROM B\\n    GIVING C. -- GIVING on its own line is
        ordinary free-form layout (this is the exact shape that appeared in
        legacy-application/cobol/LOANPMT.cbl and silently dropped the GIVING
        clause, producing a PARSE_WARNING when nested and a silent AST gap
        at top level)."""
        stmts, result = parse_procedure(
            "           SUBTRACT A FROM B\n" "               GIVING C."
        )
        stmt = _find_stmt(stmts, SubtractStatement)
        assert stmt.giving == "C"
        assert not result.warnings

    def test_subtract_from_giving_nested_in_if_else(self):
        """The real-world trigger: SUBTRACT ... FROM ... GIVING (split
        across lines) nested inside an IF/ELSE body, with no period until
        END-IF. Before the fix this produced a PARSE_WARNING ("Unparsed
        tokens starting at 'GIVING'") because the dangling GIVING clause
        was left for the next statement boundary to trip over."""
        stmts, result = parse_procedure(
            "           IF A = 1\n"
            '               DISPLAY "X"\n'
            "           ELSE\n"
            "               SUBTRACT A FROM B\n"
            "                   GIVING C\n"
            "           END-IF."
        )
        assert not result.warnings
        # The SUBTRACT lives inside the ELSE branch of the IfStatement.
        from cobolparser.models.statements import IfStatement

        if_stmt = _find_stmt(stmts, IfStatement)
        subtract = _find_stmt(if_stmt.else_statements, SubtractStatement)
        assert subtract.giving == "C"

    def test_subtract_giving_without_from(self):
        """SUBTRACT A GIVING C (direct GIVING path) - line 336-341."""
        stmts, _ = parse_procedure("           SUBTRACT A GIVING C.")
        stmt = _find_stmt(stmts, SubtractStatement)
        d = stmt.to_dict()
        assert d["giving"] == "C"


class TestNestedMoveWithNewlines:
    """Tests for _parse_nested_statements MOVE handling with NEWLINEs (lines 254-258)."""

    def test_nested_move_with_newline_before_target(self):
        """ON SIZE ERROR MOVE X TO\n Y - NEWLINE between TO and target."""
        stmts, _ = parse_procedure(
            "           ADD A TO B\n"
            "               ON SIZE ERROR\n"
            "                   MOVE 0\n"
            "                   TO\n"
            "                   C."
        )
        add_stmt = _find_stmt(stmts, AddStatement)
        assert add_stmt.on_size_error is not None
        move_stmts = [s for s in add_stmt.on_size_error if s.statement_type == "MOVE"]
        assert len(move_stmts) >= 1


class TestMatchesExceptionPaths:
    """Tests for matches() returning False when exception is raised (lines 41-42, etc.)."""

    def test_add_matches_exception_on_broken_stream(self):
        """AddStatementParser.matches() returns False on stream that throws."""

        class BrokenStream:
            def peek(self, offset=0):
                raise RuntimeError("broken")

            @property
            def context(self):
                return None

        parser = AddStatementParser()
        assert parser.matches(BrokenStream()) is False

    def test_subtract_matches_exception_on_broken_stream(self):
        """SubtractStatementParser.matches() returns False on stream that throws."""

        class BrokenStream:
            def peek(self, offset=0):
                raise RuntimeError("broken")

            @property
            def context(self):
                return None

        parser = SubtractStatementParser()
        assert parser.matches(BrokenStream()) is False


class TestComputeWithSizeErrorClauses:
    """Additional COMPUTE tests targeting size error branches."""

    def test_compute_on_size_error_with_nested_move(self):
        """COMPUTE with ON SIZE ERROR containing MOVE (lines 237-238)."""
        stmts, _ = parse_procedure(
            "           COMPUTE A = B + C\n"
            "               ON SIZE ERROR\n"
            "                   MOVE 0 TO A."
        )
        compute = _find_stmt(stmts, ComputeStatement)
        assert compute.on_size_error is not None
        move_stmts = [s for s in compute.on_size_error if s.statement_type == "MOVE"]
        assert len(move_stmts) >= 1

    def test_compute_not_on_size_error_standalone(self):
        """COMPUTE with NOT ON SIZE ERROR clause only."""
        stmts, _ = parse_procedure(
            "           COMPUTE A = B + 1\n"
            "               NOT ON SIZE ERROR\n"
            '                   DISPLAY "OK".'
        )
        compute = _find_stmt(stmts, ComputeStatement)
        assert compute.not_on_size_error is not None


class TestMultiplyDivideEdgeCases:
    """Edge cases for MULTIPLY and DIVIDE parsers."""

    def test_multiply_without_giving(self):
        """MULTIPLY A BY B (no GIVING) - should still parse."""
        stmts, _ = parse_procedure("           MULTIPLY A BY B.")
        stmt = _find_stmt(stmts, MultiplyStatement)
        assert len(stmt.operands) >= 2

    def test_divide_by_giving_with_remainder(self):
        """DIVIDE A BY B GIVING C REMAINDER D - check REMAINDER not consumed by basic parser."""
        stmts, _ = parse_procedure("           DIVIDE A BY B GIVING C REMAINDER D.")
        stmt = _find_stmt(stmts, DivideStatement)
        d = stmt.to_dict()
        assert d["giving"] == "C"
