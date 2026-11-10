"""PROCEDURE DIVISION paragraph / section boundary detection: branch gaps.

``procedure_boundaries`` decides whether the cursor sits at a new paragraph
or section. These tests drive it through ``CobolParser`` with real
procedure code and check the paragraphs and sections that come out, plus
the warnings: a stray period on its own line followed by a paragraph, a
section (across comment and blank lines), another period, a literal, a
verb, a numeric or decimal token or the end of the source; numeric
paragraph names; and ``EXIT SECTION`` straight after a section header.
"""

import pytest

from cobolparser import CobolParser, ErrorRecoveryMode

PRE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. BOUND.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  X                   PIC 9.
       PROCEDURE DIVISION.
"""


def _parse(body: str):
    parser = CobolParser(error_recovery=ErrorRecoveryMode.COLLECT_ALL)
    result = parser.parse(PRE + body, "bound.cbl")
    assert result.ast is not None
    assert result.errors == []
    return result


def _paragraphs(result) -> list[str]:
    return [p.paragraph_name for p in result.ast.procedure_division.paragraphs]


def _statements(paragraph) -> list[str]:
    return [s.to_dict()["statement_type"] for s in paragraph.statements]


def _section(result, name):
    for section in result.ast.procedure_division.sections:
        if section.section_name == name:
            return section
    raise AssertionError(f"no section {name}")


class TestStrayPeriod:
    def test_followed_by_a_paragraph(self):
        result = _parse("""\
       P1.
           DISPLAY 'A'.
           .
       P2.
           DISPLAY 'B'.
""")
        assert result.warnings == []
        assert _paragraphs(result) == ["P1", "P2"]
        p1, p2 = result.ast.procedure_division.paragraphs
        assert _statements(p1) == ["DISPLAY"]
        assert _statements(p2) == ["DISPLAY"]

    def test_followed_by_a_section_across_comment_and_blank_lines(self):
        result = _parse("""\
       P1.
           DISPLAY 'A'.
           .
      * a comment between the period and the section

       S2 SECTION.
       P2.
           DISPLAY 'B'.
""")
        assert result.warnings == []
        assert _paragraphs(result) == ["P1"]
        s2 = _section(result, "S2")
        assert [p.paragraph_name for p in s2.paragraphs] == ["P2"]

    def test_followed_by_many_blank_lines(self):
        result = _parse(
            "       P1.\n           DISPLAY 'A'.\n           .\n"
            + "\n" * 12
            + "       P2.\n           DISPLAY 'B'.\n"
        )
        assert result.warnings == []
        assert _paragraphs(result) == ["P1", "P2"]

    def test_followed_by_a_long_comment_block(self):
        # Comment lines are dropped by fixed-format normalization, so a long
        # block of them does not push P2 out of the boundary lookahead.
        result = _parse(
            "       P1.\n           DISPLAY 'A'.\n           .\n"
            + "      * comment line\n" * 12
            + "       P2.\n           DISPLAY 'B'.\n"
        )
        assert result.warnings == []
        assert _paragraphs(result) == ["P1", "P2"]
        assert all(
            _statements(p) == ["DISPLAY"]
            for p in result.ast.procedure_division.paragraphs
        )

    def test_followed_by_a_long_floating_comment_block(self):
        # ``*>`` comments survive normalization as tokens. Twelve of them
        # push P2 past the boundary lookahead: the stray period is then
        # consumed as an empty sentence and P2 is found on the next pass.
        result = _parse(
            "       P1.\n           DISPLAY 'A'.\n           .\n"
            + "           *> floating comment\n" * 12
            + "       P2.\n           DISPLAY 'B'.\n"
        )
        assert result.warnings == []
        assert _paragraphs(result) == ["P1", "P2"]
        assert all(
            _statements(p) == ["DISPLAY"]
            for p in result.ast.procedure_division.paragraphs
        )

    def test_followed_by_another_period(self):
        result = _parse("""\
       P1.
           DISPLAY 'A'.
           .
           .
       P2.
           DISPLAY 'B'.
""")
        assert result.warnings == []
        assert _paragraphs(result) == ["P1", "P2"]

    def test_followed_by_a_numeric_paragraph_name(self):
        result = _parse("""\
       P1.
           DISPLAY 'A'.
           .
       2000.
           DISPLAY 'B'.
