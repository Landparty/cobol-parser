"""The MCP tools, workspace and envelope -- none of which needs the SDK."""

from __future__ import annotations

import json
import os
import re
import shutil
from pathlib import Path

import pytest

from cobolparser.config.project import (
    LintDefaults,
    ProjectConfig,
    load_project_config,
)
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


class TestConfigCannotWidenTheGuard:
    """#544: a ``cobol.yml`` in the analysed tree, or above it, must not turn
    ``read_source`` into a read-anything tool."""

    @pytest.fixture
    def secret(self, tmp_path: Path) -> Path:
        path = tmp_path / "secret.txt"
        path.write_text("secret=hunter2\n")
        return path

    def test_copybook_path_slash_reads_nothing_outside(
        self, root: Path, secret: Path
    ) -> None:
        (root / "cobol.yml").write_text(
            "version: 1\nproject:\n  copybook_path:\n    - /\n"
        )
        ws = Workspace(root)
        tools = CobolTools(ws)
        targets = [str(secret), "../secret.txt"]
        if Path("/etc/passwd").is_file():
            targets.append("/etc/passwd")
        for target in targets:
            with pytest.raises(ToolError, match="outside the workspace"):
                tools.read_source(target, 1, 0, 0)
        assert ws.refused_copybook_dirs == ("/",)
        assert ws.config.copybook_path == ()
        # The root itself still answers.
        assert tools.read_source("BATCHSEQ.cbl", 1, 0, 0)["answer"]["lines"]

    def test_copybook_path_above_the_root_is_dropped(
        self, root: Path, secret: Path
    ) -> None:
        (root / "cobol.yml").write_text(
            'version: 1\nproject:\n  copybook_path: ["..", copybooks]\n'
        )
        ws = Workspace(root)
        with pytest.raises(ToolError, match="outside the workspace"):
            ws.resolve("../secret.txt")
        # A directory under the root is kept.
        assert ws.config.copybook_path == (str((root / "copybooks").resolve()),)
        refused = [Path(p).resolve() for p in ws.refused_copybook_dirs]
        assert refused == [root.parent.resolve()]

    def test_a_cobol_yml_in_a_parent_is_ignored(self, root: Path, secret: Path) -> None:
        (root.parent / "cobol.yml").write_text(
            'version: 1\nproject:\n  copybook_path: [".."]\n'
        )
        ws = Workspace(root)
        assert ws.config.source is None
        assert ws.config.copybook_path == ()
        with pytest.raises(ToolError, match="outside the workspace"):
            ws.resolve("../secret.txt")
        with pytest.raises(ToolError, match="outside the workspace"):
            ws.resolve("../../secret.txt")

    def test_allow_lets_an_outside_copybook_directory_in(
        self, root: Path, tmp_path: Path, secret: Path
    ) -> None:
        books = tmp_path / "books"
        shutil.move(str(root / "copybooks"), books)
        (root / "cobol.yml").write_text(
            f"version: 1\nproject:\n  copybook_path: [{books}]\n"
        )
        ws = Workspace(root, allow=[books])
        assert ws.refused_copybook_dirs == ()
        assert ws.resolve(str(books / "CUSTREC.cpy"))
        result = CobolTools(ws).explain_symbol("COPYREPL.cbl", "CUST-ID")
        assert result["answer"]["symbols"][0]["declared"] is True
        # --allow covers the copybook directory, not its parent.
        with pytest.raises(ToolError, match="outside the workspace"):
            ws.resolve(str(secret))

    def test_allow_must_be_a_directory(self, root: Path, tmp_path: Path) -> None:
        with pytest.raises(ToolError, match="--allow"):
            Workspace(root, allow=[tmp_path / "missing"])

    def test_a_dropped_directory_is_named_in_the_copy_caveat(
        self, root: Path, tmp_path: Path
    ) -> None:
        books = tmp_path / "books"
        shutil.move(str(root / "copybooks"), books)
        (root / "cobol.yml").write_text(
            f"version: 1\nproject:\n  copybook_path: [{books}]\n"
        )
        result = CobolTools(Workspace(root)).explain_symbol("COPYREPL.cbl", "CUST-ID")
        details = [
            c["detail"] for c in result["caveats"] if c["kind"] == "unresolved-copybook"
        ]
        assert any(
            "outside the workspace root" in d and str(books) in d for d in details
        )
        # A program with no COPY at all is not told about it.
        plain = CobolTools(Workspace(root)).lint("BATCHSEQ.cbl")
        assert not any(
            "outside the workspace root" in c["detail"] for c in plain["caveats"]
        )

    def test_a_config_file_outside_the_root_is_trusted(
        self, root: Path, tmp_path: Path
    ) -> None:
        books = tmp_path / "books"
        shutil.move(str(root / "copybooks"), books)
        operator = tmp_path / "operator.yml"
        operator.write_text(f"version: 1\nproject:\n  copybook_path: [{books}]\n")
        ws = Workspace(root, load_project_config(path=operator))
        assert ws.refused_copybook_dirs == ()
        assert ws.resolve(str(books / "CUSTREC.cpy"))

    def test_a_config_file_inside_the_root_is_not_trusted(
        self, root: Path, secret: Path
    ) -> None:
        inside = root / "custom.yml"
        inside.write_text("version: 1\nproject:\n  copybook_path: [/]\n")
        ws = Workspace(root, load_project_config(path=inside))
        assert ws.refused_copybook_dirs == ("/",)
        with pytest.raises(ToolError, match="outside the workspace"):
            ws.resolve(str(secret))


