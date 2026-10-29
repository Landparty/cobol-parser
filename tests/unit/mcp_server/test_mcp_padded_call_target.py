"""#754: a dynamic CALL target padded with trailing blanks (``MOVE 'SUBY    '
TO WS-P``, the PIC X(8) width) still names SUBY: CALL ignores the blanks, so
program-level ``callers_of`` must agree with ``codebase_overview``."""

from __future__ import annotations

from pathlib import Path

import pytest

from cobolparser.config import ProjectConfig
from cobolparser.mcp import CobolTools, Workspace

MAINP = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. MAINP.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-C PIC X.
       01 WS-P PIC X(8).
       PROCEDURE DIVISION.
           IF WS-C = 'A'
               MOVE 'SUBX' TO WS-P
           ELSE
               MOVE 'SUBY    ' TO WS-P
           END-IF
           CALL WS-P
           GOBACK.
"""


def _sub(name: str) -> str:
    return (
        "       IDENTIFICATION DIVISION.\n"
        f"       PROGRAM-ID. {name}.\n"
        "       PROCEDURE DIVISION.\n"
        "           GOBACK.\n"
    )


@pytest.fixture
def tools(tmp_path: Path) -> CobolTools:
    root = tmp_path / "shop"
    root.mkdir()
    (root / "MAINP.cbl").write_text(MAINP)
    (root / "SUBX.cbl").write_text(_sub("SUBX"))
    (root / "SUBY.cbl").write_text(_sub("SUBY"))
    return CobolTools(Workspace(root, ProjectConfig()))


@pytest.mark.parametrize("name", ["SUBX", "SUBY"])
def test_padded_literal_target_has_its_caller(tools: CobolTools, name: str) -> None:
    answer = tools.callers_of(None, name=name)["answer"]
    assert [c["program"] for c in answer["callers"]] == ["MAINP"]


def test_candidates_carry_no_trailing_blanks(tools: CobolTools) -> None:
    answer = tools.program_brief("MAINP.cbl")["answer"]
    (row,) = [r for r in answer["calls"] if r.get("dynamic")]
    assert row["candidates"] == ["SUBX", "SUBY"]
