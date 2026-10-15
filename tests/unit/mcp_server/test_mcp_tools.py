"""The MCP tools, workspace and envelope -- none of which needs the SDK."""

from __future__ import annotations

import json
import os
import re
import shutil
from pathlib import Path

import pytest

from cobolparser.config.project import LintDefaults, ProjectConfig
from cobolparser.mcp import CAVEAT_KINDS, CobolTools, ToolError, Workspace
from cobolparser.mcp.envelope import (
    DEFAULT_LIMIT,
    MAX_LIMIT,
    Caveat,
    Response,
    clamp_limit,
)
from cobolparser.mcp.tools import MAX_SOURCE_LINES

ENTERPRISE = Path(__file__).resolve().parents[2] / "samples" / "enterprise"

TWO_AMOUNTS = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TWOAMT.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  IN-REC.
           05  AMT              PIC 9(5).
       01  OUT-REC.
           05  FILLER           PIC X(3).
           05  AMT              PIC S9(7)V99 COMP-3.
       PROCEDURE DIVISION.
       MAIN-PARA.
           MOVE AMT OF IN-REC TO AMT OF OUT-REC.
           STOP RUN.
"""

BROKEN = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. BROKEN.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-A                 PIC 9.
       01  WS-UNUSED            PIC 9.
       PROCEDURE DIVISION.
       MAIN-PARA.
           MOVE 1 TO.
           DISPLAY WS-A.
           STOP RUN.
"""


@pytest.fixture
def root(tmp_path: Path) -> Path:
    """A private copy of the enterprise samples, safe to edit."""
    target = tmp_path / "src"
    shutil.copytree(ENTERPRISE, target)
    return target


def tools_for(root: Path, **config: object) -> CobolTools:
    return CobolTools(Workspace(root, ProjectConfig(**config)))  # type: ignore[arg-type]


def with_copybooks(root: Path) -> CobolTools:
    return tools_for(root, copybook_path=(str(root / "copybooks"),))


def kinds(result: dict) -> list[str]:
    return [c["kind"] for c in result["caveats"]]


# -- envelope ----------------------------------------------------------------


class TestEnvelope:
    def test_unknown_caveat_kind_is_refused(self) -> None:
        with pytest.raises(ValueError):
            Caveat("made-up", "x")

    def test_every_kind_is_constructible(self) -> None:
        for kind in CAVEAT_KINDS:
            assert Caveat(kind, "d").to_dict() == {"kind": kind, "detail": "d"}

    def test_clamp_limit(self) -> None:
        assert clamp_limit(None) == DEFAULT_LIMIT
        assert clamp_limit(0) == 1
        assert clamp_limit(10**6) == MAX_LIMIT

    def test_cap_records_the_true_total(self) -> None:
        response = Response()
        assert response.cap([1, 2, 3], 2, "xs") == [1, 2]
        assert response.cap([1], 2, "ys") == [1]
        assert response.build({})["truncated"] == [
            {"field": "xs", "shown": 2, "total": 3}
        ]

    def test_duplicate_caveats_collapse(self) -> None:
        response = Response()
        response.caveat("partial-parse", "same")
        response.caveat("partial-parse", "same")
        assert len(response.build({})["caveats"]) == 1


# -- workspace -----------------------------------------------------------------


