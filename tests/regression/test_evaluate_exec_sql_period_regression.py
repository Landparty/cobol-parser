"""A schema-qualified table name inside a nested EXEC SQL statement must not
be mistaken for the EVALUATE's own terminating period.

`_skip_clause_statements` (evaluate_parser.py) detects an IBM-style
period-terminated EVALUATE (no END-EVALUATE; the WHEN clause's last
statement's own trailing period closes the whole construct) by checking
whether the nested statement parser consumed a PERIOD token. Before this
fix it checked for *any* PERIOD token anywhere in the range the nested
parser consumed -- but the lexer tokenizes every "." as TokenType.PERIOD
unconditionally, including the schema-qualifier dot in a table name like
"BANK.GL_ACCOUNT" inside an EXEC SQL block's embedded text. That dot has
nothing to do with COBOL sentence termination, but the old check treated
it as though it did: it closed the WHEN clause (and the whole EVALUATE)
right after the EXEC SQL statement, so every statement physically below it
in the same WHEN clause -- and the following WHEN clause(s) entirely --
got misparsed as flat, top-level paragraph statements instead of staying
nested inside the EVALUATE.

Observed on GLRECON.cbl (legacy-application corpus) via mockymock: a
mocked WRITE statement immediately followed by "WHEN +100" (no period
between them, both inside WHEN 0's body) had its splice span swallow the
WHEN clause header, because the AST no longer reported the WRITE and the
following statements as members of the EVALUATE at all.
"""

from cobolparser import parse_cobol


class TestEvaluateExecSqlPeriodRegression:
    def test_schema_qualified_table_name_does_not_close_the_evaluate(self):
        source = (
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. EVALSQL.\n"
            "       DATA DIVISION.\n"
            "       WORKING-STORAGE SECTION.\n"
            "       01 SQLCODE PIC S9(9) COMP.\n"
            "       01 WS-A PIC 9(5).\n"
            "       01 WS-B PIC 9(5).\n"
            "       PROCEDURE DIVISION.\n"
            "       MAIN-PARA.\n"
            "           EVALUATE SQLCODE\n"
            "               WHEN 0\n"
            "                   EXEC SQL\n"
            "                       UPDATE BANK.GL_ACCOUNT\n"
            "                       SET    NET_BALANCE = 0\n"
            "                       WHERE  CURRENT OF GL_BAL_CUR\n"
            "                   END-EXEC\n"
            "                   MOVE 1 TO WS-A\n"
            "                   ADD 1 TO WS-B\n"
            "               WHEN +100\n"
            "                   CONTINUE\n"
            "               WHEN OTHER\n"
            "                   DISPLAY 'ERROR'\n"
            "           END-EVALUATE.\n"
        )
        result = parse_cobol(source, filename="evalsql.cbl")
        assert result.success, [str(e) for e in result.errors]
        assert not result.warnings, result.warnings

        evaluates = result.ast.find_all_by_type("EvaluateStatement")
        assert len(evaluates) == 1
        stmt = evaluates[0]

        assert len(stmt.when_clauses) == 2
        when_0, when_100 = stmt.when_clauses
        assert when_0.selectors == [{"type": "Literal", "value": "0"}]
        # The EXEC SQL statement's embedded "BANK.GL_ACCOUNT" period must not
        # truncate WHEN 0's body -- the MOVE and ADD after it stay nested.
        assert [type(s).__name__ for s in when_0.statements] == [
            "ExecSQLStatement",
            "MoveStatement",
            "AddStatement",
        ]

        assert when_100.selectors == [{"type": "Literal", "value": "+100"}]
        assert [type(s).__name__ for s in when_100.statements] == ["ContinueStatement"]

        assert stmt.default_when is not None
        assert [type(s).__name__ for s in stmt.default_when.statements] == [
            "DisplayStatement"
        ]

        # A paragraph-level sanity check on top of the EVALUATE's own
        # internal structure: none of WHEN 0's statements leaked out as
        # top-level paragraph statements sitting alongside the EVALUATE.
        procedure = result.ast.get_division("PROCEDURE")
        paragraph = procedure.paragraphs[0]
        assert [type(s).__name__ for s in paragraph.statements] == ["EvaluateStatement"]

    def test_unqualified_table_name_still_parses(self):
        """Guard: a plain (unqualified) UPDATE target -- no embedded period
        at all -- must keep working exactly as before."""
        source = (
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. EVALSQL2.\n"
            "       DATA DIVISION.\n"
            "       WORKING-STORAGE SECTION.\n"
            "       01 SQLCODE PIC S9(9) COMP.\n"
            "       01 WS-A PIC 9(5).\n"
            "       PROCEDURE DIVISION.\n"
            "       MAIN-PARA.\n"
            "           EVALUATE SQLCODE\n"
            "               WHEN 0\n"
            "                   EXEC SQL\n"
            "                       UPDATE GL_ACCOUNT SET NET_BALANCE = 0\n"
            "                   END-EXEC\n"
            "                   MOVE 1 TO WS-A\n"
            "           END-EVALUATE.\n"
        )
        result = parse_cobol(source, filename="evalsql2.cbl")
        assert result.success, [str(e) for e in result.errors]
        stmt = result.ast.find_all_by_type("EvaluateStatement")[0]
        assert [type(s).__name__ for s in stmt.when_clauses[0].statements] == [
            "ExecSQLStatement",
            "MoveStatement",
        ]

    def test_genuine_period_terminated_evaluate_still_closes(self):
        """Guard: the original heuristic's real purpose -- an IBM-style
        EVALUATE with no END-EVALUATE, closed by its last statement's own
        trailing period -- must still work."""
        source = (
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. EVALSQL3.\n"
            "       DATA DIVISION.\n"
            "       WORKING-STORAGE SECTION.\n"
            "       01 WS-A PIC 9(5).\n"
            "       01 WS-B PIC 9(5).\n"
            "       PROCEDURE DIVISION.\n"
            "       MAIN-PARA.\n"
            "           EVALUATE WS-A\n"
            "               WHEN 0\n"
            "                   MOVE 1 TO WS-B.\n"
            "           DISPLAY 'AFTER'.\n"
        )
        result = parse_cobol(source, filename="evalsql3.cbl")
        assert result.success, [str(e) for e in result.errors]
        procedure = result.ast.get_division("PROCEDURE")
        paragraph = procedure.paragraphs[0]
        # The EVALUATE closed at the period after "MOVE 1 TO WS-B.", so
        # DISPLAY 'AFTER' is a sibling top-level statement, not nested.
        assert [type(s).__name__ for s in paragraph.statements] == [
            "EvaluateStatement",
            "DisplayStatement",
        ]
