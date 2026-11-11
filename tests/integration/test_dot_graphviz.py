"""DOT output rendered by a real Graphviz `dot` (C7 of the 2026-11 corpus
review: the DOT generators were only ever checked as text).

Skipped where `dot` is not installed; CI installs graphviz for this.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from cobolparser import parse_cobol
from cobolparser.analysis.codebase import CodebaseGraphBuilder
from cobolparser.analysis.program_flow import ProgramFlowAnalyzer
from cobolparser.generators.flowchart import DotFlowchartGenerator

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(shutil.which("dot") is None, reason="graphviz not installed"),
]

ROOT = Path(__file__).parent.parent.parent
ENTERPRISE = ROOT / "tests" / "samples" / "enterprise"

# Labels that need escaping in DOT: quotes, backslashes, braces, angle
# brackets and pipes (record-shape metacharacters).
AWKWARD = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. AWKWARD.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-A  PIC X.
       PROCEDURE DIVISION.
       MAIN-PARA.
           IF WS-A = '"' OR WS-A = '\\' OR WS-A = '{' OR WS-A = '<'
              PERFORM 1-X THRU 1-X-EXIT
           END-IF
           EVALUATE WS-A
              WHEN '"}|' DISPLAY 'Q'
              WHEN OTHER GO TO 1-X-EXIT
           END-EVALUATE
           STOP RUN.
       1-X.
           DISPLAY '"<>{}|'.
       1-X-EXIT.
           EXIT.
"""


def _render(dot_source: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["dot", "-Tsvg", "-o", "/dev/null"],
        input=dot_source,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )


def _program_flow_dot(source: str, filename: str) -> str:
    result = parse_cobol(source, filename=filename)
    assert result.ast is not None
    return DotFlowchartGenerator().generate(ProgramFlowAnalyzer().analyze(result.ast))


@pytest.mark.parametrize(
    "path",
    [pytest.param(p, id=p.name) for p in sorted(ENTERPRISE.glob("*.cbl"))],
)
def test_program_flow_dot_renders(path: Path) -> None:
    rendered = _render(
        _program_flow_dot(path.read_text(encoding="utf-8", errors="replace"), path.name)
    )
    assert rendered.returncode == 0, rendered.stderr
    assert rendered.stderr.strip() == "", rendered.stderr


def test_awkward_labels_render() -> None:
    rendered = _render(_program_flow_dot(AWKWARD, "awkward.cbl"))
    assert rendered.returncode == 0, rendered.stderr
    assert rendered.stderr.strip() == "", rendered.stderr


def test_codebase_graph_dot_renders() -> None:
    graph = CodebaseGraphBuilder(
        copybook_paths=[str(ENTERPRISE / "copybooks")], workers=1
    ).build_from_directory(str(ENTERPRISE))
    rendered = _render(graph.to_dot())
    assert rendered.returncode == 0, rendered.stderr
    assert rendered.stderr.strip() == "", rendered.stderr
