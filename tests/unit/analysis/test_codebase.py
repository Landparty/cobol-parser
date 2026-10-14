"""Tests for whole-codebase call-graph and copybook-dependency analysis."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from cobolparser.analysis.codebase import (
    CallEdge,
    CodebaseGraph,
    CodebaseGraphBuilder,
    CopybookImpactAnalyzer,
    CopyEdge,
    ImpactReport,
    ProgramNode,
    _member_fields,
    _normalize_member,
    _normalize_program_name,
    _program_node_id,
    _sanitize_id,
)
from cobolparser.models.ast_base import SourceLocation
from cobolparser.models.statements.call import CallStatement

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

MAIN_PROGRAM = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. MAINPGM.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       COPY LEVEL1.
       COPY CUSTOMER.
       PROCEDURE DIVISION.
       MAIN-LOGIC.
           CALL "SUBPGM".
           CALL "REPORTER".
           STOP RUN.
"""

SUB_PROGRAM = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SUBPGM.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       COPY LEVEL2.
       PROCEDURE DIVISION.
       SUB-LOGIC.
           CALL "MAINPGM".
           GOBACK.
"""

DYNAMIC_PROGRAM = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. DYNPGM.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       COPY CIRCULARA.
       01 WS-FROM-INPUT   PIC X(8).
       01 WS-TARGET       PIC X(8) VALUE "SUBPGM".
       01 WS-BLIND        PIC X(8).
       PROCEDURE DIVISION.
       DYN-LOGIC.
           MOVE WS-FROM-INPUT TO WS-TARGET.
           MOVE WS-FROM-INPUT TO WS-BLIND.
           CALL WS-TARGET.
           CALL WS-BLIND.
           STOP RUN.
"""

BROKEN_PROGRAM = "this is not COBOL at all {{{\nnor is this\n"

SELF_CALLING_PROGRAM = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. LOOPER.
       PROCEDURE DIVISION.
       LOOP-LOGIC.
           CALL "LOOPER".
           GOBACK.
