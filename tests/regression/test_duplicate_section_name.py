"""Two sections with one name: the second used to replace the first, and
the first section's statements vanished with no diagnostic (open-source
corpus finding). The input is invalid COBOL; the parser now warns and
keeps the paragraphs of both under the one section.
"""

from cobolparser import CobolParser, ErrorRecoveryMode

SRC = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. T.
       PROCEDURE DIVISION.
       S1 SECTION.
       P1.
           DISPLAY "ONE".
       S2 SECTION.
       P2.
           DISPLAY "TWO".
       S1 SECTION.
       P3.
           DISPLAY "THREE"
           STOP RUN.
"""


def test_duplicate_section_keeps_both_bodies_and_warns():
    result = CobolParser(error_recovery=ErrorRecoveryMode.COLLECT_ALL).parse(SRC)
    assert result.ast is not None
    proc = result.ast.get_division("PROCEDURE")
    sections = proc.find_all_by_type("CobolSection")
    assert [s.section_name for s in sections] == ["S1", "S2"]
    s1 = sections[0]
    assert [p.paragraph_name for p in s1.paragraphs] == ["P1", "P3"]
    assert s1.get_metadata("duplicate_header_lines") == [10]
    assert len(result.ast.find_all_by_type("DisplayStatement")) == 3
    assert len(result.ast.find_all_by_type("StopStatement")) == 1
    assert any(
        "Section 'S1' is defined again at line 10 (first at line 4)" in w
        for w in result.warnings
    ), result.warnings


def test_unique_sections_have_no_duplicate_metadata():
    src = SRC.replace(
        "       S1 SECTION.\n       P3.", "       S3 SECTION.\n       P3."
    )
    result = CobolParser(error_recovery=ErrorRecoveryMode.COLLECT_ALL).parse(src)
    sections = result.ast.get_division("PROCEDURE").find_all_by_type("CobolSection")
    assert [s.section_name for s in sections] == ["S1", "S2", "S3"]
    assert all(s.get_metadata("duplicate_header_lines") is None for s in sections)
    assert not result.warnings
