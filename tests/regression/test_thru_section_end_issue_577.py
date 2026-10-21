"""Regression tests for issue #577: a SECTION as the end of a THRU range.

``range_members`` sliced the ordered procedures from the start key to the
end key, and a section's key is its header, so ``PERFORM S1 THRU S2`` gave
``['S1', 'A1', 'S2']`` and left out S2's paragraphs. MCP ``callers_of``
missed M1's PERFORM as a caller of B1 and B2.
"""

from pathlib import Path

from cobolparser import parse_cobol
from cobolparser.analysis.program_flow import ProgramFlowAnalyzer
from cobolparser.config import ProjectConfig
from cobolparser.mcp.tools import CobolTools
from cobolparser.mcp.workspace import Workspace

_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. THRU1.
       PROCEDURE DIVISION.
       MAIN SECTION.
       M1.
           PERFORM S1 THRU S2
           PERFORM A1 THRU S2
           PERFORM S1 THRU A1
           STOP RUN.
       S1 SECTION.
       A1.
           DISPLAY 'A1'.
       S2 SECTION.
       B1.
           DISPLAY 'B1'.
       B2.
           DISPLAY 'B2'.
       S3 SECTION.
       C1.
           DISPLAY 'C1'.
"""


def _ranges() -> list[list[str]]:
    result = parse_cobol(_SOURCE, filename="thru.cbl")
    assert result.ast is not None
    report = ProgramFlowAnalyzer().analyze(result.ast)
    return [e.range_members for e in report.edges if e.range_members]


def test_section_thru_section_includes_the_end_sections_paragraphs() -> None:
    ranges = _ranges()
    assert ["S1", "A1", "S2", "B1", "B2"] in ranges
    assert ["A1", "S2", "B1", "B2"] in ranges


def test_paragraph_end_is_unchanged() -> None:
    assert ["S1", "A1"] in _ranges()


def test_no_range_runs_into_the_next_section() -> None:
    assert not any("S3" in r or "C1" in r for r in _ranges())


def test_mcp_callers_of_end_section_paragraphs(tmp_path: Path) -> None:
    (tmp_path / "thru.cbl").write_text(_SOURCE)
    tools = CobolTools(Workspace(tmp_path, ProjectConfig()))
    for name in ("B1", "B2"):
        answer = tools.callers_of("thru.cbl", name)["answer"]
        callers = answer["procedures"][0]["callers"]
        assert any(c.get("from") == "M1" for c in callers), (name, callers)