"""

COPYBOOK_MEMBERS = (
    "LEVEL1.cpy",
    "LEVEL2.cpy",
    "LEVEL3.cpy",
    "CUSTOMER.cpy",
    "CIRCULARA.cpy",
    "CIRCULARB.cpy",
)


@pytest.fixture
def copybooks(tmp_path, samples_dir) -> Path:
    """A copybook directory holding the shared sample members.

    Uses the repository's own fixtures: LEVEL1 -> LEVEL2 -> LEVEL3 is a real
    nested chain and CIRCULARA <-> CIRCULARB a real circular pair.
    """
    target = tmp_path / "copybooks"
    target.mkdir()
    for name in COPYBOOK_MEMBERS:
        shutil.copy(samples_dir / "copybooks" / name, target / name)
    return target


@pytest.fixture
def source_tree(tmp_path) -> Path:
    """A small program tree: two mutually calling programs plus a dynamic one."""
    src = tmp_path / "src"
    src.mkdir()
    (src / "MAIN.cbl").write_text(MAIN_PROGRAM)
    (src / "SUB.cob").write_text(SUB_PROGRAM)
    (src / "DYN.cbl").write_text(DYNAMIC_PROGRAM)
    return src


@pytest.fixture
def graph(source_tree, copybooks) -> CodebaseGraph:
    builder = CodebaseGraphBuilder(copybook_paths=[str(copybooks)])
    return builder.build_from_directory(str(source_tree))


def _edge(edges, caller, callee):
    return [e for e in edges if e.caller == caller and e.callee == callee]


# ---------------------------------------------------------------------------
# Name normalization
# ---------------------------------------------------------------------------


class TestNameNormalization:
    def test_program_name_unquoted_and_uppercased(self):
        assert _normalize_program_name('"subpgm"') == "SUBPGM"
        assert _normalize_program_name("'sub-pgm' ") == "SUB-PGM"
        assert _normalize_program_name("  MAINPGM  ") == "MAINPGM"

    def test_member_accepts_bare_name_file_name_and_path(self):
        assert _normalize_member("CUSTOMER") == "CUSTOMER"
        assert _normalize_member("customer.cpy") == "CUSTOMER"
        assert _normalize_member("./copybooks/CUSTOMER.CPY") == "CUSTOMER"
        assert _normalize_member("copybooks\\CUSTOMER.cbl") == "CUSTOMER"

    def test_member_keeps_unknown_extension(self):
        assert _normalize_member("CUSTOMER.dat") == "CUSTOMER.DAT"

    def test_blank_member_is_empty(self):
        assert _normalize_member("   ") == ""


# ---------------------------------------------------------------------------
# Call graph
# ---------------------------------------------------------------------------


class TestCallEdges:
    def test_programs_are_discovered(self, graph):
        assert graph.program_ids == ["DYNPGM", "MAINPGM", "SUBPGM"]
        assert all(not p.parse_failed for p in graph.programs)

    def test_static_call_edges_in_both_directions(self, graph):
        assert _edge(graph.call_edges, "MAINPGM", "SUBPGM")
        assert _edge(graph.call_edges, "SUBPGM", "MAINPGM")
        assert _edge(graph.call_edges, "MAINPGM", "REPORTER")

    def test_callers_and_callees(self, graph):
        assert graph.callers_of("SUBPGM") == ["DYNPGM", "MAINPGM"]
        assert graph.callees_of("MAINPGM") == ["REPORTER", "SUBPGM"]
        assert graph.callers_of("MAINPGM") == ["SUBPGM"]

    def test_callers_of_is_case_insensitive(self, graph):
        assert graph.callers_of("subpgm") == graph.callers_of("SUBPGM")

    def test_unknown_program_has_no_edges(self, graph):
        assert graph.callers_of("NOSUCH") == []
        assert graph.callees_of("NOSUCH") == []

    def test_program_node_calls_are_sorted_and_deduplicated(self, graph):
        main = next(p for p in graph.programs if p.program_id == "MAINPGM")
        assert main.calls == ["REPORTER", "SUBPGM"]
        assert main.calls == sorted(set(main.calls))

    def test_external_callee_has_no_program_node(self, graph):
        assert "REPORTER" not in graph.program_ids


class TestDynamicCalls:
    def test_partially_resolved_dynamic_call_keeps_its_edge(self, graph):
        edges = _edge(graph.call_edges, "DYNPGM", "SUBPGM")
        assert len(edges) == 1
        assert edges[0].is_dynamic is True
        # A MOVE from an untracked field means the value set is not exhaustive.
        assert edges[0].resolved is False

    def test_incomplete_value_set_is_reported(self, graph):
        assert any(
            "WS-TARGET" in note and "not exhaustive" in note
            for note in graph.unresolved
        )

    def test_unresolvable_dynamic_call_is_reported_not_dropped(self, graph):
        assert any(
            "WS-BLIND" in note and "no possible target could be resolved" in note
            for note in graph.unresolved
        )
        # No invented edge: a data name is not a program name.
        assert not _edge(graph.call_edges, "DYNPGM", "WS-BLIND")

    def test_fully_resolved_dynamic_call_is_marked_resolved(self, tmp_path):
        program = tmp_path / "D.cbl"
        program.write_text(
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. RESOLVED.\n"
            "       DATA DIVISION.\n"
            "       WORKING-STORAGE SECTION.\n"
            '       01 WS-TARGET PIC X(8) VALUE "CALLEE".\n'
            "       PROCEDURE DIVISION.\n"
            "       MAIN-LOGIC.\n"
            "           CALL WS-TARGET.\n"
            "           STOP RUN.\n"
        )
        graph = CodebaseGraphBuilder().build([str(program)])
        edges = _edge(graph.call_edges, "RESOLVED", "CALLEE")
        assert [(e.is_dynamic, e.resolved) for e in edges] == [(True, True)]

    def test_figurative_candidates_make_no_call_edge(self, tmp_path):
        # SPACES / LOW-VALUES / HIGH-VALUES / ZERO are the "no program"
        # sentinel, not callees: no '\x00' / '0' / '\xff' node in the graph.
        program = tmp_path / "D.cbl"
        program.write_text(
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. DISPATCH.\n"
            "       DATA DIVISION.\n"
            "       WORKING-STORAGE SECTION.\n"
            "       01 WS-PGM PIC X(8) VALUE SPACES.\n"
            "       PROCEDURE DIVISION.\n"
            "       MAIN-LOGIC.\n"
            "           MOVE 'SUBA' TO WS-PGM.\n"
            "           MOVE LOW-VALUES TO WS-PGM.\n"
            "           MOVE HIGH-VALUES TO WS-PGM.\n"
            "           MOVE ZERO TO WS-PGM.\n"
            "           CALL WS-PGM.\n"
            "           STOP RUN.\n"
        )
        graph = CodebaseGraphBuilder().build([str(program)])
        assert [e.callee for e in graph.call_edges] == ["SUBA"]

    def test_only_figurative_candidates_are_reported_unresolved(self, tmp_path):
        program = tmp_path / "D.cbl"
        program.write_text(
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. DISPATCH.\n"
            "       DATA DIVISION.\n"
            "       WORKING-STORAGE SECTION.\n"
            "       01 WS-PGM PIC X(8) VALUE SPACES.\n"
            "       PROCEDURE DIVISION.\n"
            "       MAIN-LOGIC.\n"
            "           CALL WS-PGM.\n"
            "           STOP RUN.\n"
        )
        graph = CodebaseGraphBuilder().build([str(program)])
        assert graph.call_edges == []
        assert any("no possible target" in note for note in graph.unresolved)


class TestCycles:
    def test_mutual_recursion_is_reported(self, graph):
        assert ["MAINPGM", "SUBPGM"] in graph.cycles()

    def test_self_call_is_a_cycle(self, tmp_path):
        program = tmp_path / "LOOPER.cbl"
        program.write_text(SELF_CALLING_PROGRAM)
        graph = CodebaseGraphBuilder().build([str(program)])
        assert graph.cycles() == [["LOOPER"]]

    def test_acyclic_graph_has_no_cycles(self, tmp_path):
        (tmp_path / "A.cbl").write_text(
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. AAA.\n"
            "       PROCEDURE DIVISION.\n"
            "       P.\n"
            '           CALL "BBB".\n'
            "           GOBACK.\n"
        )
        graph = CodebaseGraphBuilder().build([str(tmp_path / "A.cbl")])
        assert graph.cycles() == []

    def test_cycle_count_is_in_the_dict(self, graph):
        assert graph.to_dict()["summary"]["cycle_count"] == len(graph.cycles())


# ---------------------------------------------------------------------------
# COPY graph
# ---------------------------------------------------------------------------


class TestCopyEdges:
    def test_direct_copy_edges(self, graph):
        direct = {(e.program, e.member) for e in graph.copy_edges if not e.nested}
        assert ("MAINPGM", "LEVEL1") in direct
        assert ("MAINPGM", "CUSTOMER") in direct
        assert ("SUBPGM", "LEVEL2") in direct

    def test_nested_copy_edges_are_member_to_member(self, graph):
        nested = {(e.program, e.member) for e in graph.copy_edges if e.nested}
        assert ("LEVEL1", "LEVEL2") in nested
        assert ("LEVEL2", "LEVEL3") in nested

    def test_resolved_members_carry_their_file_path(self, graph, copybooks):
        edge = next(e for e in graph.copy_edges if e.member == "LEVEL3")
        assert edge.path == str(copybooks / "LEVEL3.cpy")

    def test_program_node_copies_are_direct_only(self, graph):
        main = next(p for p in graph.programs if p.program_id == "MAINPGM")
        assert main.copies == ["CUSTOMER", "LEVEL1"]

    def test_circular_copy_chain_is_reported_not_looped_on(self, graph):
        assert any(
            note.startswith("circular COPY chain:") and "CIRCULARA" in note
            for note in graph.unresolved
        )

    def test_missing_copybook_path_is_stated_once(self, source_tree):
        graph = CodebaseGraphBuilder().build_from_directory(str(source_tree))
        gaps = [n for n in graph.unresolved if "no copybook search path" in n]
        assert len(gaps) == 1
        # The member names are still known -- only their files are not.
        assert any(e.member == "LEVEL1" for e in graph.copy_edges)
        assert all(e.path is None for e in graph.copy_edges)
        assert not any(e.nested for e in graph.copy_edges)

    def test_unresolvable_member_is_reported(self, tmp_path, copybooks):
        program = tmp_path / "P.cbl"
        program.write_text(
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. GHOSTLY.\n"
            "       DATA DIVISION.\n"
            "       WORKING-STORAGE SECTION.\n"
            "       COPY NOSUCHBOOK.\n"
            "       PROCEDURE DIVISION.\n"
            "       P.\n"
            "           STOP RUN.\n"
        )
        graph = CodebaseGraphBuilder(copybook_paths=[str(copybooks)]).build(
            [str(program)]
        )
        edge = next(e for e in graph.copy_edges if e.member == "NOSUCHBOOK")
        assert edge.path is None
        assert any("NOSUCHBOOK" in note for note in graph.unresolved)

    def test_sample_copybook_program_parses_into_edges(self, samples_dir, copybooks):
        program = samples_dir / "copybook_programs" / "basic_copy.cbl"
        graph = CodebaseGraphBuilder(copybook_paths=[str(copybooks)]).build(
            [str(program)]
        )
        node = next(p for p in graph.programs if p.program_id == "TESTPROG")
        assert "CUSTOMER" in node.copies
        assert "EMPLOYEE" in node.copies


SQL_PROGRAM = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SQLPGM.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
           EXEC SQL INCLUDE SQLCA END-EXEC.
           EXEC SQL
               INCLUDE DCLCUST
           END-EXEC.
       PROCEDURE DIVISION.
       P.
           STOP RUN.
"""

