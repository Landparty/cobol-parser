"""Issue #536: ``data-items`` and MCP ``record_layout`` parsed a bare
copybook as a program with no divisions, so ``data-items`` printed
``"items": []`` and exited 0 and ``record_layout`` answered ``found: false``
-- though gen-data / decode take the same file.  Both now wrap a fragment
the way gen-data does, and cite the copybook's own lines.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from cobolparser.cli.parse import main
from cobolparser.config.project import ProjectConfig
from cobolparser.mcp import CobolTools, Workspace

COPYBOOK = (
    "       01  REC.\n"
    "           05  HDR       PIC X(2).\n"
    "           05  BODY      PIC X(10).\n"
    "           05  BODY-N    REDEFINES BODY.\n"
    "               10 BN-A   PIC 9(4).\n"
    "               10 BN-B   PIC 9(6).\n"
    "           05  TAIL      PIC X(3).\n"
)

EXPECTED = {
    "REC": (0, 15),
    "HDR": (0, 2),
    "BODY": (2, 10),
    "BODY-N": (2, 10),
    "BN-A": (2, 4),
    "BN-B": (6, 6),
    "TAIL": (12, 3),
}


def _run(argv: list[str]) -> int:
    saved = sys.argv
    sys.argv = ["cobol-parser", *argv]
    try:
        main()
    except SystemExit as exc:
        return int(exc.code or 0)
    finally:
        sys.argv = saved
    return 0


def test_data_items_lays_out_a_bare_copybook(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "rd.cpy"
    path.write_text(COPYBOOK)
    assert _run(["--no-config", "data-items", str(path)]) == 0
    captured = capsys.readouterr()
    output = json.loads(captured.out)
    got = {
        item["name"]: (item["byte_offset"], item["byte_length"])
        for item in output["items"]
    }
    assert got == EXPECTED
    assert "error" not in captured.err


def test_data_items_without_a_data_division_fails(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "nodata.cbl"
    path.write_text(
        "       IDENTIFICATION DIVISION.\n"
        "       PROGRAM-ID. NODATA.\n"
        "       PROCEDURE DIVISION.\n"
        "           STOP RUN.\n"
    )
    assert _run(["--no-config", "data-items", str(path)]) != 0
    assert "no DATA DIVISION" in capsys.readouterr().err


def test_mcp_record_layout_answers_for_a_copybook(tmp_path: Path) -> None:
    (tmp_path / "rd.cpy").write_text(COPYBOOK)
    tools = CobolTools(Workspace(tmp_path, ProjectConfig()))
    result = tools.record_layout("rd.cpy", "REC")
    answer = result["answer"]
    assert answer["found"] is True
    (record,) = answer["records"]
    assert (record["byte_offset"], record["byte_length"]) == (0, 15)
    fields = {field["name"]: field for field in record["fields"]}
    assert (fields["BN-B"]["byte_offset"], fields["BN-B"]["byte_length"]) == (6, 6)
    # Locations are the copybook's own lines, not the skeleton's.
    assert fields["TAIL"]["declared_at"]["file"].endswith("rd.cpy")
    assert fields["TAIL"]["declared_at"]["line"] == 7
    assert "partial-parse" not in [c["kind"] for c in result["caveats"]]
