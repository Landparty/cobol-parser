"""Regression tests for issue #533: no fall-through out of a DECLARATIVES section.

``build_fall_through_edges`` gave the last procedure of each declarative
section a FALL_THROUGH edge to the next procedure in source order -- the
next declarative section, or past END DECLARATIVES into the main code. A USE
procedure returns to the runtime when its section ends, so MCP
``callers_of("MAIN")`` reported a false caller and MAIN's fan-in was
inflated.
"""

from pathlib import Path

from cobolparser import parse_cobol
from cobolparser.analysis.complexity import ComplexityAnalyzer
from cobolparser.analysis.program_flow import ProgramFlowAnalyzer
from cobolparser.config import ProjectConfig
from cobolparser.mcp.tools import CobolTools
from cobolparser.mcp.workspace import Workspace

_HEAD = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. P18.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT IN-F ASSIGN TO 'IN' FILE STATUS IS WS-FS.
           SELECT OUT-F ASSIGN TO 'OUT' FILE STATUS IS WS-FS.
       DATA DIVISION.
       FILE SECTION.
       FD IN-F.
       01 IN-R PIC X(10).
       FD OUT-F.
       01 OUT-R PIC X(10).
       WORKING-STORAGE SECTION.
       01 WS-FS PIC XX.
       PROCEDURE DIVISION.
       DECLARATIVES.
       ERR-SEC SECTION.
           USE AFTER STANDARD ERROR PROCEDURE ON IN-F.
       ERR-PARA.
           DISPLAY 'IO ERROR ' WS-FS
           PERFORM LOG-IT.
       LOG-IT.
           DISPLAY 'LOGGED'.
"""

_SECOND = """\
       OUT-ERR SECTION.
           USE AFTER STANDARD ERROR PROCEDURE ON OUT-F.
       OUT-PARA.
           DISPLAY 'OUT ERROR'.
"""

_TAIL = """\
       END DECLARATIVES.
       MAIN SECTION.
       MAIN-PARA.
           OPEN INPUT IN-F
           STOP RUN.
"""

_ONE = _HEAD + _TAIL
_TWO = _HEAD + _SECOND + _TAIL


def _fall_throughs(source: str) -> set[tuple[str, str]]:
    result = parse_cobol(source, filename="p18.cbl")
    assert result.ast is not None
    report = ProgramFlowAnalyzer().analyze(result.ast)
    return {
        (e.source, e.target)
        for e in report.edges
        if e.edge_type.value == "FALL_THROUGH"
    }


def test_one_declarative_section_does_not_fall_into_main() -> None:
    assert _fall_throughs(_ONE) == {
        ("ERR-SEC", "ERR-PARA"),
        ("ERR-PARA", "LOG-IT"),
        ("MAIN", "MAIN-PARA"),
    }


def test_two_declarative_sections_do_not_fall_into_each_other() -> None:
    edges = _fall_throughs(_TWO)
    assert ("LOG-IT", "OUT-ERR") not in edges
    assert ("OUT-PARA", "MAIN") not in edges
    assert ("OUT-ERR", "OUT-PARA") in edges


def test_main_has_no_fan_in() -> None:
    result = parse_cobol(_TWO, filename="p18.cbl")
    assert result.ast is not None
    report = ComplexityAnalyzer().analyze(result.ast)
    main = next(p for p in report.procedures if p.name == "MAIN")
    assert main.fan_in == 0


def test_mcp_callers_of_main_is_empty(tmp_path: Path) -> None:
    (tmp_path / "p18.cbl").write_text(_ONE)
    tools = CobolTools(Workspace(tmp_path, ProjectConfig()))
    answer = tools.callers_of("p18.cbl", "MAIN")["answer"]
    assert [p["caller_count"] for p in answer["procedures"]] == [0]