SQLCA_MEMBER = """\
       01  SQLCA.
           05  SQLCAID     PIC X(8).
           05  SQLCODE     PIC S9(9) COMP.
"""

DCLCUST_MEMBER = """\
       01  DCLCUST.
           05  CUST-ID     PIC X(10).
           EXEC SQL INCLUDE DCLADDR END-EXEC.
"""

DCLADDR_MEMBER = """\
           05  CUST-ADDR   PIC X(40).
"""


class TestSqlIncludeEdges:
    """``EXEC SQL INCLUDE`` pulls a member in exactly as COPY does (#295)."""

    @pytest.fixture
    def sql_graph(self, tmp_path) -> CodebaseGraph:
        books = tmp_path / "sqlbooks"
        books.mkdir()
        (books / "SQLCA.cpy").write_text(SQLCA_MEMBER)
        (books / "DCLCUST.cpy").write_text(DCLCUST_MEMBER)
        (books / "DCLADDR.cpy").write_text(DCLADDR_MEMBER)
        program = tmp_path / "SQLPGM.cbl"
        program.write_text(SQL_PROGRAM)
        return CodebaseGraphBuilder(copybook_paths=[str(books)]).build([str(program)])

    def test_include_members_are_direct_copy_edges(self, sql_graph, tmp_path):
        direct = {
            (e.program, e.member): e for e in sql_graph.copy_edges if not e.nested
        }
        assert set(direct) == {("SQLPGM", "SQLCA"), ("SQLPGM", "DCLCUST")}
        assert direct[("SQLPGM", "SQLCA")].path == str(
            tmp_path / "sqlbooks" / "SQLCA.cpy"
        )
        node = next(p for p in sql_graph.programs if p.program_id == "SQLPGM")
        assert node.copies == ["DCLCUST", "SQLCA"]

    def test_include_inside_a_member_is_a_nested_edge(self, sql_graph):
        nested = {(e.program, e.member) for e in sql_graph.copy_edges if e.nested}
        assert ("DCLCUST", "DCLADDR") in nested
        assert sql_graph.programs_using("DCLADDR") == ["SQLPGM"]

    def test_copybook_impact_finds_the_including_program(self, sql_graph):
        report = CopybookImpactAnalyzer(sql_graph).analyze("SQLCA")
        assert report.direct_programs == ["SQLPGM"]
        assert "SQLCODE" in report.fields
        assert report.unresolved == []

    def test_include_edges_use_the_copy_label(self, sql_graph):
        assert '-.->|"COPY"| C_SQLCA' in sql_graph.to_mermaid()
        assert 'label="COPY", style=dashed' in sql_graph.to_dot()

    def test_missing_dclgen_include_is_reported_unresolved(self, tmp_path, copybooks):
        program = tmp_path / "P.cbl"
        program.write_text(SQL_PROGRAM)
        graph = CodebaseGraphBuilder(copybook_paths=[str(copybooks)]).build(
            [str(program)]
        )
        edge = next(e for e in graph.copy_edges if e.member == "DCLCUST")
        assert edge.path is None
        assert any(
            note.startswith("EXEC SQL INCLUDE member DCLCUST")
            for note in graph.unresolved
        )

    def test_precompiler_members_keep_their_edge_but_are_not_unresolved(
        self, tmp_path, copybooks
    ):
        program = tmp_path / "P.cbl"
        program.write_text(
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. DB2PGM.\n"
            "       DATA DIVISION.\n"
            "       WORKING-STORAGE SECTION.\n"
            "           EXEC SQL INCLUDE SQLCA END-EXEC.\n"
            "           EXEC SQL INCLUDE SQLDA END-EXEC.\n"
            "       PROCEDURE DIVISION.\n"
            "       P.\n"
            "           STOP RUN.\n"
        )
        graph = CodebaseGraphBuilder(copybook_paths=[str(copybooks)]).build(
            [str(program)]
        )
        members = {e.member: e.path for e in graph.copy_edges}
        assert members == {"SQLCA": None, "SQLDA": None}
        assert not any("SQLCA" in note or "SQLDA" in note for note in graph.unresolved)

    def test_precompiler_member_included_from_a_copybook_is_not_unresolved(
        self, tmp_path
    ):
        books = tmp_path / "books"
        books.mkdir()
        (books / "DB2WS.cpy").write_text(
            "           EXEC SQL INCLUDE SQLCA END-EXEC.\n"
        )
        program = tmp_path / "P.cbl"
        program.write_text(
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. NESTPGM.\n"
            "       DATA DIVISION.\n"
            "       WORKING-STORAGE SECTION.\n"
            "       COPY DB2WS.\n"
            "       PROCEDURE DIVISION.\n"
            "       P.\n"
            "           STOP RUN.\n"
        )
        graph = CodebaseGraphBuilder(copybook_paths=[str(books)]).build([str(program)])
        assert ("DB2WS", "SQLCA") in {
            (e.program, e.member) for e in graph.copy_edges if e.nested
        }
        assert not any("SQLCA" in note for note in graph.unresolved)

    def test_copy_of_a_precompiler_member_is_still_reported(self, tmp_path, copybooks):
        program = tmp_path / "P.cbl"
        program.write_text(
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. COPIER.\n"
            "       DATA DIVISION.\n"
            "       WORKING-STORAGE SECTION.\n"
            "           EXEC SQL INCLUDE SQLCA END-EXEC.\n"
            "       COPY SQLCA.\n"
            "       PROCEDURE DIVISION.\n"
            "       P.\n"
            "           STOP RUN.\n"
        )
        graph = CodebaseGraphBuilder(copybook_paths=[str(copybooks)]).build(
            [str(program)]
        )
        assert any(note.startswith("COPY member SQLCA") for note in graph.unresolved)

    def test_copy_and_include_of_one_missing_member_give_one_note(
        self, tmp_path, copybooks
    ):
        program = tmp_path / "P.cbl"
        program.write_text(
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. BOTHWAYS.\n"
            "       DATA DIVISION.\n"
            "       WORKING-STORAGE SECTION.\n"
            "       COPY DCLGONE.\n"
            "           EXEC SQL INCLUDE DCLGONE END-EXEC.\n"
            "       PROCEDURE DIVISION.\n"
            "       P.\n"
            "           STOP RUN.\n"
        )
        graph = CodebaseGraphBuilder(copybook_paths=[str(copybooks)]).build(
            [str(program)]
        )
        assert [e.member for e in graph.copy_edges] == ["DCLGONE"]
        notes = [n for n in graph.unresolved if "DCLGONE" in n]
        assert len(notes) == 1
        assert notes[0].startswith("COPY member DCLGONE")

    def test_lowercase_and_quoted_include_names(self, tmp_path):
        books = tmp_path / "books"
        books.mkdir()
        (books / "SQLCA.cpy").write_text(SQLCA_MEMBER)
        (books / "DCLCUST.cpy").write_text("       01  DCLCUST PIC X.\n")
        program = tmp_path / "P.cbl"
        program.write_text(
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. LOWPGM.\n"
            "       DATA DIVISION.\n"
            "       WORKING-STORAGE SECTION.\n"
            "           exec sql include sqlca end-exec.\n"
            "           EXEC SQL INCLUDE 'DCLCUST' END-EXEC.\n"
            "       PROCEDURE DIVISION.\n"
            "       P.\n"
            "           STOP RUN.\n"
        )
        graph = CodebaseGraphBuilder(copybook_paths=[str(books)]).build([str(program)])
        resolved = {e.member: e.path for e in graph.copy_edges}
        assert resolved == {
            "SQLCA": str(books / "SQLCA.cpy"),
            "DCLCUST": str(books / "DCLCUST.cpy"),
        }
        assert CopybookImpactAnalyzer(graph).analyze("DCLCUST").direct_programs == [
            "LOWPGM"
        ]

    def test_copy_and_include_of_one_member_give_one_edge(self, tmp_path):
        books = tmp_path / "books"
        books.mkdir()
        (books / "SQLCA.cpy").write_text(SQLCA_MEMBER)
        (books / "BOTH.cpy").write_text(
            "       COPY SQLCA.\n           EXEC SQL INCLUDE SQLCA END-EXEC.\n"
        )
        program = tmp_path / "P.cbl"
        program.write_text(
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. TWICE.\n"
            "       DATA DIVISION.\n"
            "       WORKING-STORAGE SECTION.\n"
            "       COPY SQLCA.\n"
            "           EXEC SQL INCLUDE SQLCA END-EXEC.\n"
            "       COPY BOTH.\n"
            "       PROCEDURE DIVISION.\n"
            "       P.\n"
            "           STOP RUN.\n"
        )
        graph = CodebaseGraphBuilder(copybook_paths=[str(books)]).build([str(program)])
        pairs = [(e.program, e.member, e.nested) for e in graph.copy_edges]
        assert pairs.count(("TWICE", "SQLCA", False)) == 1
        assert pairs.count(("BOTH", "SQLCA", True)) == 1
        assert graph.programs_using("SQLCA") == ["TWICE"]

    def test_include_as_an_ordinary_word_is_not_an_edge(self, tmp_path, copybooks):
        program = tmp_path / "P.cbl"
        program.write_text(
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. PLAIN.\n"
            "       DATA DIVISION.\n"
            "       WORKING-STORAGE SECTION.\n"
            "       01 INCLUDE-FLAG PIC X VALUE 'INCLUDE SQLCA END-EXEC'.\n"
            "       PROCEDURE DIVISION.\n"
            "       P.\n"
            "           STOP RUN.\n"
        )
        graph = CodebaseGraphBuilder(copybook_paths=[str(copybooks)]).build(
            [str(program)]
        )
        assert graph.copy_edges == []