class TestWorkspaceGuard:
    def test_parent_escape_is_refused(self, root: Path) -> None:
        with pytest.raises(ToolError, match="outside the workspace"):
            Workspace(root, ProjectConfig()).resolve("../outside.cbl")

    def test_absolute_path_outside_is_refused(self, root: Path) -> None:
        with pytest.raises(ToolError, match="outside the workspace"):
            Workspace(root, ProjectConfig()).resolve("/etc/hostname")

    def test_symlink_out_of_the_root_is_refused(
        self, root: Path, tmp_path: Path
    ) -> None:
        secret = tmp_path / "secret.txt"
        secret.write_text("x\n")
        (root / "link.cbl").symlink_to(secret)
        with pytest.raises(ToolError, match="outside the workspace"):
            Workspace(root, ProjectConfig()).resolve("link.cbl")

    def test_copybook_directory_outside_the_root_is_allowed(
        self, tmp_path: Path
    ) -> None:
        books = tmp_path / "books"
        books.mkdir()
        (books / "A.cpy").write_text("       01  A PIC X.\n")
        project = tmp_path / "project"
        project.mkdir()
        ws = Workspace(project, ProjectConfig(copybook_path=(str(books),)))
        assert ws.resolve(str(books / "A.cpy")) == (books / "A.cpy").resolve()
        assert ws.display(books / "A.cpy") == (books / "A.cpy").resolve().as_posix()

    def test_missing_and_empty(self, root: Path) -> None:
        ws = Workspace(root, ProjectConfig())
        with pytest.raises(ToolError, match="not found"):
            ws.resolve("NOPE.cbl")
        with pytest.raises(ToolError, match="no file"):
            ws.resolve("  ")

    def test_root_must_be_a_directory(self, root: Path) -> None:
        with pytest.raises(ToolError, match="not a directory"):
            Workspace(root / "BATCHSEQ.cbl", ProjectConfig())

    def test_config_is_found_from_the_root(self, root: Path) -> None:
        (root / "cobol.yml").write_text(
            "version: 1\nproject:\n  copybook_path: [copybooks]\n"
        )
        ws = Workspace(root)
        assert ws.config.copybook_path == (str((root / "copybooks").resolve()),)

    def test_edited_config_is_reread(self, root: Path) -> None:
        ws = Workspace(root)
        assert ws.config.copybook_path == ()
        first = ws.program("COPYREPL.cbl")
        (root / "cobol.yml").write_text(
            "version: 1\nproject:\n  copybook_path: [copybooks]\n"
        )
        tools = CobolTools(ws)
        result = tools.explain_symbol("COPYREPL.cbl", "CUST-ID")
        assert ws.program("COPYREPL.cbl") is not first
        assert result["answer"]["symbols"][0]["declared"] is True
        # ... and a copybook in the new directory is now inside the guard.
        assert ws.resolve(str(root / "copybooks" / "CUSTREC.cpy"))

    def test_broken_config_is_an_error_until_fixed(self, root: Path) -> None:
        config = root / "cobol.yml"
        config.write_text("version: 1\n")
        ws = Workspace(root)
        config.write_text("version: 1\nproject:\n  nonsense: [\n")
        with pytest.raises(ToolError, match="cobol.yml"):
            ws.program("BATCHSEQ.cbl")
        config.write_text("version: 1\nproject:\n  copybook_path: [copybooks]\n")
        assert ws.program("BATCHSEQ.cbl")
        assert ws.config.copybook_path

    def test_a_config_given_explicitly_stays_fixed(self, root: Path) -> None:
        ws = Workspace(root, ProjectConfig())
        (root / "cobol.yml").write_text(
            "version: 1\nproject:\n  copybook_path: [copybooks]\n"
        )
        assert ws.config.copybook_path == ()

    def test_non_utf8_is_an_error(self, root: Path) -> None:
        (root / "BIN.cbl").write_bytes(b"\xff\xfe\x00")
        with pytest.raises(ToolError, match="UTF-8"):
            tools_for(root).read_source("BIN.cbl")


class TestCache:
    def test_parse_once(self, root: Path) -> None:
        ws = Workspace(root, ProjectConfig())
        assert ws.program("BATCHSEQ.cbl") is ws.program("BATCHSEQ.cbl")

    def test_edit_invalidates(self, root: Path) -> None:
        ws = Workspace(root, ProjectConfig())
        first = ws.program("BATCHSEQ.cbl")
        path = root / "BATCHSEQ.cbl"
        path.write_text(path.read_text() + "\n")
        assert ws.program("BATCHSEQ.cbl") is not first

    def test_copybook_edit_invalidates(self, root: Path) -> None:
        ws = Workspace(root, ProjectConfig(copybook_path=(str(root / "copybooks"),)))
        first = ws.program("COPYREPL.cbl")
        book = root / "copybooks" / "DCLCUST.cpy"
        stat = book.stat()
        os.utime(book, ns=(stat.st_atime_ns, stat.st_mtime_ns + 10**9))
        assert ws.program("COPYREPL.cbl") is not first

    def test_a_copybook_added_later_is_picked_up(
        self, root: Path, tmp_path: Path
    ) -> None:
        # The member was missing, so the parse read no file of it: only its
        # directory's mtime can say it has arrived.
        books = tmp_path / "books"
        (books / "COPYLIB").mkdir(parents=True)
        tools = tools_for(root, copybook_path=(str(books),))
        before = tools.explain_symbol("COPYREPL.cbl", "CUST-ID")
        assert before["answer"]["symbols"][0]["declared"] is False
        for member in (root / "copybooks").iterdir():
            shutil.copy(member, books / member.name)
        after = tools.explain_symbol("COPYREPL.cbl", "CUST-ID")
        assert after["answer"]["symbols"][0]["declared"] is True
        assert "unresolved-copybook" not in kinds(after)

    def test_least_recently_used_is_evicted(self, root: Path) -> None:
        ws = Workspace(root, ProjectConfig(), cache_size=1)
        first = ws.program("BATCHSEQ.cbl")
        ws.program("SUBPROG.cbl")
        assert ws.program("BATCHSEQ.cbl") is not first


