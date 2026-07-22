"""Regression tests for DISPLAY / GO TO / CANCEL list-truncation gaps.

Mirrors the comma fixes already applied to MOVE / CALL / SET / UNSTRING:
a COMMA between operands is a separator, not a terminator. Also covers the
DISPLAY UPON clause bug where everything after the device name (including
the sentence period) was abandoned, turning `WITH NO ADVANCING` into a
dropped clause and the leftover period into a phantom paragraph named ".".
"""

from cobolparser import parse_cobol
from cobolparser.models.statements import (
    CancelStatement,
    DisplayStatement,
    GoStatement,
)


def _parse(statement: str):
    """Parse a single PROCEDURE DIVISION statement, return the ParseResult."""
    src = (
        "       IDENTIFICATION DIVISION.\n"
        "       PROGRAM-ID. TEST-STMT.\n"
        "       PROCEDURE DIVISION.\n"
        "       MAIN-PARA.\n"
        f"{statement}\n"
    )
    result = parse_cobol(src, filename="t.cob")
    assert result.success, f"parse failed: {result.errors}"
    assert result.ast is not None
    return result


def _paragraph_names(result):
    return [p.paragraph_name for p in result.ast.find_all_by_type("CobolParagraph")]


def _single_stmt(result, node_class):
    stmts = [
        s
        for s in result.ast.find_all_by_type(node_class.__name__)
        if isinstance(s, node_class)
    ]
    assert len(stmts) == 1, f"expected exactly one {node_class.__name__}: {stmts}"
    return stmts[0]


class TestDisplayUponTrailingClauses:
    def test_upon_then_with_no_advancing(self):
        """Clauses after UPON must not be dropped, and the period must be
        consumed (previously: with_no_advancing lost + phantom '.' paragraph)."""
        result = _parse(
            '           DISPLAY WS-A WS-B "LIT" UPON CONSOLE WITH NO ADVANCING.'
        )
        stmt = _single_stmt(result, DisplayStatement)
        assert stmt.display_items == ["WS-A", "WS-B", '"LIT"']
        assert stmt.output_device == "CONSOLE"
        assert stmt.with_no_advancing is True
        assert _paragraph_names(result) == ["MAIN-PARA"]

    def test_with_no_advancing_then_upon_not_regressed(self):
        """Reverse clause order worked before the fix and must keep working."""
        result = _parse("           DISPLAY WS-A WITH NO ADVANCING UPON CONSOLE.")
        stmt = _single_stmt(result, DisplayStatement)
        assert stmt.display_items == ["WS-A"]
        assert stmt.output_device == "CONSOLE"
        assert stmt.with_no_advancing is True
        assert _paragraph_names(result) == ["MAIN-PARA"]

    def test_upon_only_still_consumes_period(self):
        result = _parse("           DISPLAY WS-A UPON SYSOUT.")
        stmt = _single_stmt(result, DisplayStatement)
        assert stmt.display_items == ["WS-A"]
        assert stmt.output_device == "SYSOUT"
        assert stmt.with_no_advancing is False
        assert _paragraph_names(result) == ["MAIN-PARA"]


class TestDisplayCommaItems:
    def test_comma_separated_items(self):
        """DISPLAY WS-A, WS-B, WS-C. -- previously truncated to ['WS-A'] with
        WS-C misread as a phantom paragraph."""
        result = _parse("           DISPLAY WS-A, WS-B, WS-C.")
        stmt = _single_stmt(result, DisplayStatement)
        assert stmt.display_items == ["WS-A", "WS-B", "WS-C"]
        assert _paragraph_names(result) == ["MAIN-PARA"]

    def test_space_separated_items_not_regressed(self):
        result = _parse("           DISPLAY WS-A WS-B WS-C.")
        stmt = _single_stmt(result, DisplayStatement)
        assert stmt.display_items == ["WS-A", "WS-B", "WS-C"]
        assert _paragraph_names(result) == ["MAIN-PARA"]

    def test_comma_separated_items_with_literal(self):
        result = _parse('           DISPLAY "TOTAL:", WS-TOTAL.')
        stmt = _single_stmt(result, DisplayStatement)
        assert stmt.display_items == ['"TOTAL:"', "WS-TOTAL"]
        assert _paragraph_names(result) == ["MAIN-PARA"]


class TestGoToCommaTargets:
    def test_comma_separated_computed_go_to(self):
        """GO TO A, B, C DEPENDING ON X. -- previously collapsed to a single
        unconditional target with the DEPENDING variable lost."""
        result = _parse("           GO TO PARA-A, PARA-B, PARA-C DEPENDING ON WS-IDX.")
        stmt = _single_stmt(result, GoStatement)
        assert stmt.target_paragraphs == ["PARA-A", "PARA-B", "PARA-C"]
        assert stmt.depending_on_variable == "WS-IDX"
        assert _paragraph_names(result) == ["MAIN-PARA"]

    def test_space_separated_computed_go_to_not_regressed(self):
        result = _parse("           GO TO PARA-A PARA-B PARA-C DEPENDING ON WS-IDX.")
        stmt = _single_stmt(result, GoStatement)
        assert stmt.target_paragraphs == ["PARA-A", "PARA-B", "PARA-C"]
        assert stmt.depending_on_variable == "WS-IDX"
        assert _paragraph_names(result) == ["MAIN-PARA"]

    def test_simple_go_to_not_regressed(self):
        result = _parse("           GO TO PARA-A.")
        stmt = _single_stmt(result, GoStatement)
        assert stmt.target_paragraphs == ["PARA-A"]
        assert stmt.depending_on_variable is None
        assert _paragraph_names(result) == ["MAIN-PARA"]


class TestCancelCommaPrograms:
    def test_comma_separated_program_names(self):
        """CANCEL WS-A, WS-B. -- previously truncated to ['WS-A'] with WS-B
        misread as a phantom paragraph."""
        result = _parse("           CANCEL WS-A, WS-B.")
        stmt = _single_stmt(result, CancelStatement)
        assert stmt.program_names == ["WS-A", "WS-B"]
        assert _paragraph_names(result) == ["MAIN-PARA"]

    def test_space_separated_program_names_not_regressed(self):
        result = _parse("           CANCEL WS-A WS-B.")
        stmt = _single_stmt(result, CancelStatement)
        assert stmt.program_names == ["WS-A", "WS-B"]
        assert _paragraph_names(result) == ["MAIN-PARA"]

    def test_comma_separated_literal_program_names(self):
        result = _parse('           CANCEL "SUBPROG1", "SUBPROG2".')
        stmt = _single_stmt(result, CancelStatement)
        assert stmt.program_names == ["SUBPROG1", "SUBPROG2"]
        assert _paragraph_names(result) == ["MAIN-PARA"]