class TestProgramsUsing:
    def test_direct_only(self, graph):
        assert graph.programs_using("LEVEL2", transitive=False) == ["SUBPGM"]

    def test_transitive_reaches_through_nesting(self, graph):
        assert graph.programs_using("LEVEL2") == ["MAINPGM", "SUBPGM"]
        assert graph.programs_using("LEVEL3") == ["MAINPGM", "SUBPGM"]

    def test_transitive_default_is_true(self, graph):
        assert graph.programs_using("LEVEL3") == graph.programs_using(
            "LEVEL3", transitive=True
        )

    def test_deepest_member_has_no_direct_user(self, graph):
        assert graph.programs_using("LEVEL3", transitive=False) == []

    def test_accepts_a_file_name(self, graph):
        assert graph.programs_using("LEVEL3.cpy") == graph.programs_using("LEVEL3")

    def test_circular_members_terminate(self, graph):
        assert graph.programs_using("CIRCULARB") == ["DYNPGM"]

    def test_unknown_member_has_no_users(self, graph):
        assert graph.programs_using("NOSUCH") == []
        assert graph.programs_using("") == []


# ---------------------------------------------------------------------------
# Failure handling
# ---------------------------------------------------------------------------


class TestFailureHandling:
    def test_unparseable_file_lands_in_errors_without_killing_the_run(
        self, source_tree, copybooks
    ):
        (source_tree / "BROKEN.cbl").write_text(BROKEN_PROGRAM)
        graph = CodebaseGraphBuilder(
            copybook_paths=[str(copybooks)]
        ).build_from_directory(str(source_tree))
        broken = [e for e in graph.errors if e["path"].endswith("BROKEN.cbl")]
        assert broken and "parse error" in broken[0]["error"]
        # The rest of the tree is unaffected.
        assert "MAINPGM" in graph.program_ids
        assert _edge(graph.call_edges, "MAINPGM", "SUBPGM")

    def test_unparseable_file_is_marked_on_its_node(self, tmp_path):
        broken = tmp_path / "BROKEN.cbl"
        broken.write_text(BROKEN_PROGRAM)
        graph = CodebaseGraphBuilder().build([str(broken)])
        node = graph.programs[0]
        assert node.parse_failed is True
        assert node.program_id == "BROKEN"  # assumed from the file name
        assert any("assumed from the file name" in n for n in graph.unresolved)

    def test_unreadable_file_is_recorded(self, tmp_path):
        missing = tmp_path / "GONE.cbl"
        graph = CodebaseGraphBuilder().build([str(missing)])
        assert graph.programs[0].parse_failed is True
        assert any(e["path"] == str(missing) for e in graph.errors)
        assert any(
            "COPY statements could not be scanned" in n for n in graph.unresolved
        )

    def test_unparseable_file_still_contributes_copy_edges(self, tmp_path, copybooks):
        # A COPY scan does not need a successful parse.
        broken = tmp_path / "HALF.cbl"
        broken.write_text("       COPY CUSTOMER.\n       nonsense {{{\n")
        graph = CodebaseGraphBuilder(copybook_paths=[str(copybooks)]).build(
            [str(broken)]
        )
        assert any(e.member == "CUSTOMER" for e in graph.copy_edges)

    def test_duplicate_program_id_is_reported(self, tmp_path):
        for name in ("A.cbl", "B.cbl"):
            (tmp_path / name).write_text(SELF_CALLING_PROGRAM)
        graph = CodebaseGraphBuilder().build(
            [str(tmp_path / "A.cbl"), str(tmp_path / "B.cbl")]
        )
        assert any("duplicate PROGRAM-ID LOOPER" in n for n in graph.unresolved)
        assert len(graph.programs) == 2

    def test_several_units_in_one_file_are_all_graphed(self, tmp_path):
        nested = tmp_path / "NESTED.cbl"
        nested.write_text(
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. OUTERPGM.\n"
            "       DATA DIVISION.\n"
            "       WORKING-STORAGE SECTION.\n"
            "       COPY CUSTOMER.\n"
            "       PROCEDURE DIVISION.\n"
            "       P.\n"
            '           CALL "OUTERCALLEE".\n'
            "           STOP RUN.\n"
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. INNERPGM.\n"
            "       PROCEDURE DIVISION.\n"
            "       Q.\n"
            '           CALL "INNERCALLEE".\n'
            "           GOBACK.\n"
            "       END PROGRAM INNERPGM.\n"
            "       END PROGRAM OUTERPGM.\n"
        )
        graph = CodebaseGraphBuilder().build([str(nested)])
        assert "OUTERPGM" in graph.program_ids
        assert "INNERPGM" in graph.program_ids
        # A contained unit's CALL is not attributed to the unit enclosing it.
        assert graph.callees_of("OUTERPGM") == ["OUTERCALLEE"]
        assert graph.callees_of("INNERPGM") == ["INNERCALLEE"]
        assert any("program units" in n for n in graph.unresolved)