class TestWorkspaceFiles:
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


# -- program_brief ---------------------------------------------------------------

FLOWT = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. FLOWT.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  REC-A.
           05  FILLER            PIC X(2).
           05  A-CODE            PIC X(3).
           05  FILLER            PIC X(5).
       01  REC-B REDEFINES REC-A.
           05  B-ALL             PIC X(10).
       PROCEDURE DIVISION.
       0000-MAIN.
           PERFORM 1000-A THRU 3000-C.
           GO TO 9000-END.
       1000-A.
           DISPLAY 'A'.
       2000-B.
           DISPLAY 'B'.
       3000-C.
           DISPLAY 'C'.
       9000-END.
           STOP RUN.
       5000-DEAD.
           DISPLAY 'DEAD'.
"""


def line_of(root: Path, location: dict) -> str:
    """The text on disk at a cited location, to check a citation is real."""
    return (root / location["file"]).read_text().splitlines()[location["line"] - 1]


class TestProgramBrief:
    def test_files_and_their_use(self, root: Path) -> None:
        answer = tools_for(root).program_brief("VSAMKSDS.cbl")["answer"]
        files = {f["name"]: f for f in answer["files"]}
        master = files["CUST-MASTER"]
        assert master["organization"] == "INDEXED"
        assert master["access"] == "-RUD"
        assert master["record_key"] == "CM-CUST-ID"
        assert master["records"] == ["CUST-MASTER-REC"]
        assert files["AUDIT-LOG"]["access"] == "C---"
        assert answer["access_legend"]

    def test_interface_and_calls(self, root: Path) -> None:
        result = tools_for(root).program_brief("SUBPROG.cbl")
        answer = result["answer"]
        primary, entry = answer["interface"]
        assert primary["call_example"].startswith('CALL "SUBPROG" USING LK-ACCOUNT')
        days = primary["parameters"][1]
        assert (days["name"], days["by"], days["direction"]) == (
            "LK-DAYS",
            "VALUE",
            "input",
        )
        assert "LK-DAYS" in line_of(root, days["declared_at"])
        assert entry["kind"] == "entry-statement"
        calls = {c["program"]: c for c in answer["calls"]}
        dynamic = calls["WS-DYN-NAME"]
        assert dynamic["dynamic"] is True
        assert dynamic["candidates"] == ["RATECALC"]
        assert "CALL WS-DYN-NAME" in line_of(root, dynamic["sites"][0]["location"])
        assert calls["FACTORL"]["dynamic"] is False

    def test_sql_tables_and_cics(self, root: Path) -> None:
        tools = with_copybooks(root)
        db2 = tools.program_brief("DB2BATCH.cbl")["answer"]
        assert {"name": "BANK.ACCOUNT", "access": "--U-"} in db2["sql_tables"]
        cics = tools.program_brief("CICSONLN.cbl")["answer"]
        assert cics["cics_commands"]["SEND"] == 2
        linked = {c["program"]: c for c in cics["calls"]}
        assert linked["CUSTAUDT"]["via"] == "EXEC CICS LINK"
        assert "CUSTAUDT" in line_of(root, linked["CUSTAUDT"]["sites"][0]["location"])
        assert "exec_dli_commands" in tools.program_brief("EXECDLI.cbl")["answer"]

    def test_health_lint_and_unreachable(self, root: Path) -> None:
        (root / "FLOWT.cbl").write_text(FLOWT)
        answer = tools_for(root).program_brief("FLOWT.cbl")["answer"]
        assert answer["unreachable_procedures"] == ["5000-DEAD"]
        assert answer["size"] == {"sections": 0, "paragraphs": 6, "statements": 7}
        assert answer["health"]["grade"] in "ABCDF"
        assert answer["lint"]["scope"] == "file"
        assert len(answer["lint"]["worst"]) <= 5

    def test_nested_unit_counts_only_its_own_statements(self, root: Path) -> None:
        tools = tools_for(root)
        outer = tools.program_brief("OOCOBOL.cbl")
        assert outer["answer"]["unit_kind"] == "CLASS"
        assert outer["answer"]["size"]["statements"] == 0
        method = tools.program_brief("OOCOBOL.cbl", program="deposit")["answer"]
        assert method["size"]["statements"] > 0

    def test_a_failing_analyzer_costs_only_its_section(
        self, root: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from cobolparser.analysis.technical_debt import TechnicalDebtAnalyzer

        def boom(self: object, ast: object) -> None:
            raise RuntimeError("kaboom")

        monkeypatch.setattr(TechnicalDebtAnalyzer, "analyze", boom)
        result = tools_for(root).program_brief("VSAMKSDS.cbl")
        assert "health" not in result["answer"]
        assert result["answer"]["files"]
        assert any(
            c["kind"] == "analyzer-failed" and "kaboom" in c["detail"]
            for c in result["caveats"]
        )

    def test_every_sample_is_briefed_compactly(self, root: Path) -> None:
        tools = with_copybooks(root)
        for path in sorted(root.glob("*.cbl")):
            result = tools.program_brief(path.name)
            assert "analyzer-failed" not in kinds(result), path.name
            assert len(json.dumps(result)) < 16_000, path.name


# -- callers_of --------------------------------------------------------------------


class TestCallersOf:
    def test_perform_thru_is_one_caller_per_statement(self, root: Path) -> None:
        (root / "FLOWT.cbl").write_text(FLOWT)
        tools = tools_for(root)
        first = tools.callers_of("FLOWT.cbl", "1000-A")["answer"]["procedures"][0]
        assert first["callers"] == [
            {
                "from": "0000-MAIN",
                "type": "PERFORM",
                "location": {"file": "FLOWT.cbl", "line": 13},
                "thru": "3000-C",
            }
        ]
        middle = tools.callers_of("FLOWT.cbl", "2000-B")["answer"]["procedures"][0]
        assert middle["callers_by_type"] == {"PERFORM": 1, "FALL_THROUGH": 1}
        ranged = next(c for c in middle["callers"] if c["type"] == "PERFORM")
        assert ranged["via_range"] == ["1000-A", "3000-C"]

    def test_goto_and_unreachable(self, root: Path) -> None:
        (root / "FLOWT.cbl").write_text(FLOWT)
        tools = tools_for(root)
        end = tools.callers_of("FLOWT.cbl", "9000-END")["answer"]["procedures"][0]
        assert {"from": "0000-MAIN", "type": "GOTO"} in [
            {"from": c["from"], "type": c["type"]} for c in end["callers"]
        ]
        dead = tools.callers_of("FLOWT.cbl", "5000-dead")["answer"]["procedures"][0]
        assert dead["reachable"] is False
        assert dead["caller_count"] == 0
        assert "5000-DEAD" in line_of(root, dead["declared_at"])

    def test_sort_procedure_and_sql_whenever(self, root: Path) -> None:
        tools = with_copybooks(root)
        sort = tools.callers_of("BATCHSEQ.cbl", "3000-WRITE-REPORT")["answer"]
        assert "SORT_OUTPUT_PROCEDURE" in sort["procedures"][0]["callers_by_type"]
        error = tools.callers_of("DB2BATCH.cbl", "9900-SQL-ERROR")["answer"]
        by_type = error["procedures"][0]["callers_by_type"]
        assert by_type["SQL_WHENEVER"] >= 1
        for caller in error["procedures"][0]["callers"]:
            if caller["type"] == "SQL_WHENEVER":
                assert "EXEC SQL" in line_of(root, caller["location"])

    def test_a_called_program(self, root: Path) -> None:
        answer = tools_for(root).callers_of("MQBATCH.cbl", "MQPUT1")["answer"]
        assert answer["kind"] == "program"
        assert answer["scope"] == "workspace"
        (call,) = answer["callers"]
        assert call["program"] == "MQBATCH"
        assert call["from"] == "1100-REPLY"
        assert "MQPUT1" in line_of(root, call["location"])

    def test_not_found_and_own_program(self, root: Path) -> None:
        tools = tools_for(root)
        missing = tools.callers_of("BATCHSEQ.cbl", "3000-WRITE")["answer"]
        assert missing["found"] is False
        assert "3000-WRITE-REPORT" in missing["suggestions"]
        own = tools.callers_of("MQBATCH.cbl", "MQBATCH")["answer"]
        assert own["found"] is True
        assert own["declared_in"] == [{"file": "MQBATCH.cbl"}]
        assert own["callers"] == []
        with pytest.raises(ToolError):
            tools.callers_of("MQBATCH.cbl", " ")


# -- record_layout -----------------------------------------------------------------


class TestRecordLayout:
    def test_fields_in_source_order_cited_in_the_copybook(self, root: Path) -> None:
        result = with_copybooks(root).record_layout("COPYREPL.cbl", "WS-IN-CUSTOMER")
        (record,) = result["answer"]["records"]
        assert record["section"] == "WORKING-STORAGE"
        assert record["byte_length"] == 105
        names = [f["name"] for f in record["fields"]]
        # The layout emits a group after its members; the answer must not.
        assert names.index("IN-ADDRESS") < names.index("IN-STREET")
        street = record["fields"][names.index("IN-STREET")]
        assert (street["byte_offset"], street["byte_length"]) == (45, 30)
        assert street["declared_at"]["file"] == "copybooks/CUSTREC.cpy"
        assert ":PFX:-STREET" in line_of(root, street["declared_at"])
        active = record["fields"][names.index("IN-ACTIVE")]
        assert active["level"] == 88 and active["condition_values"] == ["A"]

    def test_a_group_inside_a_record(self, root: Path) -> None:
        answer = with_copybooks(root).record_layout("COPYREPL.cbl", "IN-ADDRESS")[
            "answer"
        ]
        (group,) = answer["records"]
        assert group["byte_offset"] == 45
        assert group["qualified_name"] == "IN-ADDRESS OF WS-IN-CUSTOMER"
        assert [f["name"] for f in group["fields"]] == [
            "IN-STREET",
            "IN-CITY",
            "IN-POSTCODE",
        ]

    def test_a_file_name_gives_its_records(self, root: Path) -> None:
        answer = tools_for(root).record_layout("VSAMKSDS.cbl", "CUST-MASTER")["answer"]
        assert answer["file"]["organization"] == "INDEXED"
        assert [r["name"] for r in answer["records"]] == ["CUST-MASTER-REC"]
        assert answer["records"][0]["section"] == "FILE"

    def test_filler_and_redefines(self, root: Path) -> None:
        (root / "FLOWT.cbl").write_text(FLOWT)
        tools = tools_for(root)
        rec_a = tools.record_layout("FLOWT.cbl", "REC-A")["answer"]["records"][0]
        fillers = [f for f in rec_a["fields"] if f["name"] == "FILLER"]
        assert [f["declared_at"]["line"] for f in fillers] == [6, 8]
        assert [f["byte_offset"] for f in fillers] == [0, 5]
        rec_b = tools.record_layout("FLOWT.cbl", "REC-B")["answer"]["records"][0]
        assert rec_b["redefines"] == "REC-A"

    def test_ambiguous_qualified_and_missing(self, root: Path) -> None:
        (root / "TWO.cbl").write_text(TWO_AMOUNTS)
        tools = tools_for(root)
        both = tools.record_layout("TWO.cbl", "AMT")
        assert len(both["answer"]["records"]) == 2
        assert "ambiguous-name" in kinds(both)
        one = tools.record_layout("TWO.cbl", "AMT IN OUT-REC")
        (amt,) = one["answer"]["records"]
        assert (amt["byte_offset"], amt["byte_length"]) == (3, 5)
        missing = tools.record_layout("TWO.cbl", "OUT-RECX")["answer"]
        assert missing["found"] is False
        assert "OUT-REC" in missing["suggestions"]

    def test_field_limit(self, root: Path) -> None:
        result = with_copybooks(root).record_layout(
            "COPYREPL.cbl", "WS-IN-CUSTOMER", limit=2
        )
        record = result["answer"]["records"][0]
        assert len(record["fields"]) == 2
        assert result["truncated"] == [
            {"field": "records[0].fields", "shown": 2, "total": record["field_count"]}
        ]
