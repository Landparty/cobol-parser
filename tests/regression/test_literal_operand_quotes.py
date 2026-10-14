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


_TYPED_HEADER = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TYPED.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 X      PIC X.
       01 Z      PIC X.
       01 WS-IN  PIC X(20).
       01 WS-OUT PIC X(20).
       PROCEDURE DIVISION.
           STRING WS-IN DELIMITED BY X'00' INTO WS-OUT.
           UNSTRING WS-IN DELIMITED BY X'00' INTO WS-OUT.
           INSPECT WS-IN REPLACING ALL X'00' BY SPACE.
           CALL 'puts' USING BY REFERENCE Z'hello'.
           CALL 'SUBPGM' USING BY CONTENT 'A' X'00'.
           DISPLAY WS-OUT.
           STOP RUN.
"""


class TestTypedLiteralPrefix:
    """The prefix letter of ``X'00'`` / ``Z'hello'`` is not the data item X/Z."""

    def _ast(self, source: str = _TYPED_HEADER):
        result = parse_cobol(source)
        assert result.errors == []
        return result.ast

    def test_unused_variables_still_flags_x_and_z(self) -> None:
        report = UnusedVariableAnalyzer().analyze(self._ast())
        assert sorted(i.name for i in report.unused_items) == ["X", "Z"]

    def test_xref_attributes_no_reference_to_x_or_z(self) -> None:
        report = XrefAnalyzer().analyze(self._ast())
        refs = {e.name: len(e.references) for e in report.entries}
        assert refs["X"] == 0
        assert refs["Z"] == 0

    def test_xref_reports_no_undefined_prefix_letter(self) -> None:
        source = _TYPED_HEADER.replace("       01 X      PIC X.\n", "").replace(
            "       01 Z      PIC X.\n", ""
        )
        assert XrefAnalyzer().analyze(self._ast(source)).undefined == []

    def test_lineage_draws_no_flow_from_x(self) -> None:
        report = FieldFlowAnalyzer().analyze(self._ast())
        sources = {e.source.to_dict().get("name") for e in report.edges}
        assert "X" not in sources
        assert "Z" not in sources

    def test_gen_fixtures_does_not_report_literal_arguments_unresolved(
        self, tmp_path
    ) -> None:
        from cobolparser.generators import ProgramFixtureGenerator

        path = tmp_path / "TYPED.cbl"
        path.write_text(_TYPED_HEADER)
        bundle = ProgramFixtureGenerator().generate_from_file(str(path), seed=1)
        assert not [u for u in bundle.unresolved if "argument" in u]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ('"A"', True),
        ("'IT''S'", True),
        ("X'00'", True),
        ('z"hello"', True),
        ("NX'0041'", True),
        ("X", False),
        ("WS-X", False),
        ("TBL(1)", False),
        ("5", False),
    ],
)
def test_is_quoted_literal(text: str, expected: bool) -> None:
    from cobolparser._literals import is_quoted_literal

    assert is_quoted_literal(text) is expected


def test_quoted_literal_re_keeps_a_name_ending_in_a_prefix_letter() -> None:
    from cobolparser._literals import QUOTED_LITERAL_RE

    assert QUOTED_LITERAL_RE.sub(" ", "WS-X'00'") == "WS-X "
    assert QUOTED_LITERAL_RE.sub(" ", "A X'00' Z'B' \"C\"").split() == ["A"]