class TestParseCaveats:
    def test_no_copybook_path_names_every_unexpanded_member(self, root: Path) -> None:
        result = tools_for(root).lint("COPYREPL.cbl")
        details = [
            c["detail"] for c in result["caveats"] if c["kind"] == "unresolved-copybook"
        ]
        assert any("CUSTREC" in d for d in details)
        assert any("PROCLIB" in d for d in details)

    def test_one_missing_member_does_not_cost_the_others(
        self, root: Path, tmp_path: Path
    ) -> None:
        books = tmp_path / "books"
        books.mkdir()
        for member in (root / "copybooks").iterdir():
            if member.name != "CUSTREC.cpy":
                shutil.copy(member, books / member.name)
        tools = tools_for(root, copybook_path=(str(books),))
        result = tools.explain_symbol("COPYREPL.cbl", "WS-READ-COUNT")
        assert result["answer"]["symbols"][0]["declared"] is True
        assert result["answer"]["symbols"][0]["declared_at"]["file"].endswith(
            "WSCOUNTS.cpy"
        )
        details = [
            c["detail"] for c in result["caveats"] if c["kind"] == "unresolved-copybook"
        ]
        assert details and all("CUSTREC" in d for d in details)
        assert not any("expansion failed" in d for d in details)

    def test_failed_expansion_falls_back_with_a_caveat(
        self, root: Path, tmp_path: Path
    ) -> None:
        # A circular COPY still fails the expansion as a whole.
        books = tmp_path / "loop"
        books.mkdir()
        (books / "LOOPA.cpy").write_text("           COPY LOOPB.\n")
        (books / "LOOPB.cpy").write_text("           COPY LOOPA.\n")
        (root / "LOOP.cbl").write_text(
            TWO_AMOUNTS.replace(
                "       PROCEDURE DIVISION.",
                "           COPY LOOPA.\n" "       PROCEDURE DIVISION.",
            )
        )
        result = tools_for(root, copybook_path=(str(books),)).lint("LOOP.cbl")
        assert any(
            c["kind"] == "unresolved-copybook" and "expansion failed" in c["detail"]
            for c in result["caveats"]
        )
        assert result["program"]["file"] == "LOOP.cbl"

    def test_partial_parse(self, root: Path) -> None:
        (root / "BROKEN.cbl").write_text(BROKEN)
        result = tools_for(root).lint("BROKEN.cbl")
        assert "partial-parse" in kinds(result)
        assert any(f["rule"] == "parse" for f in result["answer"]["findings"])

    def test_defines_reach_the_parse(self, root: Path) -> None:
        (root / "COND.cbl").write_text(
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. COND.\n"
            "       DATA DIVISION.\n"
            "       WORKING-STORAGE SECTION.\n"
            "       >>IF DBG DEFINED\n"
            "       01  WS-DEBUG-ONLY        PIC X.\n"
            "       >>END-IF\n"
            "       PROCEDURE DIVISION.\n"
            "       MAIN-PARA.\n"
            "           STOP RUN.\n"
        )
        without = tools_for(root).explain_symbol("COND.cbl", "WS-DEBUG-ONLY")
        with_dbg = tools_for(root, define=("DBG=TRUE",)).explain_symbol(
            "COND.cbl", "WS-DEBUG-ONLY"
        )
        assert without["answer"]["found"] is False
        assert with_dbg["answer"]["found"] is True


# -- read_source ---------------------------------------------------------------


