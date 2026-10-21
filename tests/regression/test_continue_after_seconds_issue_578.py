"""Regression tests for issue #578: ``CONTINUE AFTER n SECONDS``.

Enterprise COBOL 6.4 added ``CONTINUE AFTER arithmetic-expression SECONDS``.
The CONTINUE parser consumed only the verb, so the AFTER phrase was dropped
with an "Unparsed tokens" warning and a data item used only in the delay
read as never referenced by unused-variables and xref.
"""

from cobolparser import (
    CobolParser,
    ErrorRecoveryMode,
    UnusedVariableAnalyzer,
    parse_cobol,
)
from cobolparser.analysis.xref import XrefAnalyzer

SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. CONTDLY.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-DELAY PIC 9(3) VALUE 5.
       01 WS-FACTOR PIC 9 VALUE 2.
       01 WS-UNUSED PIC X.
       PROCEDURE DIVISION.
       MAIN-PARA.
           CONTINUE AFTER WS-DELAY SECONDS
           CONTINUE AFTER (WS-DELAY * WS-FACTOR) + 1 SECONDS
           CONTINUE
           DISPLAY 'DONE'
           STOP RUN.
"""


def _continues(ast):
    return [s for s in ast.get_all_statements() if s.statement_type == "CONTINUE"]


def test_delay_is_parsed_without_warning() -> None:
    result = parse_cobol(SOURCE, filename="contdly.cbl")
    assert result.success, result.errors
    assert result.warnings == []
    stmts = _continues(result.ast)
    assert [s.delay_expression for s in stmts] == [
        "WS-DELAY",
        "( WS-DELAY * WS-FACTOR ) + 1",
        None,
    ]
    assert stmts[0].delay_expression_tree is not None
    assert stmts[0].to_dict()["delay_expression"] == "WS-DELAY"
    # A plain CONTINUE serializes exactly as before.
    assert "delay_expression" not in stmts[2].to_dict()
    # The DISPLAY after the delay is still its own statement.
    types = [s.statement_type for s in result.ast.get_all_statements()]
    assert types.count("DISPLAY") == 1


def test_delay_operands_count_as_read() -> None:
    ast = parse_cobol(SOURCE, filename="contdly.cbl").ast
    unused = [i.name for i in UnusedVariableAnalyzer().analyze(ast).unused_items]
    assert unused == ["WS-UNUSED"]

    xref = XrefAnalyzer().analyze(ast)
    roles = {
        entry.name: {ref.role for ref in entry.references} for entry in xref.entries
    }
    assert roles["WS-DELAY"] == {"read"}
    assert roles["WS-FACTOR"] == {"read"}


def test_missing_seconds_is_reported() -> None:
    source = SOURCE.replace(
        "CONTINUE AFTER WS-DELAY SECONDS", "CONTINUE AFTER WS-DELAY"
    )
    result = CobolParser(error_recovery=ErrorRecoveryMode.COLLECT_ALL).parse(source)
    assert any("SECONDS" in str(e) for e in result.errors)
    # The next statement is not swallowed into the delay expression.
    assert _continues(result.ast)[0].delay_expression == "WS-DELAY"
