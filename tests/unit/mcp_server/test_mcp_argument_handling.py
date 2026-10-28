"""MCP tool arguments read as asked: case, a program without a file, a name
declared only in another program unit, ``define`` entries."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from cobolparser.config.project import ProjectConfig
from cobolparser.mcp import CobolTools, ToolError, Workspace
from cobolparser.mcp.workspace import _defined_symbols

ENTERPRISE = Path(__file__).resolve().parents[2] / "samples" / "enterprise"


@pytest.fixture
def tools(tmp_path: Path) -> CobolTools:
    target = tmp_path / "src"
    shutil.copytree(ENTERPRISE, target)
    return CobolTools(Workspace(target, ProjectConfig()))


class TestLintArgumentCase:
    def test_severity_is_case_insensitive(self, tools: CobolTools) -> None:
        upper = tools.lint("NESTED.cbl", min_severity="WARNING")["answer"]
        lower = tools.lint("NESTED.cbl", min_severity="warning")["answer"]
        assert upper["min_severity"] == "warning"
        assert upper["summary"] == lower["summary"]

    def test_rule_ids_are_case_insensitive(self, tools: CobolTools) -> None:
        answer = tools.lint("NESTED.cbl", rules=["DEAD-CODE"])["answer"]
        assert answer["rules_run"] == ["dead-code"]

    def test_an_unknown_rule_is_still_refused(self, tools: CobolTools) -> None:
        with pytest.raises(ToolError, match="unknown lint rule"):
            tools.lint("NESTED.cbl", rules=["NO-SUCH-RULE"])

    def test_an_empty_rule_list_runs_every_rule(self, tools: CobolTools) -> None:
        every = tools.lint("NESTED.cbl")["answer"]["rules_run"]
        assert tools.lint("NESTED.cbl", rules=[])["answer"]["rules_run"] == every


class TestProgramWithoutFile:
    """``program`` with no ``file`` limits the start to that PROGRAM-ID; it
    used to be dropped, so the answer silently covered every program."""

    def test_where_from_is_limited_to_the_program(self, tools: CobolTools) -> None:
        everywhere = tools.where_from("WS-EOF-FLAG")["answer"]
        assert everywhere["found"] is True
        here = tools.where_from("WS-EOF-FLAG", program="batchseq")["answer"]
        assert here["found"] is True
        # A program that does not declare the field: not found there.
        elsewhere = tools.where_from("WS-EOF-FLAG", program="SUBPROG")["answer"]
        assert elsewhere["found"] is False

    def test_impact_of_change_is_limited_to_the_program(
        self, tools: CobolTools
    ) -> None:
        answer = tools.impact_of_change("WS-EOF-FLAG", program="SUBPROG")["answer"]
        assert answer["found"] is False

    def test_an_unknown_program_is_an_error(self, tools: CobolTools) -> None:
        with pytest.raises(ToolError, match="did you mean BATCHSEQ"):
            tools.where_from("WS-EOF-FLAG", program="BATCHSEQ2")


class TestDeclaredInAnotherUnit:
    """NESTED.cbl's outermost unit is answered by default; WS-MSG and
    0000-POST are declared only in programs nested in it."""

    def test_explain_symbol_names_the_units(self, tools: CobolTools) -> None:
        answer = tools.explain_symbol("NESTED.cbl", "WS-MSG")["answer"]
        assert answer["found"] is False
        assert answer["declared_in_program_units"] == ["VALIDATE", "POSTER"]
        assert "program=" in answer["hint"]
        found = tools.explain_symbol("NESTED.cbl", "WS-MSG", program="POSTER")
        assert found["answer"]["found"] is True

    def test_record_layout_names_the_units(self, tools: CobolTools) -> None:
        answer = tools.record_layout("NESTED.cbl", "WS-MSG")["answer"]
        assert answer["found"] is False
        assert answer["declared_in_program_units"] == ["VALIDATE", "POSTER"]

    def test_callers_of_names_the_unit(self, tools: CobolTools) -> None:
        answer = tools.callers_of("NESTED.cbl", "0000-POST")["answer"]
        assert answer["found"] is False
        assert answer["declared_in_program_units"] == ["POSTER"]

    def test_a_name_declared_nowhere_gets_no_hint(self, tools: CobolTools) -> None:
        answer = tools.explain_symbol("NESTED.cbl", "NO-SUCH-NAME")["answer"]
        assert "declared_in_program_units" not in answer
        assert "hint" not in answer


class TestDefinedSymbols:
    def test_read_as_the_cli_reads_define(self) -> None:
        assert _defined_symbols(("DEBUG", "LEVEL=2", "EMPTY=")) == {
            "DEBUG": "TRUE",
            "LEVEL": "2",
            "EMPTY": "",
        }

    def test_none_when_nothing_is_defined(self) -> None:
        assert _defined_symbols(()) is None


UNUSED_AND_DEAD = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. EBCP.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-UNUSED   PIC X.
       01  WS-USED     PIC X.
       PROCEDURE DIVISION.
       MAIN-PARA.
           MOVE "A" TO WS-USED
           DISPLAY WS-USED
           STOP RUN.
       DEAD-PARA.
           DISPLAY "X".
"""


class TestColumnsInAnEbcdicSource:
    """A column is the analyzer's plus how far the file's text sits right of
    it, worked out from the file -- which was read as UTF-8, so an EBCDIC
    program (no line breaks, no fixed-format columns) lost the 7 sequence
    and indicator columns from every column it was cited at."""

    @pytest.mark.parametrize(
        "encode",
        [
            lambda text: text.encode("cp037").replace(b"\x25", b"\x15"),
            lambda text: text.encode("utf-8"),
        ],
        ids=["ebcdic", "utf-8"],
    )
    def test_lint_columns_are_on_disk_columns(self, tmp_path: Path, encode) -> None:
        (tmp_path / "EBCP.cbl").write_bytes(encode(UNUSED_AND_DEAD))
        tools = CobolTools(Workspace(tmp_path, ProjectConfig()))
        findings = tools.lint("EBCP.cbl")["answer"]["findings"]
        located = {f["symbol"]: f["location"] for f in findings}
        assert located["WS-UNUSED"] == {"file": "EBCP.cbl", "line": 5, "column": 8}
        assert located["DEAD-PARA"] == {"file": "EBCP.cbl", "line": 12, "column": 8}