class TestReadSource:
    def test_window_around_a_line(self, root: Path) -> None:
        result = tools_for(root).read_source("BATCHSEQ.cbl", 89, before=1, after=1)
        answer = result["answer"]
        expected = (root / "BATCHSEQ.cbl").read_text().splitlines()[88]
        assert [row["line"] for row in answer["lines"]] == [88, 89, 90]
        assert answer["lines"][1]["text"] == expected
        assert answer["file"] == "BATCHSEQ.cbl"

    def test_window_clamps_at_the_edges(self, root: Path) -> None:
        answer = tools_for(root).read_source("BATCHSEQ.cbl", 1, before=50)["answer"]
        assert answer["start_line"] == 1

    def test_line_out_of_range(self, root: Path) -> None:
        with pytest.raises(ToolError, match="outside"):
            tools_for(root).read_source("BATCHSEQ.cbl", 100_000)
        with pytest.raises(ToolError, match="outside"):
            tools_for(root).read_source("BATCHSEQ.cbl", 0)

    @pytest.mark.parametrize("newline", ["\n", "\r\n", "\r"])
    def test_line_endings_as_an_editor_counts_them(
        self, root: Path, newline: str
    ) -> None:
        # A form feed inside a record is text, not a line break
        # (str.splitlines() would break there and shift every later line).
        rows = ["first", "sec\x0cond", "third"]
        (root / "ENDS.cbl").write_bytes(newline.join(rows).encode() + b"\n")
        answer = tools_for(root).read_source("ENDS.cbl", 2, before=1, after=1)
        assert answer["answer"]["total_lines"] == 3
        assert [r["text"] for r in answer["answer"]["lines"]] == rows

    def test_empty_file(self, root: Path) -> None:
        (root / "EMPTY.cbl").write_text("")
        answer = tools_for(root).read_source("EMPTY.cbl")["answer"]
        assert answer["total_lines"] == 0
        assert answer["lines"] == []

    def test_long_window_is_cut_and_says_so(self, root: Path) -> None:
        (root / "LONG.cbl").write_text("".join(f"line {n}\n" for n in range(1000)))
        result = tools_for(root).read_source("LONG.cbl", 500, before=400, after=400)
        assert len(result["answer"]["lines"]) == MAX_SOURCE_LINES
        assert result["truncated"] == [
            {"field": "lines", "shown": MAX_SOURCE_LINES, "total": 801}
        ]


# -- lint ------------------------------------------------------------------------