# ---------------------------------------------------------------------------
# Building
# ---------------------------------------------------------------------------


class TestBuilding:
    def test_build_from_directory_filters_by_extension(self, tmp_path):
        (tmp_path / "KEEP.cbl").write_text(SELF_CALLING_PROGRAM)
        (tmp_path / "SKIP.txt").write_text(SELF_CALLING_PROGRAM)
        graph = CodebaseGraphBuilder().build_from_directory(str(tmp_path))
        assert [p.path for p in graph.programs] == [str(tmp_path / "KEEP.cbl")]

    def test_build_from_directory_honours_custom_extensions(self, tmp_path):
        (tmp_path / "P.cbl").write_text(SELF_CALLING_PROGRAM)
        (tmp_path / "Q.cblx").write_text(SELF_CALLING_PROGRAM)
        graph = CodebaseGraphBuilder().build_from_directory(
            str(tmp_path), extensions=(".cblx",)
        )
        assert [p.path for p in graph.programs] == [str(tmp_path / "Q.cblx")]

    def test_build_from_directory_recurses(self, tmp_path):
        nested = tmp_path / "a" / "b"
        nested.mkdir(parents=True)
        (nested / "DEEP.COB").write_text(SELF_CALLING_PROGRAM)
        graph = CodebaseGraphBuilder().build_from_directory(str(tmp_path))
        assert len(graph.programs) == 1

    def test_build_from_directory_rejects_a_non_directory(self, tmp_path):
        with pytest.raises(NotADirectoryError):
            CodebaseGraphBuilder().build_from_directory(str(tmp_path / "nope"))

    def test_empty_input(self):
        graph = CodebaseGraphBuilder().build([])
        assert graph.programs == []
        assert graph.to_dict()["summary"]["program_count"] == 0

    def test_duplicate_paths_are_parsed_once(self, tmp_path):
        program = tmp_path / "ONE.cbl"
        program.write_text(SELF_CALLING_PROGRAM)
        graph = CodebaseGraphBuilder().build([str(program), str(program)])
        assert len(graph.programs) == 1

    def test_chunking_does_not_change_the_result(self, source_tree, copybooks):
        whole = CodebaseGraphBuilder(
            copybook_paths=[str(copybooks)]
        ).build_from_directory(str(source_tree))
        chunked = CodebaseGraphBuilder(
            copybook_paths=[str(copybooks)], chunk_size=1
        ).build_from_directory(str(source_tree))
        assert chunked.to_dict() == whole.to_dict()

    def test_explicit_worker_count(self, source_tree):
        graph = CodebaseGraphBuilder(workers=1).build_from_directory(str(source_tree))
        assert graph.program_ids == ["DYNPGM", "MAINPGM", "SUBPGM"]


# ---------------------------------------------------------------------------
# Serialization and determinism
# ---------------------------------------------------------------------------


class TestSerialization:
    def test_program_node_dict_shape(self):
        node = ProgramNode(program_id="A", path="a.cbl", calls=["B"], copies=["C"])
        assert node.to_dict() == {
            "program_id": "A",
            "path": "a.cbl",
            "calls": ["B"],
            "copies": ["C"],
            "parse_failed": False,
        }

    def test_call_edge_dict_shape(self):
        assert CallEdge(caller="A", callee="B").to_dict() == {
            "caller": "A",
            "callee": "B",
            "is_dynamic": False,
            "resolved": True,
        }

    def test_copy_edge_dict_shape(self):
        assert CopyEdge(program="A", member="M").to_dict() == {
            "program": "A",
            "member": "M",
            "path": None,
            "nested": False,
            "library": None,
            "parent_path": None,
        }

    def test_graph_dict_keys(self, graph):
        payload = graph.to_dict()
        assert set(payload) == {
            "programs",
            "call_edges",
            "copy_edges",
            "cycles",
            "unresolved",
            "errors",
            "summary",
        }
        assert set(payload["summary"]) == {
            "program_count",
            "call_edge_count",
            "copy_edge_count",
            "member_count",
            "cycle_count",
            "unresolved_count",
            "error_count",
        }

    def test_graph_dict_is_json_serializable(self, graph):
        assert json.loads(json.dumps(graph.to_dict()))["summary"]["program_count"] == 3

    def test_lists_are_sorted(self, graph):
        assert graph.unresolved == sorted(graph.unresolved)
        assert [p.program_id for p in graph.programs] == sorted(
            p.program_id for p in graph.programs
        )

    def test_members_property(self, graph):
        assert graph.members == sorted(graph.members)
        assert {"LEVEL1", "LEVEL2", "LEVEL3", "CUSTOMER"} <= set(graph.members)


