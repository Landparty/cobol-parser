"""Tests targeting uncovered lines in start_parser.py, search_parser.py, and set_parser.py.

Covers:
start_parser.py:
- KEY IS GREATER THAN / NOT LESS THAN conditions (lines 155-166)
- INVALID KEY / NOT INVALID KEY clauses (lines 140-166, 177-178)

search_parser.py:
- SEARCH ALL (line 51-54)
- VARYING clause (lines 64-72)
- AT END clause (lines 90-100)
- END-SEARCH with period (lines 83-89)
- WHEN clause with condition parsing (lines 101-124)

set_parser.py:
- SET ... TO TRUE/FALSE (lines 84-89)
- SET ... UP BY (lines 94-105)
- SET ... DOWN BY (lines 106-117)
- Multiple targets (lines 51-70)
- Period at end (lines 121-125)
"""

from cobolparser.models.statements import SetStatement
from cobolparser.parser import CobolParser


def parse_procedure(code):
    """Parse COBOL and return procedure division statements."""
    src = f"""
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TEST-STMT.
       PROCEDURE DIVISION.
{code}
    """
    result = CobolParser().parse(src)
    proc = result.ast.procedure_division
    if proc.paragraphs:
        return proc.paragraphs[0].statements, result
    if proc.sections:
        sec = proc.sections[0]
        if sec.paragraphs:
            return sec.paragraphs[0].statements, result
    return [], result


class TestStartKeyConditions:
    """Tests for START ... KEY IS ... conditions (lines 90-138, 155-166)."""

    def test_start_key_equal(self):
        stmts, result = parse_procedure(
            "           START INPUT-FILE KEY IS EQUAL TO WS-KEY."
        )
        assert len(stmts) >= 1

    def test_start_key_greater(self):
        stmts, result = parse_procedure(
            "           START INPUT-FILE KEY IS GREATER THAN WS-KEY."
        )
        assert len(stmts) >= 1

    def test_start_key_not_less(self):
        stmts, result = parse_procedure(
            "           START INPUT-FILE KEY IS NOT LESS THAN WS-KEY."
        )
        assert len(stmts) >= 1

    def test_start_key_greater_than_or_equal(self):
        stmts, result = parse_procedure(
            "           START INPUT-FILE KEY IS GREATER THAN OR EQUAL\n"
            "               WS-KEY."
        )
        assert len(stmts) >= 1

    def test_start_invalid_key(self):
        stmts, result = parse_procedure(
            "           START INPUT-FILE KEY IS EQUAL TO WS-KEY\n"
            "               INVALID KEY\n"
            "                   DISPLAY \"Invalid key\"\n"
            "           END-START."
        )
        assert len(stmts) >= 1

    def test_start_not_invalid_key(self):
        stmts, result = parse_procedure(
            "           START INPUT-FILE KEY IS EQUAL TO WS-KEY\n"
            "               NOT INVALID KEY\n"
            "                   DISPLAY \"Found\"\n"
            "           END-START."
        )
        assert len(stmts) >= 1

    def test_start_both_invalid_key_clauses(self):
        stmts, result = parse_procedure(
            "           START INPUT-FILE KEY IS EQUAL TO WS-KEY\n"
            "               INVALID KEY\n"
            "                   DISPLAY \"Error\"\n"
            "               NOT INVALID KEY\n"
            "                   DISPLAY \"OK\"\n"
            "           END-START."
        )
        assert len(stmts) >= 1


