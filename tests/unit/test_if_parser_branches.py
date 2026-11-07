"""IF statement parsing: the branches the other IF test files leave open.

Real IF sentences parsed through ``CobolParser``; each test checks the
``IfStatement`` (condition, THEN / ELSE statements, END-IF flags), which
statements end up outside the IF, and the errors / warnings: a condition
cut short by a period, a comma, ELSE or the end of the source; a scoped
statement (``END-EVALUATE``) whose sentence period stands on its own line,
in either branch; a branch whose first word is not a statement; and an
ELSE branch holding several statements.
"""

import pytest

from cobolparser import CobolParser, ErrorRecoveryMode

PRE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. IFBR.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  X                   PIC 9.
       01  Y                   PIC 9.
       PROCEDURE DIVISION.
       P1.
"""


def _parse(body: str):
    parser = CobolParser(error_recovery=ErrorRecoveryMode.COLLECT_ALL)
    result = parser.parse(PRE + body, "ifbr.cbl")
    assert result.ast is not None
    return result


def _top_level(result) -> list[str]:
    """Statement types directly in paragraph P1, in order."""
    p1 = result.ast.procedure_division.paragraphs[0]
    return [s.to_dict()["statement_type"] for s in p1.statements]


def _first_if(result):
    p1 = result.ast.procedure_division.paragraphs[0]
    return next(s for s in p1.statements if s.to_dict()["statement_type"] == "IF")


def _types(statements) -> list[str]:
    return [s.to_dict()["statement_type"] for s in statements]


def _cond(stmt) -> tuple:
    c = stmt.to_dict()["condition"]
    return (c["left_operand"], c["operator"], c["right_operand"])


class TestConditionEnds:
    def test_period_right_after_condition(self):
        result = _parse("           IF X = 1.\n           DISPLAY 'B'.\n")
        assert result.errors == []
        stmt = _first_if(result)
        assert _cond(stmt) == ("X", "EQUAL", "1")
        assert stmt.then_statements == []
        # The DISPLAY is the next sentence, not the THEN branch.
        assert _top_level(result) == ["IF", "DISPLAY"]

    def test_comma_after_condition_is_a_separator(self):
        result = _parse("           IF X = 1, DISPLAY 'A'.\n")
        assert result.errors == []
        stmt = _first_if(result)
        assert _cond(stmt) == ("X", "EQUAL", "1")
        assert _types(stmt.then_statements) == ["DISPLAY"]

    def test_else_right_after_condition(self):
        result = _parse("           IF X = 1 ELSE DISPLAY 'A'.\n")
        assert result.errors == []
        stmt = _first_if(result)
        assert _cond(stmt) == ("X", "EQUAL", "1")
        assert stmt.then_statements == []
        assert _types(stmt.else_statements) == ["DISPLAY"]

    def test_condition_split_over_lines_with_then_on_its_own_line(self):
        result = _parse("""\
           IF X = 1
              AND Y = 2
           THEN
               DISPLAY 'A'
           END-IF.
""")
        assert result.errors == []
        stmt = _first_if(result)
        assert stmt.to_dict()["condition"]["operator"] == "AND"
        assert _types(stmt.then_statements) == ["DISPLAY"]
        assert stmt.ended_by_end_if is True
        assert stmt.period_after_end_if is True

    def test_source_ends_inside_the_condition(self):
        result = _parse("           IF X = 1")
        assert result.errors == []
        stmt = _first_if(result)
        assert _cond(stmt) == ("X", "EQUAL", "1")
        assert stmt.then_statements == []

    def test_missing_condition_is_an_error(self):
        result = _parse("           IF THEN DISPLAY 'A'.\n")
        assert [str(e) for e in result.errors] == [
            "line 9, column 5: IF statement requires a condition before the "
            "THEN branch"
        ]
        assert _types(_first_if(result).then_statements) == ["DISPLAY"]

    def test_empty_parentheses_are_an_unparseable_condition(self):
        result = _parse("           IF ( ) DISPLAY 'A'.\n")
        assert [str(e) for e in result.errors] == [
            "line 9, column 5: IF statement: could not parse condition expression"
        ]
        stmt = _first_if(result)
        assert stmt.to_dict()["condition"] is None
        assert _types(stmt.then_statements) == ["DISPLAY"]

    @pytest.mark.xfail(
        strict=True,
        reason=(
            "IfStatementParser only reports a condition the builder returns "
            "None for; 'IF X = THEN' yields a COMPARISON with right_operand "
            "None and no error, so an incomplete relation passes silently"
        ),
    )
    def test_relation_without_right_operand_is_an_error(self):
        result = _parse("           IF X = THEN DISPLAY 'A'.\n")
        assert result.errors


class TestPeriodAfterScopedStatement:
    def test_then_branch(self):
        result = _parse("""\
           IF X = 1
               EVALUATE Y WHEN 1 CONTINUE END-EVALUATE
               .
           DISPLAY 'B'.
""")
        assert result.errors == []
        assert result.warnings == []
        stmt = _first_if(result)
        assert _types(stmt.then_statements) == ["EVALUATE"]
        assert stmt.else_statements == []
        assert _top_level(result) == ["IF", "DISPLAY"]

    def test_else_branch(self):
        result = _parse("""\
           IF X = 1 CONTINUE
           ELSE
               EVALUATE Y WHEN 1 CONTINUE END-EVALUATE
               .
           DISPLAY 'B'.
""")
        assert result.errors == []
        assert result.warnings == []
        stmt = _first_if(result)
        assert _types(stmt.then_statements) == ["CONTINUE"]
        assert _types(stmt.else_statements) == ["EVALUATE"]
        assert _top_level(result) == ["IF", "DISPLAY"]


class TestBranchContents:
    def test_else_with_several_statements_and_end_if(self):
        result = _parse("""\
           IF X = 1
               DISPLAY 'A'
           ELSE
               DISPLAY 'B'
               DISPLAY 'C'
           END-IF
           DISPLAY 'D'.
""")
        assert result.errors == []
        stmt = _first_if(result)
        assert _types(stmt.then_statements) == ["DISPLAY"]
        assert [s.display_items for s in stmt.else_statements] == [['"B"'], ['"C"']]
        assert stmt.ended_by_end_if is True
        assert stmt.period_after_end_if is False
        assert _top_level(result) == ["IF", "DISPLAY"]

    def test_then_branch_that_is_not_a_statement_is_reported(self):
        # ``= 2`` cannot start a statement: both branch loops stop, the IF
        # ends with empty branches, and the leftover is reported.
        result = _parse("           IF X = 1 THEN = 2.\n           DISPLAY 'B'.\n")
        stmt = _first_if(result)
        assert stmt.then_statements == []
        assert stmt.else_statements == []
        assert any("Unparsed tokens starting at '='" in w for w in result.warnings)
        assert _top_level(result)[-1] == "DISPLAY"

    def test_else_branch_that_is_not_a_statement_is_reported(self):
        result = _parse(
            "           IF X = 1 DISPLAY 'A' ELSE = 2.\n           DISPLAY 'B'.\n"
        )
        stmt = _first_if(result)
        assert _types(stmt.then_statements) == ["DISPLAY"]
        assert stmt.else_statements == []
        assert any("Unparsed tokens starting at '='" in w for w in result.warnings)
