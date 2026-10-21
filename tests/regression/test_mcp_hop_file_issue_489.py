"""Issue #489: MCP ``where_from`` / ``impact_of_change`` looked a hop's file
up by ``(PROGRAM-ID, line, kind, statement)``. A statement at program line
13 and one of the same kind at line 13 of a PROCEDURE DIVISION copybook
shared the key, the last one written won, and one of them was cited in the
wrong file. Each hop now carries the file its edge was stamped with, and a
key two files claim is never guessed.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from cobolparser.mcp.codebase_index import lineage_index
from cobolparser.mcp.tools import CobolTools
from cobolparser.mcp.workspace import Workspace

COPYBOOK = "".join(f"      * comment {n}\n" for n in range(1, 12)) + (
    "       COPY-PARA.\n" "           MOVE WS-A TO WS-C.\n"
)

PROGRAM = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. COL.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-A PIC X(5).
       01  WS-B PIC X(5).
       01  WS-C PIC X(5).
       01  WS-D PIC X(5).
       PROCEDURE DIVISION.
       MAIN-PARA.
           PERFORM COPY-PARA
           ACCEPT WS-B
           MOVE WS-B TO WS-D
           DISPLAY WS-C WS-D
           STOP RUN.
           COPY PROCS.
"""


@pytest.fixture()
def root(tmp_path: Path) -> Path:
    (tmp_path / "cpy").mkdir()
    (tmp_path / "cpy" / "PROCS.cpy").write_text(COPYBOOK)
    (tmp_path / "COL.cbl").write_text(PROGRAM)
    (tmp_path / "cobol.yml").write_text("project:\n  copybook_path: [cpy]\n")
    return tmp_path


def _first_steps(tools: CobolTools, field: str) -> set[str]:
    answer = tools.where_from(field)["answer"]
    return {hit["path"][0] for hit in answer["hits"]}


def test_program_line_is_cited_in_the_program(root: Path) -> None:
    tools = CobolTools(Workspace(root))
    assert _first_steps(tools, "WS-D") == {"COL:WS-B (MOVE at COL.cbl:13)"}


def test_copybook_line_is_cited_in_the_copybook(root: Path) -> None:
    tools = CobolTools(Workspace(root))
    assert _first_steps(tools, "WS-C") == {"COL:WS-A (MOVE at cpy/PROCS.cpy:13)"}


def test_a_key_two_files_claim_is_not_guessed(root: Path) -> None:
    index = lineage_index(Workspace(root))
    assert index.edge_files[("COL", 13, "move", "MOVE")] is None
