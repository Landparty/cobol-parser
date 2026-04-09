"""Tests for COBOL procedure division section support.

Verifies that sections are properly parsed, paragraphs are correctly
associated with their enclosing sections, and the AST is well-formed.
"""

from cobolparser import ErrorRecoveryMode, parse_cobol
from cobolparser.models.program import CobolDivision, CobolParagraph, CobolSection


def parse(src: str):
    """Parse COBOL source with error recovery enabled."""
    return parse_cobol(
        src, filename="<test>", error_recovery=ErrorRecoveryMode.COLLECT_ALL
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _proc_div(result) -> CobolDivision:
    """Extract the PROCEDURE division from a parse result."""
    div = result.ast.procedure_division
    assert div is not None, "Expected PROCEDURE DIVISION in AST"
    return div


def _get_sections(div: CobolDivision) -> list[CobolSection]:
    """Get only CobolSection objects from a division (not paragraphs)."""
    return [s for s in div.sections if isinstance(s, CobolSection)]


def _get_all_stmt_types(result) -> list[str]:
    """Collect all statement types from the AST."""
    stmts = result.ast.get_all_statements()
    return [s.statement_type for s in stmts]


# ---------------------------------------------------------------------------
# Basic section parsing
# ---------------------------------------------------------------------------

class TestBasicSectionParsing:
    """Test that sections are recognized and created in the AST."""

    def test_single_section_with_paragraph(self):
        src = (
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. SECTEST.\n"
            "       PROCEDURE DIVISION.\n"
            "       INIT-SECTION SECTION.\n"
            "       INIT-PARA.\n"
            "           DISPLAY 'HELLO'.\n"
        )
        result = parse(src)
        div = _proc_div(result)
        sections = _get_sections(div)

        assert len(sections) == 1
        assert sections[0].section_name == "INIT-SECTION"

    def test_section_contains_its_paragraphs(self):
        src = (
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. SECTEST.\n"
            "       PROCEDURE DIVISION.\n"
            "       MAIN-SECTION SECTION.\n"
            "       MAIN-PARA.\n"
            "           DISPLAY 'MAIN'.\n"
        )
        result = parse(src)
        div = _proc_div(result)
        sections = _get_sections(div)

        assert len(sections) == 1
        section = sections[0]
        assert len(section.paragraphs) >= 1
        para_names = [p.paragraph_name for p in section.paragraphs]
        assert "MAIN-PARA" in para_names

    def test_section_paragraph_has_statements(self):
        src = (
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. SECTEST.\n"
            "       PROCEDURE DIVISION.\n"
            "       WORK-SECTION SECTION.\n"
            "       WORK-PARA.\n"
            "           DISPLAY 'WORKING'.\n"
            "           MOVE A TO B.\n"
        )
        result = parse(src)
        div = _proc_div(result)
        sections = _get_sections(div)
        section = sections[0]

        assert len(section.paragraphs) >= 1
        para = section.paragraphs[0]
        assert len(para.statements) >= 1

        stmt_types = [s.statement_type for s in para.statements]
        assert "DISPLAY" in stmt_types

    def test_section_without_explicit_paragraph(self):
        """Statements directly in a section (no paragraph name) should be captured."""
        src = (
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. SECTEST.\n"
            "       PROCEDURE DIVISION.\n"
            "       DIRECT-SECTION SECTION.\n"
            "           DISPLAY 'DIRECT'.\n"
        )
        result = parse(src)
        stmt_types = _get_all_stmt_types(result)
        assert "DISPLAY" in stmt_types


# ---------------------------------------------------------------------------
# Multiple sections
# ---------------------------------------------------------------------------

class TestMultipleSections:
    """Test programs with multiple sections."""

    def test_two_sections(self):
        src = (
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. TWOSEC.\n"
            "       PROCEDURE DIVISION.\n"
            "       ALPHA-SECTION SECTION.\n"
            "       ALPHA-PARA.\n"
            "           DISPLAY 'ALPHA'.\n"
            "       BETA-SECTION SECTION.\n"
            "       BETA-PARA.\n"
            "           DISPLAY 'BETA'.\n"
        )
        result = parse(src)
        div = _proc_div(result)
        sections = _get_sections(div)

        section_names = [s.section_name for s in sections]
        assert "ALPHA-SECTION" in section_names
        assert "BETA-SECTION" in section_names

    def test_each_section_owns_its_paragraphs(self):
        src = (
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. OWN.\n"
            "       PROCEDURE DIVISION.\n"
            "       SEC-A SECTION.\n"
            "       PARA-A1.\n"
            "           DISPLAY 'A1'.\n"
            "       PARA-A2.\n"
            "           DISPLAY 'A2'.\n"
            "       SEC-B SECTION.\n"
            "       PARA-B1.\n"
            "           DISPLAY 'B1'.\n"
        )
        result = parse(src)
        div = _proc_div(result)

        sec_a = div.get_section_by_name("SEC-A")
        sec_b = div.get_section_by_name("SEC-B")

        assert isinstance(sec_a, CobolSection)
        assert isinstance(sec_b, CobolSection)

        a_para_names = [p.paragraph_name for p in sec_a.paragraphs]
        b_para_names = [p.paragraph_name for p in sec_b.paragraphs]

        assert "PARA-A1" in a_para_names
        assert "PARA-A2" in a_para_names
        assert "PARA-B1" in b_para_names
        # B should NOT contain A's paragraphs
        assert "PARA-A1" not in b_para_names

    def test_three_sections_statement_counts(self):
        src = (
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. THREE.\n"
            "       PROCEDURE DIVISION.\n"
            "       SEC1 SECTION.\n"
            "       P1.\n"
            "           DISPLAY 'ONE'.\n"
            "       SEC2 SECTION.\n"
            "       P2.\n"
            "           DISPLAY 'TWO'.\n"
            "           DISPLAY 'TWO-B'.\n"
            "       SEC3 SECTION.\n"
            "       P3.\n"
            "           DISPLAY 'THREE'.\n"
        )
        result = parse(src)
        stmt_types = _get_all_stmt_types(result)
        assert stmt_types.count("DISPLAY") >= 4


# ---------------------------------------------------------------------------
# Mixed: top-level paragraphs before sections
# ---------------------------------------------------------------------------

class TestMixedParagraphsAndSections:
    """Test programs that have top-level paragraphs followed by sections."""

    def test_paragraph_before_section(self):
        src = (
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. MIXED.\n"
            "       PROCEDURE DIVISION.\n"
            "       TOP-PARA.\n"
            "           DISPLAY 'TOP'.\n"
            "       MY-SECTION SECTION.\n"
            "       SEC-PARA.\n"
            "           DISPLAY 'SEC'.\n"
        )
        result = parse(src)
        div = _proc_div(result)

        # Top-level paragraph should exist on the division
        top_para_names = [p.paragraph_name for p in div.paragraphs]
        assert "TOP-PARA" in top_para_names

        # Section should contain its paragraph
        sections = _get_sections(div)
        assert len(sections) == 1
        sec_para_names = [p.paragraph_name for p in sections[0].paragraphs]
        assert "SEC-PARA" in sec_para_names

    def test_all_statements_reachable(self):
        """get_all_statements() should find statements in both top-level and sections."""
        src = (
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. REACH.\n"
            "       PROCEDURE DIVISION.\n"
            "       TOP-PARA.\n"
            "           DISPLAY 'A'.\n"
            "       MY-SECTION SECTION.\n"
            "       SEC-PARA.\n"
            "           DISPLAY 'B'.\n"
        )
        result = parse(src)
        stmt_types = _get_all_stmt_types(result)
        assert stmt_types.count("DISPLAY") >= 2


# ---------------------------------------------------------------------------
# Section with multiple statement types
# ---------------------------------------------------------------------------

class TestSectionWithVariousStatements:
    """Test sections with different statement types."""

    def test_section_with_move_and_display(self):
        src = (
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. MULTI.\n"
            "       PROCEDURE DIVISION.\n"
            "       WORK-SECTION SECTION.\n"
            "       WORK-PARA.\n"
            "           MOVE 1 TO WS-A.\n"
            "           DISPLAY WS-A.\n"
        )
        result = parse(src)
        stmt_types = _get_all_stmt_types(result)
        assert "MOVE" in stmt_types
        assert "DISPLAY" in stmt_types

    def test_section_with_perform(self):
        src = (
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. PERF.\n"
            "       PROCEDURE DIVISION.\n"
            "       MAIN-SECTION SECTION.\n"
            "       MAIN-PARA.\n"
            "           PERFORM HELPER-PARA.\n"
            "       HELPER-SECTION SECTION.\n"
            "       HELPER-PARA.\n"
            "           DISPLAY 'HELPER'.\n"
        )
        result = parse(src)
        stmt_types = _get_all_stmt_types(result)
        assert "PERFORM" in stmt_types
        assert "DISPLAY" in stmt_types

    def test_section_with_if_statement(self):
        src = (
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. IFTEST.\n"
            "       PROCEDURE DIVISION.\n"
            "       LOGIC-SECTION SECTION.\n"
            "       LOGIC-PARA.\n"
            "           IF WS-A = 1\n"
            "               DISPLAY 'YES'\n"
            "           END-IF.\n"
        )
        result = parse(src)
        stmt_types = _get_all_stmt_types(result)
        assert "IF" in stmt_types


# ---------------------------------------------------------------------------
# AST structure and API tests
# ---------------------------------------------------------------------------

class TestSectionASTStructure:
    """Test the AST structure for sections."""

    def test_section_to_dict(self):
        src = (
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. DICT.\n"
            "       PROCEDURE DIVISION.\n"
            "       MY-SECTION SECTION.\n"
            "       MY-PARA.\n"
            "           DISPLAY 'HI'.\n"
        )
        result = parse(src)
        div = _proc_div(result)
        sections = _get_sections(div)
        assert len(sections) >= 1

        d = sections[0].to_dict()
        assert d["node_type"] == "Section"
        assert d["section_name"] == "MY-SECTION"
        assert "paragraphs" in d

    def test_division_to_dict_includes_sections(self):
        src = (
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. DDICT.\n"
            "       PROCEDURE DIVISION.\n"
            "       S1 SECTION.\n"
            "       P1.\n"
            "           DISPLAY 'X'.\n"
        )
        result = parse(src)
        div = _proc_div(result)
        d = div.to_dict()

        assert "sections" in d
        assert "S1" in d["sections"]

    def test_find_procedures_returns_sections(self):
        src = (
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. FINDP.\n"
            "       PROCEDURE DIVISION.\n"
            "       FIND-SECTION SECTION.\n"
            "       FIND-PARA.\n"
            "           DISPLAY 'FOUND'.\n"
        )
        result = parse(src)
        procs = result.ast.find_procedures(proc_type="SECTION")
        assert len(procs) >= 1
        assert any(
            isinstance(p, CobolSection) and p.section_name == "FIND-SECTION"
            for p in procs
        )

    def test_find_procedures_returns_paragraphs_in_sections(self):
        src = (
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. FINDP2.\n"
            "       PROCEDURE DIVISION.\n"
            "       MY-SECTION SECTION.\n"
            "       INNER-PARA.\n"
            "           DISPLAY 'INNER'.\n"
        )
        result = parse(src)
        procs = result.ast.find_procedures(proc_type="PARAGRAPH")
        para_names = [
            p.paragraph_name for p in procs if isinstance(p, CobolParagraph)
        ]
        assert "INNER-PARA" in para_names

    def test_get_section_by_name(self):
        src = (
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. BYNAME.\n"
            "       PROCEDURE DIVISION.\n"
            "       LOOKUP-SECTION SECTION.\n"
            "       LOOKUP-PARA.\n"
            "           DISPLAY 'LOOKUP'.\n"
        )
        result = parse(src)
        div = _proc_div(result)
        section = div.get_section_by_name("LOOKUP-SECTION")
        assert section is not None
        assert isinstance(section, CobolSection)

    def test_section_metadata_counts(self):
        src = (
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. META.\n"
            "       PROCEDURE DIVISION.\n"
            "       S1 SECTION.\n"
            "       P1.\n"
            "           DISPLAY 'A'.\n"
            "       S2 SECTION.\n"
            "       P2.\n"
            "           DISPLAY 'B'.\n"
        )
        result = parse(src)
        div = _proc_div(result)
        assert div.metadata.get("section_count") == 2
        assert div.metadata.get("paragraph_count") >= 2

    def test_program_statistics_include_sections(self):
        src = (
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. STATS.\n"
            "       PROCEDURE DIVISION.\n"
            "       STAT-SECTION SECTION.\n"
            "       STAT-PARA.\n"
            "           DISPLAY 'STAT'.\n"
        )
        result = parse(src)
        stats = result.ast.get_statistics()
        assert stats["procedure_count"] >= 2  # section + paragraph


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestSectionEdgeCases:
    """Test edge cases for section handling."""

    def test_empty_section(self):
        """A section with no paragraphs or statements should not crash."""
        src = (
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. EMPTY.\n"
            "       PROCEDURE DIVISION.\n"
            "       EMPTY-SECTION SECTION.\n"
            "       NEXT-SECTION SECTION.\n"
            "       NEXT-PARA.\n"
            "           DISPLAY 'NEXT'.\n"
        )
        result = parse(src)
        div = _proc_div(result)
        sections = _get_sections(div)
        section_names = [s.section_name for s in sections]
        assert "EMPTY-SECTION" in section_names
        assert "NEXT-SECTION" in section_names

    def test_section_no_paragraphs_only_statements(self):
        """Section with statements but no named paragraphs."""
        src = (
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. NOPARA.\n"
            "       PROCEDURE DIVISION.\n"
            "       FLAT-SECTION SECTION.\n"
            "           DISPLAY 'FLAT'.\n"
        )
        result = parse(src)
        stmt_types = _get_all_stmt_types(result)
        assert "DISPLAY" in stmt_types

    def test_section_in_json_export(self):
        """Sections should appear in JSON export."""
        src = (
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. JSON.\n"
            "       PROCEDURE DIVISION.\n"
            "       JSON-SECTION SECTION.\n"
            "       JSON-PARA.\n"
            "           DISPLAY 'JSON'.\n"
        )
        result = parse(src)
        json_str = result.ast.to_json()
        assert "JSON-SECTION" in json_str

    def test_program_with_only_sections(self):
        """Program where all procedure code is in sections (no top-level paragraphs)."""
        src = (
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. ALLSEC.\n"
            "       PROCEDURE DIVISION.\n"
            "       INIT SECTION.\n"
            "       INIT-START.\n"
            "           DISPLAY 'INIT'.\n"
            "       PROCESS SECTION.\n"
            "       PROCESS-START.\n"
            "           DISPLAY 'PROCESS'.\n"
            "       CLEANUP SECTION.\n"
            "       CLEANUP-START.\n"
            "           DISPLAY 'CLEANUP'.\n"
        )
        result = parse(src)
        div = _proc_div(result)
        sections = _get_sections(div)

        assert len(sections) == 3
        # No top-level paragraphs
        assert len(div.paragraphs) == 0

        stmt_types = _get_all_stmt_types(result)
        assert stmt_types.count("DISPLAY") >= 3

    def test_section_with_multiple_paragraphs(self):
        """A single section can contain multiple paragraphs."""
        src = (
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. MULTIPARA.\n"
            "       PROCEDURE DIVISION.\n"
            "       BIG-SECTION SECTION.\n"
            "       PARA-1.\n"
            "           DISPLAY 'ONE'.\n"
            "       PARA-2.\n"
            "           DISPLAY 'TWO'.\n"
            "       PARA-3.\n"
            "           DISPLAY 'THREE'.\n"
        )
        result = parse(src)
        div = _proc_div(result)
        section = div.get_section_by_name("BIG-SECTION")
        assert isinstance(section, CobolSection)
        assert len(section.paragraphs) == 3

        para_names = [p.paragraph_name for p in section.paragraphs]
        assert para_names == ["PARA-1", "PARA-2", "PARA-3"]