class TestDeterminism:
    def test_two_builds_agree(self, source_tree, copybooks):
        first = CodebaseGraphBuilder(
            copybook_paths=[str(copybooks)]
        ).build_from_directory(str(source_tree))
        second = CodebaseGraphBuilder(
            copybook_paths=[str(copybooks)]
        ).build_from_directory(str(source_tree))
        assert first.to_dict() == second.to_dict()
        assert first.to_dot() == second.to_dot()
        assert first.to_mermaid() == second.to_mermaid()

    def test_input_order_does_not_matter(self, source_tree, copybooks):
        files = sorted(str(p) for p in source_tree.iterdir())
        forward = CodebaseGraphBuilder(copybook_paths=[str(copybooks)]).build(files)
        backward = CodebaseGraphBuilder(copybook_paths=[str(copybooks)]).build(
            list(reversed(files))
        )
        assert forward.to_dict() == backward.to_dict()


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


class TestMermaid:
    def test_header_and_nodes(self, graph):
        text = graph.to_mermaid()
        assert text.splitlines()[0] == "flowchart LR"
        assert '    P_MAINPGM["MAINPGM"]' in text
        assert '    C_LEVEL1[/"LEVEL1"/]' in text

    def test_hyphenated_names_are_sanitized_in_ids_but_kept_in_labels(self, tmp_path):
        program = tmp_path / "H.cbl"
        program.write_text(
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. MY-PROG.\n"
            "       PROCEDURE DIVISION.\n"
            "       P.\n"
            '           CALL "OTHER-PROG".\n'
            "           GOBACK.\n"
        )
        text = CodebaseGraphBuilder().build([str(program)]).to_mermaid()
        assert "P_MY_PROG" in text
        assert '["MY-PROG"]' in text
        # A raw hyphenated id would be read as an arrow fragment.
        assert "P_MY-PROG" not in text

    def test_edges_are_rendered_with_quoted_labels(self, graph):
        text = graph.to_mermaid()
        assert '    P_MAINPGM -->|"CALL"| P_SUBPGM' in text
        assert '    P_DYNPGM -->|"CALL (dynamic, partial)"| P_SUBPGM' in text
        assert '    P_MAINPGM -.->|"COPY"| C_LEVEL1' in text
        assert '    C_LEVEL1 -.->|"COPY (nested)"| C_LEVEL2' in text

    def test_external_callee_gets_its_own_shape(self, graph):
        assert '    P_REPORTER(["REPORTER (external)"])' in graph.to_mermaid()

    def test_every_referenced_node_is_declared(self, graph):
        text = graph.to_mermaid()
        declared = {
            line.strip().split("[")[0].split("(")[0]
            for line in text.splitlines()[1:]
            if "-->" not in line and "-.->" not in line
        }
        for line in text.splitlines():
            if "-->" in line or "-.->" in line:
                source, target = line.strip().split(" ")[0], line.strip().split(" ")[-1]
                assert source in declared
                assert target in declared

    def test_labels_are_escaped(self):
        graph = CodebaseGraph(
            programs=[ProgramNode(program_id='A"<>B', path="a.cbl")],
        )
        text = graph.to_mermaid()
        assert "#lt;#gt;" in text
        assert '"A\'#lt;#gt;B"' in text

    def test_empty_graph_renders_a_placeholder(self):
        assert 'EMPTY["No programs found"]' in CodebaseGraph().to_mermaid()

    def test_unparsed_program_is_labelled(self, tmp_path):
        broken = tmp_path / "BROKEN.cbl"
        broken.write_text(BROKEN_PROGRAM)
        text = CodebaseGraphBuilder().build([str(broken)]).to_mermaid()
        assert '["BROKEN (unparsed)"]' in text


class TestDot:
    def test_header_and_nodes(self, graph):
        text = graph.to_dot()
        assert text.splitlines()[0] == "digraph codebase {"
        assert text.rstrip().endswith("}")
        assert 'P_MAINPGM [label="MAINPGM", shape=box' in text
        assert 'C_CUSTOMER [label="CUSTOMER", shape=note' in text

    def test_hyphenated_names_are_quoted_and_sanitized(self, tmp_path):
        program = tmp_path / "H.cbl"
        program.write_text(
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. MY-PROG.\n"
            "       PROCEDURE DIVISION.\n"
            "       P.\n"
            '           CALL "OTHER-PROG".\n'
            "           GOBACK.\n"
        )
        text = CodebaseGraphBuilder().build([str(program)]).to_dot()
        assert 'P_MY_PROG [label="MY-PROG"' in text
        assert "P_MY_PROG -> P_OTHER_PROG" in text
        # An unquoted hyphenated identifier is not legal DOT.
        assert "MY-PROG [" not in text

    def test_edges(self, graph):
        text = graph.to_dot()
        assert 'P_MAINPGM -> P_SUBPGM [label="CALL"];' in text
        assert 'P_MAINPGM -> C_LEVEL1 [label="COPY", style=dashed];' in text
        assert 'C_LEVEL2 -> C_LEVEL3 [label="COPY (nested)", style=dashed];' in text

    def test_unresolved_dynamic_edge_is_styled_apart(self, graph):
        assert 'label="CALL (dynamic, partial)", style=dotted' in graph.to_dot()

    def test_quotes_are_escaped(self):
        graph = CodebaseGraph(programs=[ProgramNode(program_id='A"B', path="a.cbl")])
        assert '\\"' in graph.to_dot()

    def test_empty_graph_renders_a_placeholder(self):
        assert 'EMPTY [label="No programs found"];' in CodebaseGraph().to_dot()

    def test_unparsed_program_is_coloured_apart(self, tmp_path):
        broken = tmp_path / "BROKEN.cbl"
        broken.write_text(BROKEN_PROGRAM)
        text = CodebaseGraphBuilder().build([str(broken)]).to_dot()
        assert "(unparsed)" in text
        assert "#f8d7da" in text

    def test_unparsed_label_line_break_is_a_single_dot_escape(self, tmp_path):
        # #274: the DOT line break went through _dot_str's backslash
        # escaping, so Graphviz rendered a literal backslash followed by "n".
        broken = tmp_path / "BROKEN.cbl"
        broken.write_text(BROKEN_PROGRAM)
        text = CodebaseGraphBuilder().build([str(broken)]).to_dot()
        assert 'label="BROKEN\\n(unparsed)"' in text
        assert "\\\\n" not in text


# ---------------------------------------------------------------------------
# Copybook impact
# ---------------------------------------------------------------------------


