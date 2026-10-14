"""WHEN selectors that are string literals spelled like EVALUATE keywords.

The lexer strips a string literal's quotes, and the selector builder used to
classify the remaining *text*: ``WHEN "ANY"`` became the ANY wildcard,
``WHEN "THRU"`` a range with no ends (reported as an error on valid code),
and ``WHEN "AND"`` / ``"NOT"`` / ``"<"`` a condition. A COBOL tokenizer's
operator table is written exactly this way. Keyword recognition now skips
STRING_LITERAL tokens.
"""

from cobolparser import parse_cobol


def _selectors(when_lines: str) -> tuple[list, list]:
    source = (
        "       IDENTIFICATION DIVISION.\n"
        "       PROGRAM-ID. EVALKW.\n"
        "       DATA DIVISION.\n"
        "       WORKING-STORAGE SECTION.\n"
        "       01 WS-OP PIC X(4).\n"
        "       01 WS-N  PIC 9(4).\n"
        "       PROCEDURE DIVISION.\n"
        "       MAIN-PARA.\n"
        "           EVALUATE WS-OP\n" + when_lines + "           END-EVALUATE.\n"
    )
    result = parse_cobol(source)
    (stmt,) = result.ast.find_all_by_type("EvaluateStatement")
    return result.errors, [clause.selectors for clause in stmt.when_clauses]


def test_keyword_spelled_literals_are_plain_values():
    errors, selectors = _selectors(
        "             WHEN 'ANY' DISPLAY 1\n"
        "             WHEN 'THRU' DISPLAY 2\n"
        "             WHEN 'AND' DISPLAY 3\n"
        "             WHEN 'NOT' DISPLAY 4\n"
        "             WHEN '<' DISPLAY 5\n"
        "             WHEN 'A OR B' DISPLAY 6\n"
    )
    assert errors == []
    assert selectors == [
        [{"type": "Literal", "value": value, "quoted": True}]
        for value in ("ANY", "THRU", "AND", "NOT", "<", "A OR B")
    ]


def test_keywords_as_words_still_classify():
    errors, selectors = _selectors(
        "             WHEN ANY DISPLAY 1\n"
        "             WHEN 'A' THRU 'C' DISPLAY 2\n"
        "             WHEN NOT 'THRU' DISPLAY 3\n"
    )
    assert errors == []
    assert selectors == [
        [{"type": "Any"}],
        [{"type": "Range", "start": "A", "end": "C"}],
        [{"type": "Condition", "text": "NOT 'THRU'"}],
    ]
