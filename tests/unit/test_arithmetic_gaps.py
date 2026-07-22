"""Regression tests for the ADD/SUBTRACT/MULTIPLY/DIVIDE/COMPUTE gap fixes.

Each test corresponds to one of five previously-confirmed bugs in
``arithmetic_parsers.py`` / ``arithmetic.py``:

1. ADD/SUBTRACT silently dropped ROUNDED.
2. COMPUTE silently discarded ROUNDED (consumed the token, never stored it).
3. ADD/SUBTRACT only kept a single TO/FROM target even when several were
   written, losing extra targets, their ROUNDED flags, and any trailing
   ON/NOT ON SIZE ERROR clauses to unparsed-token recovery.
4. DIVIDE REMAINDER was not implemented at all.
5. ADD/SUBTRACT CORRESPONDING was misparsed as if CORRESPONDING were a plain
   data-item operand.

All snippets are the exact repros from the bug report.
"""

from cobolparser import parse_cobol
from cobolparser.models.statements import (
    AddStatement,
    ComputeStatement,
    DivideStatement,
    SubtractStatement,
)


def _first_statement(source: str):
    """Parse *source* and return the single PROCEDURE DIVISION statement."""
    result = parse_cobol(source, filename="test.cbl")
    assert result.success, result.errors
    assert result.errors == []
    proc = result.ast.procedure_division
    if proc.paragraphs:
        stmts = proc.paragraphs[0].statements
    else:
        stmts = proc.sections[0].paragraphs[0].statements
    assert len(stmts) == 1
    return stmts[0], result


class TestAddSubtractRounded:
    """Bug 1: ADD/SUBTRACT dropped ROUNDED entirely."""

    def test_add_to_rounded(self):
        src = """
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TEST.
       PROCEDURE DIVISION.
           ADD A TO B ROUNDED.
        """
        stmt, result = _first_statement(src)
        assert isinstance(stmt, AddStatement)
        assert result.warnings == []
        assert stmt.rounded is True
        assert stmt.to_dict()["rounded"] is True

    def test_subtract_from_rounded(self):
        src = """
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TEST.
       PROCEDURE DIVISION.
           SUBTRACT A FROM B ROUNDED.
        """
        stmt, result = _first_statement(src)
        assert isinstance(stmt, SubtractStatement)
        assert result.warnings == []
        assert stmt.rounded is True

    def test_add_not_rounded_by_default(self):
        src = """
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TEST.
       PROCEDURE DIVISION.
           ADD A TO B.
        """
        stmt, _ = _first_statement(src)
        assert stmt.rounded is False
        assert "rounded" not in stmt.to_dict()


class TestComputeRounded:
    """Bug 2: COMPUTE ROUNDED was actively consumed and discarded."""

    def test_compute_rounded_is_captured(self):
        src = """
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TEST.
       PROCEDURE DIVISION.
           COMPUTE X ROUNDED = A + B.
        """
        stmt, result = _first_statement(src)
        assert isinstance(stmt, ComputeStatement)
        assert result.warnings == []
        assert stmt.rounded is True
        assert stmt.targets == ["X"]
        assert stmt.to_dict()["rounded"] is True

    def test_compute_not_rounded_by_default(self):
        src = """
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TEST.
       PROCEDURE DIVISION.
           COMPUTE X = A + B.
        """
        stmt, _ = _first_statement(src)
        assert stmt.rounded is False
        assert "rounded" not in stmt.to_dict()