class TestCopybookImpact:
    def test_direct_impact(self, graph):
        report = CopybookImpactAnalyzer(graph).analyze("CUSTOMER")
        assert report.member == "CUSTOMER"
        assert report.direct_programs == ["MAINPGM"]
        assert report.transitive_programs == []
        assert report.chains == []

    def test_transitive_impact_and_chains(self, graph):
        report = CopybookImpactAnalyzer(graph).analyze("LEVEL3")
        assert report.direct_programs == []
        assert report.transitive_programs == ["MAINPGM", "SUBPGM"]
        assert report.chains == [
            ["MAINPGM", "LEVEL1", "LEVEL2", "LEVEL3"],
            ["SUBPGM", "LEVEL2", "LEVEL3"],
        ]
        assert report.program_count == 2

    def test_accepts_a_file_name(self, graph):
        analyzer = CopybookImpactAnalyzer(graph)
        assert (
            analyzer.analyze("level3.cpy").to_dict()
            == analyzer.analyze("LEVEL3").to_dict()
        )

    def test_fields_come_from_the_member(self, graph):
        report = CopybookImpactAnalyzer(graph).analyze("CUSTOMER")
        assert "CUSTOMER-RECORD" in report.fields
        assert "CUSTOMER-ID" in report.fields
        assert "ZIP" in report.fields
        assert report.fields == sorted(report.fields)
        assert report.unresolved == []

    def test_synthetic_record_names_are_not_reported_as_fields(self, graph):
        # LEVEL3.cpy holds only a level-05 item; the level-01 the parser
        # invents around it is not something the member contributes.
        report = CopybookImpactAnalyzer(graph).analyze("LEVEL3")
        assert report.fields == ["LEVEL3-FIELD"]

    def test_unresolved_member_reports_why_fields_are_missing(self, source_tree):
        graph = CodebaseGraphBuilder().build_from_directory(str(source_tree))
        report = CopybookImpactAnalyzer(graph).analyze("CUSTOMER")
        assert report.fields == []
        assert any("not resolved to a file" in note for note in report.unresolved)

    def test_unknown_member_is_reported(self, graph):
        report = CopybookImpactAnalyzer(graph).analyze("NOSUCH")
        assert report.direct_programs == []
        assert any("no COPY statement" in note for note in report.unresolved)

    def test_blank_member_is_rejected(self, graph):
        report = CopybookImpactAnalyzer(graph).analyze("   ")
        assert report.unresolved and "usable copybook member name" in (
            report.unresolved[0]
        )

    def test_circular_member_chain_terminates(self, graph):
        report = CopybookImpactAnalyzer(graph).analyze("CIRCULARB")
        assert report.direct_programs == []
        assert report.transitive_programs == ["DYNPGM"]
        assert ["DYNPGM", "CIRCULARA", "CIRCULARB"] in report.chains

    def test_report_dict_shape(self, graph):
        payload = CopybookImpactAnalyzer(graph).analyze("LEVEL3").to_dict()
        assert set(payload) == {
            "member",
            "direct_programs",
            "transitive_programs",
            "chains",
            "fields",
            "unresolved",
            "paths",
            "summary",
        }
        assert set(payload["summary"]) == {
            "direct_count",
            "transitive_count",
            "program_count",
            "field_count",
            "unresolved_count",
        }
        assert json.loads(json.dumps(payload))["member"] == "LEVEL3"

    def test_empty_report_defaults(self):
        report = ImpactReport(member="X")
        assert report.program_count == 0
        assert report.to_dict()["summary"]["field_count"] == 0

    def test_member_that_is_not_a_record_layout_is_reported(
        self, tmp_path, samples_dir
    ):
        books = tmp_path / "books"
        books.mkdir()
        shutil.copy(
            samples_dir / "copybooks" / "STANDARD-PROCEDURES.cpy",
            books / "STANDARD-PROCEDURES.cpy",
        )
        program = tmp_path / "P.cbl"
        program.write_text(
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. PROCPGM.\n"
            "       PROCEDURE DIVISION.\n"
            "       P.\n"
            "           COPY STANDARD-PROCEDURES.\n"
            "           STOP RUN.\n"
        )
        graph = CodebaseGraphBuilder(copybook_paths=[str(books)]).build([str(program)])
        report = CopybookImpactAnalyzer(graph).analyze("STANDARD-PROCEDURES")
        assert report.direct_programs == ["PROCPGM"]
        # Either it yields fields or it says why it could not -- never silence.
        assert report.fields or report.unresolved


# ---------------------------------------------------------------------------
# Low-level helpers
# ---------------------------------------------------------------------------


class TestHelpers:
    def test_sanitize_id_replaces_illegal_characters(self):
        assert _sanitize_id("MY-PROG") == "MY_PROG"
        assert _sanitize_id("A.B C") == "A_B_C"

    def test_sanitize_id_prefixes_a_leading_digit(self):
        assert _sanitize_id("9000-INIT") == "N_9000_INIT"

    def test_sanitize_id_never_returns_empty(self):
        assert _sanitize_id("") == "UNKNOWN"
        assert _program_node_id("") == "P_UNKNOWN"

    def test_member_fields_reports_an_unreadable_file(self, tmp_path):
        fields, problem = _member_fields(str(tmp_path / "gone.cpy"))
        assert fields == []
        assert problem is not None and "could not be read" in problem

    def test_call_with_no_target_name_is_reported(self):
        builder = CodebaseGraphBuilder()
        statement = CallStatement(SourceLocation(line=7, column=1))
        node = ProgramNode(program_id="P", path="p.cbl")
        edges: list[CallEdge] = []
        unresolved: list[str] = []
        builder._absorb_call(statement, "P", "p.cbl", node, edges, unresolved)
        assert edges == []
        assert unresolved == ["p.cbl: P: CALL at line 7 has no target name"]

    def test_unusable_copy_statement_is_reported(self, tmp_path, copybooks):
        program = tmp_path / "NOPERIOD.cbl"
        program.write_text(
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. NOPERIOD.\n"
            "       DATA DIVISION.\n"
            "       WORKING-STORAGE SECTION.\n"
            "       COPY CUSTOMER\n"
        )
        graph = CodebaseGraphBuilder(copybook_paths=[str(copybooks)]).build(
            [str(program)]
        )
        assert any("COPY statement not usable" in n for n in graph.unresolved)

    def test_member_whose_file_vanished_is_reported(self, tmp_path):
        books = tmp_path / "books"
        books.mkdir()
        (books / "OUTER.cpy").write_text("       01 OUTER-REC PIC X(4).\n")
        program = tmp_path / "P.cbl"
        program.write_text(
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. VANISH.\n"
            "       DATA DIVISION.\n"
            "       WORKING-STORAGE SECTION.\n"
            "       COPY OUTER.\n"
        )
        builder = CodebaseGraphBuilder(copybook_paths=[str(books)])
        # Resolve the member, then delete the file before it is scanned for
        # its own nested COPY statements.
        outer = str(books / "OUTER.cpy")
        (books / "OUTER.cpy").unlink()
        unresolved: list[str] = []
        assert builder._member_direct_copies("OUTER", outer, unresolved) == []
        assert any("could not be read" in note for note in unresolved)


