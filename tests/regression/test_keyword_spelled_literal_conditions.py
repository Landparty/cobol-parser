"""Condition collectors must not read a quoted literal as a clause keyword.

The lexer strips a string literal's quotes, so ``IF X = "ELSE"`` hands the
IF parser a token whose value is ``ELSE``. The condition loops of IF, SEARCH
WHEN, PERFORM UNTIL and EVALUATE WHEN compared token *values* against their
clause words, so:

* ``IF X = "ELSE" DISPLAY 'Z' END-IF`` put the DISPLAY in the ELSE branch;
* ``IF X = "END-IF" ...`` closed the IF with an empty body;
* ``PERFORM ... UNTIL X = "END-IF"`` / ``VARYING ... UNTIL X = "AFTER"``
  truncated the condition to ``X =`` (the latter with a warning);
* ``SEARCH ... WHEN K = "WHEN"`` / ``EVALUATE ... WHEN "WHEN"`` split one
  WHEN into two, with "must have at least one selector" errors.
"""

from cobolparser import parse_cobol


def _parse(body: str):
    source = (
        "       IDENTIFICATION DIVISION.\n"
        "       PROGRAM-ID. KWLIT.\n"
        "       DATA DIVISION.\n"
        "       WORKING-STORAGE SECTION.\n"
        "       01 WS-A PIC X(12).\n"
        "       01 WS-N PIC 9(4).\n"
        "       01 WS-TAB.\n"
        "          05 WS-K PIC X(12) OCCURS 5 INDEXED BY IX.\n"
        "       PROCEDURE DIVISION.\n"
        "       MAIN-PARA.\n" + body + "           STOP RUN.\n"
        "       P1.\n"
        "           EXIT.\n"
    )
    result = parse_cobol(source)
    assert result.errors == []
    assert result.warnings == []
    return result.ast.procedure_division.paragraphs[0].statements


def test_if_condition_literal_else_and_end_if():
    stmts = _parse(
        "           IF WS-A = 'ELSE' DISPLAY 'Z' END-IF\n"
        "           IF WS-A = 'END-IF' DISPLAY 'Y' END-IF\n"
        "           IF WS-A = 'THEN' THEN DISPLAY 'X' END-IF\n"
    )
    assert [s.statement_type for s in stmts] == ["IF", "IF", "IF", "STOP"]
    for stmt, literal in zip(stmts[:3], ("'ELSE'", "'END-IF'", "'THEN'"), strict=True):
        assert stmt.condition.right_operand == literal
        assert len(stmt.then_statements) == 1
        assert not stmt.else_statements


def test_perform_until_literal_scope_terminator_and_after():
    stmts = _parse(
        "           PERFORM P1 UNTIL WS-A = 'END-IF'\n"
        "           PERFORM P1 VARYING WS-N FROM 1 BY 1\n"
        "             UNTIL WS-A = 'AFTER'\n"
        "           PERFORM UNTIL WS-A = 'END-PERFORM'\n"
        "             DISPLAY 'W'\n"
        "           END-PERFORM\n"
    )
    conditions = [s.until_condition.operands[0] for s in stmts[:3]]
    assert conditions == [
        "WS-A = 'END-IF'",
        "WS-A = 'AFTER'",
        "WS-A = 'END-PERFORM'",
    ]
    assert len(stmts[2].inline_statements) == 1


def test_search_and_evaluate_when_literal_when():
    stmts = _parse(
        "           SEARCH WS-K AT END DISPLAY 'NF'\n"
        "             WHEN WS-K(IX) = 'WHEN' DISPLAY 'F'\n"
        "             WHEN WS-K(IX) = 'END-SEARCH' DISPLAY 'G'\n"
        "           END-SEARCH\n"
        "           EVALUATE WS-A\n"
        "             WHEN 'WHEN' DISPLAY '1'\n"
        "             WHEN 'ALSO' DISPLAY '2'\n"
        "             WHEN 'END-EVALUATE' DISPLAY '3'\n"
        "           END-EVALUATE\n"
    )
    search, evaluate, stop = stmts
    assert [w["condition"] for w in search.when_clauses] == [
        "WS-K ( IX ) = 'WHEN'",
        "WS-K ( IX ) = 'END-SEARCH'",
    ]
    assert [c.selectors for c in evaluate.when_clauses] == [
        [{"type": "Literal", "value": v, "quoted": True}]
        for v in ("WHEN", "ALSO", "END-EVALUATE")
    ]
    assert all(len(c.statements) == 1 for c in evaluate.when_clauses)
    assert stop.statement_type == "STOP"