class TestAddSubtractMultipleTargets:
    """Bug 3: only one TO/FROM target survived even when several were given."""

    def test_add_multiple_targets_with_rounded_and_size_error(self):
        src = """
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TEST.
       PROCEDURE DIVISION.
           ADD A B TO C D ROUNDED
               ON SIZE ERROR
                   DISPLAY "ERR"
               NOT ON SIZE ERROR
                   DISPLAY "OK"
           END-ADD.
        """
        stmt, result = _first_statement(src)
        assert isinstance(stmt, AddStatement)
        assert result.warnings == []
        # Primary `target` stays the first, for single-target callers.
        assert stmt.target == "C"
        assert stmt.targets == ["C", "D"]
        assert stmt.rounded is True
        assert stmt.on_size_error is not None
        assert len(stmt.on_size_error) == 1
        assert stmt.not_on_size_error is not None
        assert len(stmt.not_on_size_error) == 1

    def test_subtract_multiple_targets(self):
        src = """
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TEST.
       PROCEDURE DIVISION.
           SUBTRACT A FROM B C ROUNDED.
        """
        stmt, result = _first_statement(src)
        assert isinstance(stmt, SubtractStatement)
        assert result.warnings == []
        assert stmt.target == "B"
        assert stmt.targets == ["B", "C"]
        assert stmt.rounded is True

    def test_add_single_target_unaffected(self):
        """Existing single-target callers keep working (backward compat)."""
        src = """
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TEST.
       PROCEDURE DIVISION.
           ADD 1 TO A GIVING RESULT.
        """
        stmt, result = _first_statement(src)
        assert result.warnings == []
        assert stmt.target == "A"
        assert stmt.targets == ["A"]
        assert stmt.giving == "RESULT"

    def test_missing_period_does_not_swallow_next_paragraph(self):
        """The extra-target loop must stop at a paragraph header (H9): with
        the trailing period missing, `ADD A TO B` followed by `NEXT-PARA.`
        must not fold the header into the target list -- the paragraph has
        to survive in the AST and a boundary warning must be recorded."""
        src = """
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TEST.
       PROCEDURE DIVISION.
       PARA-1.
           ADD A TO B
       NEXT-PARA.
           DISPLAY "HI".
        """
        result = parse_cobol(src, filename="test.cbl")
        adds = result.ast.find_all_by_type("AddStatement")
        assert len(adds) == 1
        assert adds[0].targets == ["B"]
        paragraphs = {
            p.paragraph_name for p in result.ast.find_all_by_type("CobolParagraph")
        }
        assert "NEXT-PARA" in paragraphs
        assert len(result.warnings) >= 1


class TestDivideRemainder:
    """Bug 4: DIVIDE REMAINDER was completely unimplemented."""

    def test_divide_remainder_with_giving_and_size_error(self):
        src = """
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TEST.
       PROCEDURE DIVISION.
           DIVIDE A INTO B GIVING C REMAINDER D
               ON SIZE ERROR
                   DISPLAY "ERR"
           END-DIVIDE.
        """
        stmt, result = _first_statement(src)
        assert isinstance(stmt, DivideStatement)
        assert result.warnings == []
        assert stmt.giving == "C"
        assert stmt.remainder == "D"
        assert stmt.on_size_error is not None
        assert len(stmt.on_size_error) == 1
        assert stmt.to_dict()["remainder"] == "D"

    def test_divide_remainder_without_giving(self):
        src = """
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TEST.
       PROCEDURE DIVISION.
           DIVIDE A INTO B REMAINDER D.
        """
        stmt, result = _first_statement(src)
        assert isinstance(stmt, DivideStatement)
        assert result.warnings == []
        assert stmt.remainder == "D"

    def test_divide_without_remainder_is_unaffected(self):
        src = """
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TEST.
       PROCEDURE DIVISION.
           DIVIDE A INTO B GIVING C.
        """
        stmt, _ = _first_statement(src)
        assert stmt.remainder is None
        assert "remainder" not in stmt.to_dict()


class TestAddSubtractCorresponding:
    """Bug 5: CORRESPONDING was misparsed as a literal operand."""

    def test_subtract_corresponding(self):
        src = """
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TEST.
       PROCEDURE DIVISION.
           SUBTRACT CORRESPONDING WS-RECORD FROM WS-RECORD.
        """
        stmt, result = _first_statement(src)
        assert isinstance(stmt, SubtractStatement)
        assert result.warnings == []
        assert stmt.is_corresponding is True
        assert "CORRESPONDING" not in stmt.operands
        assert stmt.operands == ["WS-RECORD"]
        assert stmt.target == "WS-RECORD"
        assert stmt.to_dict()["is_corresponding"] is True

    def test_add_corresponding(self):
        src = """
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TEST.
       PROCEDURE DIVISION.
           ADD CORRESPONDING WS-A TO WS-B.
        """
        stmt, result = _first_statement(src)
        assert isinstance(stmt, AddStatement)
        assert result.warnings == []
        assert stmt.is_corresponding is True
        assert "CORRESPONDING" not in stmt.operands
        # `operands` carries both the CORRESPONDING source and the TO target
        # (set_target's _add_unique_operand call adds the target too).
        assert stmt.operands == ["WS-A", "WS-B"]
        assert stmt.target == "WS-B"

    def test_add_corr_abbreviation(self):
        src = """
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TEST.
       PROCEDURE DIVISION.
           ADD CORR WS-A TO WS-B.
        """
        stmt, result = _first_statement(src)
        assert isinstance(stmt, AddStatement)
        assert result.warnings == []
        assert stmt.is_corresponding is True
        assert "CORR" not in stmt.operands

    def test_add_not_corresponding_by_default(self):
        src = """
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TEST.
       PROCEDURE DIVISION.
           ADD A TO B.
        """
        stmt, _ = _first_statement(src)
        assert stmt.is_corresponding is False
        assert "is_corresponding" not in stmt.to_dict()