class TestReviewFollowUps:
    """Review follow-ups on PR #212."""

    def test_dot_slash_path_does_not_create_a_phantom_program(
        self, tmp_path, monkeypatch
    ):
        (tmp_path / "PROG1.cbl").write_text(
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. ABC123.\n"
            "       DATA DIVISION.\n"
            "       WORKING-STORAGE SECTION.\n"
            "       COPY CUSTREC.\n"
            "       PROCEDURE DIVISION.\n"
            "       MAIN.\n"
            "           STOP RUN.\n"
        )
        monkeypatch.chdir(tmp_path)
        graph = CodebaseGraphBuilder().build(["./PROG1.cbl"])
        assert [node.program_id for node in graph.programs] == ["ABC123"]
        assert graph.programs_using("CUSTREC", transitive=False) == ["ABC123"]

    def test_extension_without_a_leading_dot_is_accepted(self, tmp_path):
        (tmp_path / "A.cbl").write_text(
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. A.\n"
            "       PROCEDURE DIVISION.\n"
            "       MAIN.\n"
            "           STOP RUN.\n"
        )
        graph = CodebaseGraphBuilder().build_from_directory(
            str(tmp_path), extensions=("cbl",)
        )
        assert [node.program_id for node in graph.programs] == ["A"]

    def test_member_caches_do_not_leak_between_builds(self, tmp_path):
        copybooks = tmp_path / "cpy"
        copybooks.mkdir()
        (copybooks / "OUTER.cpy").write_text("       01 WS-A PIC X.\n")
        (copybooks / "INNER2.cpy").write_text("       01 WS-B PIC X.\n")
        program = tmp_path / "P.cbl"
        program.write_text(
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. P.\n"
            "       DATA DIVISION.\n"
            "       WORKING-STORAGE SECTION.\n"
            "       COPY OUTER.\n"
            "       PROCEDURE DIVISION.\n"
            "       MAIN.\n"
            "           STOP RUN.\n"
        )
        builder = CodebaseGraphBuilder(copybook_paths=[str(copybooks)])
        first = builder.build([str(program)])
        assert ("OUTER", "INNER2") not in {
            (e.program, e.member) for e in first.copy_edges
        }
        (copybooks / "OUTER.cpy").write_text("       COPY INNER2.\n")
        second = builder.build([str(program)])
        assert ("OUTER", "INNER2") in {(e.program, e.member) for e in second.copy_edges}


def _program_copying(member: str, program_id: str) -> str:
    return (
        "       IDENTIFICATION DIVISION.\n"
        f"       PROGRAM-ID. {program_id}.\n"
        "       DATA DIVISION.\n"
        "       WORKING-STORAGE SECTION.\n"
        "       01 WS-REC.\n"
        f"           COPY {member}.\n"
        "       PROCEDURE DIVISION.\n"
        "           GOBACK.\n"
    )


class TestLibraryQualifiedCopy:
    """#351: COPY X OF/IN LIB resolves per library, not by bare member name."""

    @pytest.fixture
    def lib_graph(self, tmp_path) -> CodebaseGraph:
        books = tmp_path / "cpy"
        (books / "LIBA").mkdir(parents=True)
        (books / "LIBB").mkdir(parents=True)
        (books / "LIBA" / "REC.cpy").write_text("       05 RA PIC X.\n")
        (books / "LIBB" / "REC.cpy").write_text(
            "       05 RB PIC X.\n       COPY INNER.\n"
        )
        (books / "INNER.cpy").write_text("       05 RI PIC X.\n")
        src = tmp_path / "src"
        src.mkdir()
        (src / "PA.cbl").write_text(_program_copying("REC OF LIBA", "PA"))
        (src / "PB.cbl").write_text(_program_copying("REC OF LIBB", "PB"))
        (src / "PC.cbl").write_text(_program_copying("REC IN LIBB", "PC"))
        return CodebaseGraphBuilder(copybook_paths=[str(books)]).build_from_directory(
            str(src)
        )

    def test_each_program_edge_points_at_its_own_library(self, lib_graph, tmp_path):
        paths = {
            e.program: Path(e.path).relative_to(tmp_path).as_posix()
            for e in lib_graph.copy_edges
            if not e.nested and e.path
        }
        assert paths == {
            "PA": "cpy/LIBA/REC.cpy",
            "PB": "cpy/LIBB/REC.cpy",
            "PC": "cpy/LIBB/REC.cpy",
        }
        libraries = {e.program: e.library for e in lib_graph.copy_edges}
        assert libraries["PA"] == "LIBA"
        assert libraries["PC"] == "LIBB"

    def test_nested_member_of_one_library_is_followed(self, lib_graph, tmp_path):
        nested = [e for e in lib_graph.copy_edges if e.nested]
        assert [(e.program, e.member) for e in nested] == [("REC", "INNER")]
        assert nested[0].parent_path is not None
        assert Path(nested[0].parent_path) == tmp_path / "cpy" / "LIBB" / "REC.cpy"

    def test_nested_member_reaches_only_the_library_copiers(self, lib_graph):
        assert lib_graph.programs_using("INNER") == ["PB", "PC"]
        report = CopybookImpactAnalyzer(lib_graph).analyze("INNER")
        assert report.direct_programs == []
        assert report.transitive_programs == ["PB", "PC"]
        assert report.chains == [["PB", "REC", "INNER"], ["PC", "REC", "INNER"]]
        assert report.fields == ["RI"]

    def test_same_named_members_report_both_files(self, lib_graph):
        report = CopybookImpactAnalyzer(lib_graph).analyze("REC")
        assert report.direct_programs == ["PA", "PB", "PC"]
        assert report.fields == ["RA", "RB"]
        assert len(report.paths) == 2
        assert any("resolves to 2 different files" in n for n in report.unresolved)

    def test_unresolved_library_names_the_library(self, tmp_path):
        books = tmp_path / "cpy"
        books.mkdir()
        (books / "REC.cpy").write_text("       05 R PIC X.\n")
        program = tmp_path / "P.cbl"
        program.write_text(_program_copying("NOSUCH OF LIBX", "P"))
        graph = CodebaseGraphBuilder(copybook_paths=[str(books)]).build([str(program)])
        assert any("COPY member NOSUCH OF LIBX" in n for n in graph.unresolved)

    def test_hand_built_nested_edge_without_parent_path_matches_by_name(self):
        graph = CodebaseGraph(
            copy_edges=[
                CopyEdge(program="P", member="OUTER", path="/x/OUTER.cpy"),
                CopyEdge(program="OUTER", member="INNER", nested=True),
            ]
        )
        assert graph.programs_using("INNER") == ["P"]