""")
        assert result.warnings == []
        assert _paragraphs(result) == ["P1", "2000"]

    def test_followed_by_a_verb_and_its_period(self):
        # ``RESUME.`` has the shape of a paragraph header, but a verb is
        # never a procedure name: it stays a statement of P1.
        result = _parse("""\
       P1.
           DISPLAY 'A'.
           . RESUME.
       P2.
           DISPLAY 'B'.
""")
        assert result.warnings == []
        assert _paragraphs(result) == ["P1", "P2"]
        assert _statements(result.ast.procedure_division.paragraphs[0]) == [
            "DISPLAY",
            "RESUME",
        ]

    def test_followed_by_a_name_that_is_not_a_header(self):
        result = _parse("""\
       P1.
           DISPLAY 'A'.
           . P2 DISPLAY 'B'.
""")
        assert _paragraphs(result) == ["P1"]
        assert any("Unparsed tokens starting at 'P2'" in w for w in result.warnings)

    def test_followed_by_a_literal(self):
        result = _parse("""\
       P1.
           DISPLAY 'A'.
           . 'X'.
       P2.
           DISPLAY 'B'.
""")
        assert _paragraphs(result) == ["P1", "P2"]
        assert any("Unparsed tokens starting at 'X'" in w for w in result.warnings)

    def test_followed_by_a_decimal_number(self):
        # Only an all-digit token can be a paragraph name.
        result = _parse("""\
       P1.
           DISPLAY 'A'.
           . 1.5 .
       P2.
""")
        assert _paragraphs(result) == ["P1", "P2"]
        assert any("Unparsed tokens starting at '1.5'" in w for w in result.warnings)

    def test_followed_by_a_name_at_end_of_source(self):
        result = _parse("""\
       P1.
           DISPLAY 'A'.
           . P9""")
        assert _paragraphs(result) == ["P1"]
        assert any("Unparsed tokens starting at 'P9'" in w for w in result.warnings)

    def test_at_end_of_source(self):
        result = _parse("       P1.\n           DISPLAY 'A'.\n           .\n")
        assert result.warnings == []
        assert _paragraphs(result) == ["P1"]


class TestHeaders:
    def test_numeric_paragraph_names_in_perform_thru(self):
        result = _parse("""\
       1000-MAIN.
           PERFORM 2000 THRU 2999.
           STOP RUN.
       2000.
           DISPLAY 'A'.
       2999.
           EXIT.
""")
        assert result.warnings == []
        assert _paragraphs(result) == ["1000-MAIN", "2000", "2999"]

    def test_missing_period_before_next_paragraph(self):
        result = _parse("""\
       P1.
           DISPLAY 'A'
       P2.
           DISPLAY 'B'.
""")
        assert _paragraphs(result) == ["P1", "P2"]
        assert any(
            "missing its terminating period" in w and "'P2'" in w
            for w in result.warnings
        )

    def test_paragraph_name_with_its_period_on_the_next_line(self):
        result = _parse("""\
       P1.
           DISPLAY 'A'.
       P2
           .
           DISPLAY 'B'.
""")
        assert result.warnings == []
        assert _paragraphs(result) == ["P1", "P2"]

    def test_missing_period_before_next_section(self):
        result = _parse("""\
       P1.
           DISPLAY 'A'
       S2 SECTION.
       P2.
           DISPLAY 'B'.
""")
        assert _paragraphs(result) == ["P1"]
        assert [p.paragraph_name for p in _section(result, "S2").paragraphs] == ["P2"]
        assert any(
            "missing its terminating period" in w and "'S2'" in w
            for w in result.warnings
        )

    def test_exit_section_straight_after_a_section_header(self):
        result = _parse("""\
       MAIN SECTION.
           EXIT SECTION.
       P1.
           DISPLAY 'A'.
""")
        assert result.warnings == []
        main = _section(result, "MAIN")
        assert [p.paragraph_name for p in main.paragraphs][-1] == "P1"
        assert "EXIT" not in [
            s.section_name for s in result.ast.procedure_division.sections
        ]