class TestLint:
    def test_findings_in_a_copybook_cite_the_copybook(self, root: Path) -> None:
        findings = with_copybooks(root).lint("COPYREPL.cbl", limit=500)["answer"][
            "findings"
        ]
        in_copybook = [
            f
            for f in findings
            if f["location"] and f["location"]["file"].startswith("copybooks/")
        ]
        assert in_copybook
        for finding in in_copybook:
            location = finding["location"]
            text = (root / location["file"]).read_text().splitlines()
            line = text[location["line"] - 1]
            # The column is the one an editor shows: the declaration (its
            # level number) starts there, and names the symbol -- as the
            # copybook spells it, before COPY ... REPLACING ==:PFX:==.
            assert line[: location["column"] - 1].strip() == ""
            assert re.sub("^(IN|OUT)-", ":PFX:-", finding["symbol"]) in line

    def test_unused_copybook_fields_are_info_as_in_the_cli(self, root: Path) -> None:
        findings = with_copybooks(root).lint("COPYREPL.cbl", limit=500)["answer"][
            "findings"
        ]
        unused = {f["symbol"]: f for f in findings if f["rule"] == "unused-variables"}
        # SQLCA is a copybook: a program that never reads SQLERRM is normal.
        assert unused["SQLERRM"]["severity"] == "info"
        assert unused["SQLERRM"]["location"]["file"] == "copybooks/SQLCA.cpy"
        # WS-DONE is the program's own declaration.
        assert unused["WS-DONE"]["severity"] == "warning"
        assert unused["WS-DONE"]["location"]["file"] == "COPYREPL.cbl"

    def test_worst_first_and_counted(self, root: Path) -> None:
        (root / "BROKEN.cbl").write_text(BROKEN)
        result = tools_for(root).lint("BROKEN.cbl", limit=1)
        assert result["answer"]["findings"][0]["severity"] == "error"
        assert result["truncated"][0]["field"] == "findings"
        summary = result["answer"]["summary"]
        assert (
            summary["total"] == summary["error"] + summary["warning"] + summary["info"]
        )

    def test_min_severity_and_rules(self, root: Path) -> None:
        tools = tools_for(root)
        none = tools.lint("BATCHSEQ.cbl", min_severity="error")["answer"]
        assert none["summary"]["total"] == 0
        only = tools.lint("BATCHSEQ.cbl", rules=["dead-code"])["answer"]
        assert only["rules_run"] == ["dead-code"]

    def test_config_lint_defaults(self, root: Path) -> None:
        tools = tools_for(root, lint=LintDefaults(rules=("complexity",)))
        assert tools.lint("BATCHSEQ.cbl")["answer"]["rules_run"] == ["complexity"]

    def test_bad_arguments(self, root: Path) -> None:
        tools = tools_for(root)
        with pytest.raises(ToolError, match="severity"):
            tools.lint("BATCHSEQ.cbl", min_severity="fatal")
        with pytest.raises(ToolError, match="unknown lint rule"):
            tools.lint("BATCHSEQ.cbl", rules=["no-such-rule"])

    def test_nothing_reaches_stdout(
        self, root: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        with_copybooks(root).lint("COPYREPL.cbl")
        tools_for(root).explain_symbol("NESTED.cbl", "WS-RUN-ID")
        assert capsys.readouterr().out == ""

    def test_result_is_json(self, root: Path) -> None:
        json.dumps(with_copybooks(root).lint("COPYREPL.cbl"))


# -- explain_symbol --------------------------------------------------------------


class TestExplainSymbol:
    def test_declared_in_a_copybook_with_layout(self, root: Path) -> None:
        result = with_copybooks(root).explain_symbol("COPYREPL.cbl", "CUST-ID")
        symbol = result["answer"]["symbols"][0]
        assert symbol["declared_at"]["file"] == "copybooks/DCLCUST.cpy"
        line = (
            (root / "copybooks" / "DCLCUST.cpy")
            .read_text()
            .splitlines()[symbol["declared_at"]["line"] - 1]
        )
        assert "CUST-ID" in line
        # Offset 0 is information, not an absent value.
        assert symbol["layout"]["byte_offset"] == 0
        assert symbol["layout"]["byte_length"] == 8
        # A reference is cited at its statement's first line (an EXEC SQL
        # block starts above its host variables); a MOVE is one line.
        move = next(r for r in symbol["references"] if r["role"] == "write")
        source = (root / move["location"]["file"]).read_text().splitlines()
        assert "CUST-ID" in source[move["location"]["line"] - 1]
        assert result["caveats"] == []

    def test_condition_name_values(self, root: Path) -> None:
        symbol = tools_for(root).explain_symbol("BATCHSEQ.cbl", "tran-debit")["answer"][
            "symbols"
        ][0]
        assert symbol["kind"] == "condition-name"
        assert symbol["layout"]["condition_values"] == ["D"]
        assert symbol["references_by_role"] == {"condition": 1}

    def test_not_found_suggests(self, root: Path) -> None:
        answer = tools_for(root).explain_symbol("BATCHSEQ.cbl", "TRAN-DEBT")["answer"]
        assert answer["found"] is False
        assert answer["special_register"] is False
        assert "TRAN-DEBIT" in answer["suggestions"]

    def test_special_register_is_named_as_one(self, root: Path) -> None:
        answer = tools_for(root).explain_symbol("BATCHSEQ.cbl", "return-code")["answer"]
        assert answer["found"] is False
        assert answer["special_register"] is True
        assert answer["suggestions"] == []
        assert "special register" in answer["note"]

    def test_undeclared_without_copybooks(self, root: Path) -> None:
        result = tools_for(root).explain_symbol("COPYREPL.cbl", "CUST-ID")
        assert result["answer"]["symbols"][0]["declared"] is False
        assert "unresolved-copybook" in kinds(result)

    def test_ambiguous_and_qualified(self, root: Path) -> None:
        (root / "TWOAMT.cbl").write_text(TWO_AMOUNTS)
        tools = tools_for(root)
        both = tools.explain_symbol("TWOAMT.cbl", "AMT")
        assert len(both["answer"]["symbols"]) == 2
        assert "ambiguous-name" in kinds(both)
        one = tools.explain_symbol("TWOAMT.cbl", "AMT IN OUT-REC")
        (symbol,) = one["answer"]["symbols"]
        assert symbol["layout"]["byte_offset"] == 3
        assert symbol["layout"]["byte_length"] == 5
        assert "ambiguous-name" not in kinds(one)

    def test_program_units(self, root: Path) -> None:
        tools = tools_for(root)
        outer = tools.explain_symbol("NESTED.cbl", "WS-RUN-ID")
        assert "program-unit-selected" in kinds(outer)
        assert outer["program"]["program_id"] == "NESTED"
        assert outer["answer"]["found"] is True
        assert "POSTER" in outer["program"]["program_units"]
        with pytest.raises(ToolError, match="no program unit"):
            tools.explain_symbol("NESTED.cbl", "WS-RUN-ID", program="NOPE")
        inner = tools.explain_symbol("NESTED.cbl", "WS-MSG", program="POSTER")
        assert inner["program"]["program_id"] == "POSTER"
        assert "program-unit-selected" not in kinds(inner)
        assert inner["answer"]["found"] is True

    def test_reference_limit(self, root: Path) -> None:
        result = tools_for(root).explain_symbol(
            "BATCHSEQ.cbl", "WS-READ-COUNT", limit=1
        )
        symbol = result["answer"]["symbols"][0]
        assert len(symbol["references"]) == 1
        assert result["truncated"][0]["total"] == symbol["reference_count"]

    def test_empty_name(self, root: Path) -> None:
        with pytest.raises(ToolError):
            tools_for(root).explain_symbol("BATCHSEQ.cbl", "   ")
