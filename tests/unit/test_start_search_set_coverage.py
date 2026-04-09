"""Tests targeting uncovered lines in start_parser.py, search_parser.py, and set_parser.py.

start_parser.py:
- KEY IS GREATER THAN / NOT LESS THAN conditions (lines 90-138, 155-166)
- INVALID KEY / NOT INVALID KEY clauses (lines 140-166, 177-178)

search_parser.py:
- SEARCH ALL (lines 51-54)
- VARYING clause (lines 64-72)
- AT END clause (lines 90-100)
- WHEN clause with condition parsing (lines 101-124)
- END-SEARCH with period (lines 83-89)

set_parser.py:
- SET ... TO TRUE/FALSE (lines 84-89)
- SET ... UP BY / DOWN BY (lines 94-117)
- Multiple targets (lines 51-70)
"""

import pytest

from cobolparser.core.token_stream import TokenStream
from cobolparser.models.statements import SetStatement
from cobolparser.parser import CobolParser
from cobolparser.parsers.statements.set_parser import SetStatementParser


def parse_procedure(code):
    """Parse COBOL and return procedure division statements."""
    src = (
        "       IDENTIFICATION DIVISION.\n"
        "       PROGRAM-ID. TEST-STMT.\n"
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


class TestStartKeyConditions:
    """START ... KEY IS ... conditions (lines 90-138, 155-166)."""

    @pytest.mark.parametrize(
        "condition",
        [
            "EQUAL TO",
            "GREATER THAN",
            "NOT LESS THAN",
            "GREATER THAN OR EQUAL",
        ],
        ids=["equal", "greater", "not-less", "greater-or-equal"],
    )
    def test_start_key_condition(self, condition):
        stmts, _ = parse_procedure(
            f"           START INPUT-FILE KEY IS {condition} WS-KEY."
        )
        assert len(stmts) >= 1

    def test_start_invalid_key(self):
        stmts, _ = parse_procedure(
            "           START INPUT-FILE KEY IS EQUAL TO WS-KEY\n"
            "               INVALID KEY\n"
            '                   DISPLAY "Invalid key"\n'
            "           END-START."
        )
        assert len(stmts) >= 1

    def test_start_not_invalid_key(self):
        stmts, _ = parse_procedure(
            "           START INPUT-FILE KEY IS EQUAL TO WS-KEY\n"
            "               NOT INVALID KEY\n"
            '                   DISPLAY "Found"\n'
            "           END-START."
        )
        assert len(stmts) >= 1

    def test_start_both_invalid_key_clauses(self):
        stmts, _ = parse_procedure(
            "           START INPUT-FILE KEY IS EQUAL TO WS-KEY\n"
            "               INVALID KEY\n"
            '                   DISPLAY "Error"\n'
            "               NOT INVALID KEY\n"
            '                   DISPLAY "OK"\n'
            "           END-START."
        )
        assert len(stmts) >= 1


class TestSearchStatement:
    """SEARCH statement variants (lines 49-152)."""

    def test_search_all(self):
        stmts, _ = parse_procedure(
            "           SEARCH ALL WS-TABLE\n"
            "               WHEN WS-KEY(WS-IDX) = WS-SEARCH\n"
            '                   DISPLAY "FOUND"\n'
            "           END-SEARCH."
        )
        assert len(stmts) >= 1

    def test_search_with_varying(self):
        stmts, _ = parse_procedure(
            "           SEARCH WS-TABLE VARYING WS-IDX\n"
            "               WHEN WS-ITEM(WS-IDX) = WS-TARGET\n"
            '                   DISPLAY "FOUND"\n'
            "           END-SEARCH."
        )
        assert len(stmts) >= 1

    def test_search_with_at_end(self):
        stmts, _ = parse_procedure(
            "           SEARCH WS-TABLE\n"
            "               AT END\n"
            '                   DISPLAY "NOT FOUND"\n'
            "               WHEN WS-ITEM(WS-IDX) = WS-TARGET\n"
            '                   DISPLAY "FOUND"\n'
            "           END-SEARCH."
        )
        assert len(stmts) >= 1

    def test_search_with_multiple_when(self):
        stmts, _ = parse_procedure(
            "           SEARCH WS-TABLE\n"
            '               WHEN WS-ITEM(WS-IDX) = "A"\n'
            '                   DISPLAY "A"\n'
            '               WHEN WS-ITEM(WS-IDX) = "B"\n'
            '                   DISPLAY "B"\n'
            "           END-SEARCH."
        )
        assert len(stmts) >= 1

    def test_search_terminated_by_period(self):
        stmts, _ = parse_procedure(
            "           SEARCH WS-TABLE\n"
            "               WHEN WS-ITEM(WS-IDX) = WS-X\n"
            '                   DISPLAY "OK".'
        )
        assert len(stmts) >= 1


class TestSetStatement:
    """SET statement variants (lines 33-126)."""

    @pytest.mark.parametrize(
        "code,expected_type",
        [
            ("SET WS-FLAG TO TRUE.", "TRUE"),
            ("SET WS-FLAG TO FALSE.", "FALSE"),
            ("SET WS-INDEX TO 5.", "TO"),
            ("SET WS-INDEX UP BY 1.", "UP_BY"),
            ("SET WS-INDEX DOWN BY 1.", "DOWN_BY"),
        ],
        ids=["to-true", "to-false", "to-value", "up-by", "down-by"],
    )
    def test_set_type_variants(self, code, expected_type):
        stmts, _ = parse_procedure(f"           {code}")
        set_stmts = [s for s in stmts if isinstance(s, SetStatement)]
        assert len(set_stmts) >= 1
        assert set_stmts[0].set_type == expected_type

    def test_set_multiple_targets(self):
        stmts, _ = parse_procedure("           SET WS-A WS-B WS-C TO TRUE.")
        set_stmts = [s for s in stmts if isinstance(s, SetStatement)]
        assert len(set_stmts) >= 1
        assert len(set_stmts[0].targets) == 3

    def test_set_address_of(self):
        stmts, _ = parse_procedure("           SET ADDRESS OF WS-PTR TO WS-ADDR.")
        set_stmts = [s for s in stmts if isinstance(s, SetStatement)]
        assert len(set_stmts) >= 1

    def test_matches_empty_stream(self):
        assert SetStatementParser().matches(TokenStream([])) is False
