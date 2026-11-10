"""A paragraph header whose separator period is on the next line.

``2000-SEND-MAP`` / ``.`` (AWS CardDemo's COTRTLIC, found by the open-source
corpus harness in ``tools/corpus``) is a legal header. The boundary check
looked only one token past the name, saw the line break, and dropped the
name as "unparsed tokens"; the paragraph's statements joined the previous
paragraph and every PERFORM of it pointed nowhere.
"""

from cobolparser import CobolParser, ErrorRecoveryMode
from cobolparser.models.walk import all_paragraphs


def _parse(body: str):
    source = (
        "       IDENTIFICATION DIVISION.\n"
        "       PROGRAM-ID. T.\n"
        "       PROCEDURE DIVISION.\n" + body
    )
    return CobolParser(error_recovery=ErrorRecoveryMode.COLLECT_ALL).parse(source)


def _layout(result):
    return [
        (p.paragraph_name, [type(s).__name__ for s in p.statements])
        for p in all_paragraphs(result.ast.procedure_division)
    ]


def test_carddemo_shape_keeps_the_paragraph():
    result = _parse(
        "       1290-CROSS-EDITS-EXIT.\n"
        "           EXIT\n"
        "           .\n"
        "       2000-SEND-MAP\n"
        "            .\n"
        "           PERFORM 2100-SCREEN-INIT\n"
        "              THRU 2100-SCREEN-INIT-EXIT\n"
        "           .\n"
        "       2100-SCREEN-INIT.\n"
        "           CONTINUE.\n"
        "       2100-SCREEN-INIT-EXIT.\n"
        "           EXIT.\n"
    )
    assert result.errors == [] and result.warnings == []
    assert _layout(result) == [
        ("1290-CROSS-EDITS-EXIT", ["ExitStatement"]),
        ("2000-SEND-MAP", ["PerformStatement"]),
        ("2100-SCREEN-INIT", ["ContinueStatement"]),
        ("2100-SCREEN-INIT-EXIT", ["ExitStatement"]),
    ]


def test_numeric_name_and_blank_lines_before_the_period():
    result = _parse(
        "       1000.\n"
        "           DISPLAY 'A'.\n"
        "       2000\n"
        "\n"
        "           .\n"
        "           DISPLAY 'B'.\n"
    )
    assert result.warnings == []
    assert _layout(result) == [
        ("1000", ["DisplayStatement"]),
        ("2000", ["DisplayStatement"]),
    ]


def test_statement_period_on_the_next_line_is_not_a_header():
    result = _parse(
        "       P1.\n"
        "           MOVE 1 TO WS-A\n"
        "           .\n"
        "           GO TO P1\n"
        "           .\n"
    )
    assert _layout(result) == [("P1", ["MoveStatement", "GoStatement"])]


def test_scope_terminator_before_a_next_line_period_is_not_a_header():
    result = _parse(
        "       P1.\n"
        "           DISPLAY 'A' UPON CONSOLE\n"
        "           END-DISPLAY\n"
        "           .\n"
        "           STOP RUN.\n"
    )
    assert _layout(result) == [("P1", ["DisplayStatement", "StopStatement"])]
