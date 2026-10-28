"""read_procedure and find_statements (``cobolparser.mcp.navigation``)."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from cobolparser.config.project import ProjectConfig
from cobolparser.mcp import CobolTools, ToolError, Workspace
from cobolparser.mcp.navigation import statement_verb

SAMPLES = Path(__file__).resolve().parents[2] / "samples"
ENTERPRISE = SAMPLES / "enterprise"


def _tools(root: Path = ENTERPRISE) -> CobolTools:
    return CobolTools(
        Workspace(root, ProjectConfig(copybook_path=(str(root / "copybooks"),)))
    )


def _disk_line(root: Path, file: str, line: int) -> str:
    return (root / file).read_text(errors="replace").splitlines()[line - 1]


class TestReadProcedure:
    def test_a_paragraph_is_whole_and_cited(self) -> None:
        answer = _tools().read_procedure("BATCHSEQ.cbl", "1000-INIT")["answer"]
        assert answer["found"] is True and answer["kind"] == "paragraph"
        (segment,) = answer["segments"]
        assert segment["lines"][0].strip() == "1000-INIT."
        for offset, text in enumerate(segment["lines"]):
            assert (
                _disk_line(ENTERPRISE, segment["file"], segment["start_line"] + offset)
                == text
            )
        # Ends before the next paragraph header.
        next_line = _disk_line(
            ENTERPRISE, segment["file"], segment["start_line"] + len(segment["lines"])
        )
        assert next_line[7:11].strip()

    def test_the_last_paragraph_runs_to_its_end(self) -> None:
        tools = _tools()
        brief = tools.program_brief("BATCHSEQ.cbl")["answer"]
        flow_names = [
            line.strip().rstrip(".")
            for line in (ENTERPRISE / "BATCHSEQ.cbl").read_text().splitlines()
            if len(line) > 8
            and line[7:11].strip()
            and line.rstrip().endswith(".")
            and "DIVISION" not in line
            and "SECTION" not in line
        ]
        last = flow_names[-1]
        answer = tools.read_procedure("BATCHSEQ.cbl", last)["answer"]
        assert answer["found"], brief
        text = "\n".join(answer["segments"][-1]["lines"])
        assert text.rstrip().endswith(".")

    def test_copybook_lines_are_a_segment_in_the_member(self, tmp_path: Path) -> None:
        (tmp_path / "copybooks").mkdir()
        (tmp_path / "copybooks" / "LOGIT.cpy").write_text(
            "           DISPLAY 'ONE'\n           DISPLAY 'TWO'.\n"
        )
        (tmp_path / "MAIN.cbl").write_text(
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. MAIN.\n"
            "       PROCEDURE DIVISION.\n"
            "       0000-MAIN.\n"
            "           COPY LOGIT.\n"
            "           GOBACK.\n"
            "       9000-OTHER.\n"
            "           STOP RUN.\n"
        )
        answer = _tools(tmp_path).read_procedure("MAIN.cbl", "0000-MAIN")["answer"]
        assert [
            (s["file"], s["start_line"], len(s["lines"])) for s in answer["segments"]
        ] == [
            ("MAIN.cbl", 4, 1),
            ("copybooks/LOGIT.cpy", 1, 2),
            ("MAIN.cbl", 6, 1),
        ]

    def test_not_found_suggests(self) -> None:
        answer = _tools().read_procedure("BATCHSEQ.cbl", "1000-INTI")["answer"]
        assert answer["found"] is False
        assert "1000-INIT" in answer["suggestions"]

    def test_a_section_lists_its_paragraphs(self) -> None:
        answer = _tools().read_procedure("DECLARE.cbl", "MAIN-LOGIC")["answer"]
        assert answer["kind"] == "section"
        assert "0000-MAIN" in answer["paragraphs"]


class TestFindStatements:
    def test_verb_over_the_root(self) -> None:
        answer = _tools().find_statements(verb="write")["answer"]
        assert answer["scope"] == "workspace"
        assert answer["match_count"] == sum(answer["by_verb"].values())
        for row in answer["statements"]:
            assert row["verb"] == "WRITE"
            text = _disk_line(
                ENTERPRISE, row["location"]["file"], row["location"]["line"]
            )
            assert "WRITE" in text.upper()

    def test_verb_prefix_matches_exec_commands(self) -> None:
        answer = _tools().find_statements(verb="EXEC CICS")["answer"]
        assert answer["match_count"] > 0
        assert all(r["verb"].startswith("EXEC CICS ") for r in answer["statements"])
        assert _tools().find_statements(verb="WRIT")["answer"]["match_count"] == 0

    def test_operand_with_role_in_one_file(self) -> None:
        tools = _tools()
        anywhere = tools.find_statements(operand="WS-EOF", file="BATCHSEQ.cbl")
        answer = anywhere["answer"]
        assert answer["scope"] == "file"
        roles = {r for row in answer["statements"] for r in row["operand_roles"]}
        if "write" in roles:
            writes = tools.find_statements(
                operand="WS-EOF", role="write", file="BATCHSEQ.cbl"
            )["answer"]
            assert 0 < writes["match_count"] <= answer["match_count"]
            assert all("write" in r["operand_roles"] for r in writes["statements"])

    def test_literal_and_paragraph(self) -> None:
        answer = _tools().find_statements(paragraph="1000-INIT", file="BATCHSEQ.cbl")[
            "answer"
        ]
        assert answer["match_count"] > 0
        assert {r["paragraph"] for r in answer["statements"]} == {"1000-INIT"}
        literal = _tools().find_statements(literal="open", file="BATCHSEQ.cbl")
        assert all("OPEN" in r["text"].upper() for r in literal["answer"]["statements"])
        assert literal["caveats"][0]["kind"] == "incomplete-analysis"

    def test_needs_a_filter_and_suggests(self) -> None:
        with pytest.raises(ToolError):
            _tools().find_statements()
        answer = _tools().find_statements(verb="WRTE", file="BATCHSEQ.cbl")["answer"]
        assert "WRITE" in answer["suggestions"]

    def test_copybook_statements_are_found_in_the_member(self, tmp_path: Path) -> None:
        root = tmp_path / "ws"
        (root / "copybooks").mkdir(parents=True)
        (root / "copybooks" / "LOGIT.cpy").write_text(
            "           DISPLAY 'FROM-THE-COPYBOOK'.\n"
        )
        (root / "MAIN.cbl").write_text(
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. MAIN.\n"
            "       PROCEDURE DIVISION.\n"
            "       0000-MAIN.\n"
            "      * DISPLAY 'IN-A-COMMENT'\n"
            "           COPY LOGIT.\n"
            "           GOBACK.\n"
        )
        answer = _tools(root).find_statements(verb="DISPLAY")["answer"]
        assert [r["location"] for r in answer["statements"]] == [
            {"file": "copybooks/LOGIT.cpy", "line": 1}
        ]
        assert answer["statements"][0]["paragraph"] == "0000-MAIN"

    def test_index_is_rebuilt_when_a_program_changes(self, tmp_path: Path) -> None:
        root = tmp_path / "ent"
        shutil.copytree(ENTERPRISE, root)
        tools = _tools(root)
        before = tools.find_statements(verb="GOBACK")["answer"]["match_count"]
        (root / "EXTRA.cbl").write_text(
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. EXTRA.\n"
            "       PROCEDURE DIVISION.\n"
            "           GOBACK.\n"
        )
        after = tools.find_statements(verb="GOBACK")["answer"]["match_count"]
        assert after == before + 1


def test_statement_verb_names_exec_commands() -> None:
    class Fake:
        _cics_command = "link"
        statement_type = "EXEC CICS"

    assert statement_verb(Fake()) == "EXEC CICS LINK"
