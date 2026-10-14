"""Issue #330: string-literal operands keep their quotes.

STRING, UNSTRING, INSPECT, CALL USING, SET and INITIALIZE REPLACING stored a
literal operand's decoded ``token.value``, so ``'A'`` and the data item ``A``
produced the same AST value (and ``X'00'`` the two characters ``00``). They
now follow the MOVE / DISPLAY convention: a typed literal keeps its source
spelling from ``raw_value``, any other is re-quoted by ``quote_literal``.
"""

from __future__ import annotations

import json

import pytest

from cobolparser import UnusedVariableAnalyzer, parse_cobol
from cobolparser.analysis.field_lineage import FieldFlowAnalyzer
from cobolparser.analysis.xref import XrefAnalyzer

_HEADER = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. LITQ.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 A        PIC X(10).
       01 B        PIC X(10).
       01 C        PIC 9(4).
       01 WS-CODE  PIC X(8).
       01 WS-FLAG  PIC X(8).
       01 WS-OUT   PIC X(20).
       PROCEDURE DIVISION.
"""


def _parse(*statements: str):
    body = "".join(f"           {s}\n" for s in statements)
    result = parse_cobol(_HEADER + body + "           STOP RUN.\n")
    assert result.errors == []
    assert result.warnings == []
    return result


def _first(result, cls_name: str):
    for stmt in result.ast.get_all_statements():
        if type(stmt).__name__ == cls_name:
            return stmt
    raise AssertionError(f"no {cls_name}")


class TestParsedValues:
    def test_string_operands_and_delimiter(self) -> None:
        stmt = _first(
            _parse("STRING 'A' X'00' A DELIMITED BY ',' INTO B."), "StringStatement"
        )
        assert stmt.operands == ['"A"', "X'00'", "A"]
        assert stmt.delimiters == ['","']

    def test_unstring_delimiter(self) -> None:
        stmt = _first(
            _parse("UNSTRING A DELIMITED BY ALL '-' OR B INTO WS-OUT."),
            "UnstringStatement",
        )
        assert stmt.delimiters == ['"-"', "B"]

    def test_call_using_literals(self) -> None:
        stmt = _first(
            _parse("CALL 'PGM' USING BY CONTENT 'A' X'00' Z'A' 5 A."),
            "CallStatement",
        )
        assert [p.name for p in stmt.using_parameters] == [
            '"A"',
            "X'00'",
            "Z'A'",
            "5",
            "A",
        ]

    def test_inspect_replacing_tallying_converting(self) -> None:
        result = _parse(
            "INSPECT A REPLACING ALL 'A' BY SPACE.",
            "INSPECT A TALLYING C FOR ALL 'X' 'Y' BEFORE INITIAL B.",
            "INSPECT A CONVERTING 'AB' TO X'4142'.",
        )
        replacing, tallying, converting = [
            s
            for s in result.ast.get_all_statements()
            if type(s).__name__ == "InspectStatement"
        ]
        assert replacing.replacing_clauses[0]["from_value"] == '"A"'
        assert replacing.replacing_clauses[0]["to_value"] == "SPACE"
        assert [c["value"] for c in tallying.tallying_clauses] == ['"X"', '"Y"']
        assert tallying.tallying_clauses[-1]["before"] == "B"
        assert converting.converting_from == '"AB"'
        assert converting.converting_to == "X'4142'"

    def test_set_to_literal(self) -> None:
        stmt = _first(_parse("SET A TO X'00'."), "SetStatement")
        assert stmt.value == "X'00'"

    def test_initialize_replacing_by_literal(self) -> None:
        stmt = _first(
            _parse("INITIALIZE A REPLACING ALPHANUMERIC BY X'FF'."),
            "InitializeStatement",
        )
        assert stmt.replacing_clauses[0]["by_value"] == "X'FF'"

    @pytest.mark.parametrize(
        "statement",
        [
            "STRING 'IT''S' DELIMITED BY SIZE INTO B.",
            'STRING "IT\'S" DELIMITED BY SIZE INTO B.',
        ],
    )
    def test_embedded_delimiter_is_re_escaped(self, statement: str) -> None:
        stmt = _first(_parse(statement), "StringStatement")
        assert stmt.operands == ['"IT\'S"']


class TestAnalyzers:
    """The literal's text spelling a declared name no longer reads as it."""

    _STATEMENTS = (
        "STRING 'WS-CODE' DELIMITED BY SIZE INTO WS-OUT.",
        "CALL 'SUBPGM' USING BY CONTENT 'WS-FLAG' 'STRLIT'.",
        "DISPLAY WS-OUT A B C.",
    )

    def test_unused_variables_reports_the_literal_lookalikes(self) -> None:
        report = UnusedVariableAnalyzer().analyze(_parse(*self._STATEMENTS).ast)
        assert sorted(i.name for i in report.unused_items) == ["WS-CODE", "WS-FLAG"]

    def test_xref_has_no_entry_for_a_call_literal(self) -> None:
        report = XrefAnalyzer().analyze(_parse(*self._STATEMENTS).ast)
        names = {e.name for e in report.entries}
        assert "STRLIT" not in names
        assert "STRLIT" not in report.undefined
        code = next(e for e in report.entries if e.name == "WS-CODE")
        assert code.references == []

    def test_lineage_has_no_flow_from_the_literal_lookalike(self) -> None:
        report = FieldFlowAnalyzer().analyze(_parse(*self._STATEMENTS).ast)
        sources = json.dumps([e.source.to_dict() for e in report.edges])
        assert "WS-CODE" not in sources