class TestSearchStatementCoverage:
    """Tests for SEARCH statement (lines 49-152)."""

    def test_search_all(self):
        stmts, result = parse_procedure(
            "           SEARCH ALL WS-TABLE\n"
            "               WHEN WS-KEY(WS-IDX) = WS-SEARCH\n"
            "                   DISPLAY \"FOUND\"\n"
            "           END-SEARCH."
        )
        assert len(stmts) >= 1

    def test_search_with_varying(self):
        stmts, result = parse_procedure(
            "           SEARCH WS-TABLE VARYING WS-IDX\n"
            "               WHEN WS-ITEM(WS-IDX) = WS-TARGET\n"
            "                   DISPLAY \"FOUND\"\n"
            "           END-SEARCH."
        )
        assert len(stmts) >= 1

    def test_search_with_at_end(self):
        stmts, result = parse_procedure(
            "           SEARCH WS-TABLE\n"
            "               AT END\n"
            "                   DISPLAY \"NOT FOUND\"\n"
            "               WHEN WS-ITEM(WS-IDX) = WS-TARGET\n"
            "                   DISPLAY \"FOUND\"\n"
            "           END-SEARCH."
        )
        assert len(stmts) >= 1

    def test_search_with_multiple_when(self):
        stmts, result = parse_procedure(
            "           SEARCH WS-TABLE\n"
            "               WHEN WS-ITEM(WS-IDX) = \"A\"\n"
            "                   DISPLAY \"A\"\n"
            "               WHEN WS-ITEM(WS-IDX) = \"B\"\n"
            "                   DISPLAY \"B\"\n"
            "           END-SEARCH."
        )
        assert len(stmts) >= 1

    def test_search_terminated_by_period(self):
        stmts, result = parse_procedure(
            "           SEARCH WS-TABLE\n"
            "               WHEN WS-ITEM(WS-IDX) = WS-X\n"
            "                   DISPLAY \"OK\"."
        )
        assert len(stmts) >= 1


class TestSetStatementCoverage:
    """Tests for SET statement (lines 33-126)."""

    def test_set_to_true(self):
        stmts, result = parse_procedure(
            "           SET WS-FLAG TO TRUE."
        )
        set_stmts = [s for s in stmts if isinstance(s, SetStatement)]
        assert len(set_stmts) >= 1
        assert set_stmts[0].set_type == "TRUE"

    def test_set_to_false(self):
        stmts, result = parse_procedure(
            "           SET WS-FLAG TO FALSE."
        )
        set_stmts = [s for s in stmts if isinstance(s, SetStatement)]
        assert len(set_stmts) >= 1
        assert set_stmts[0].set_type == "FALSE"

    def test_set_to_value(self):
        stmts, result = parse_procedure(
            "           SET WS-INDEX TO 5."
        )
        set_stmts = [s for s in stmts if isinstance(s, SetStatement)]
        assert len(set_stmts) >= 1
        assert set_stmts[0].set_type == "TO"

    def test_set_up_by(self):
        stmts, result = parse_procedure(
            "           SET WS-INDEX UP BY 1."
        )
        set_stmts = [s for s in stmts if isinstance(s, SetStatement)]
        assert len(set_stmts) >= 1
        assert set_stmts[0].set_type == "UP_BY"

    def test_set_down_by(self):
        stmts, result = parse_procedure(
            "           SET WS-INDEX DOWN BY 1."
        )
        set_stmts = [s for s in stmts if isinstance(s, SetStatement)]
        assert len(set_stmts) >= 1
        assert set_stmts[0].set_type == "DOWN_BY"

    def test_set_multiple_targets(self):
        stmts, result = parse_procedure(
            "           SET WS-A WS-B WS-C TO TRUE."
        )
        set_stmts = [s for s in stmts if isinstance(s, SetStatement)]
        assert len(set_stmts) >= 1
        assert len(set_stmts[0].targets) >= 2

    def test_set_address_of(self):
        stmts, result = parse_procedure(
            "           SET ADDRESS OF WS-PTR TO WS-ADDR."
        )
        set_stmts = [s for s in stmts if isinstance(s, SetStatement)]
        assert len(set_stmts) >= 1

    def test_set_matches_false(self):
        from cobolparser.core.token_stream import TokenStream
        from cobolparser.parsers.statements.set_parser import SetStatementParser

        parser = SetStatementParser()
        stream = TokenStream([])
        assert parser.matches(stream) is False
