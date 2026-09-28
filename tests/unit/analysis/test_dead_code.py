"""Tests for dead code (unreferenced procedure) detection."""

from cobolparser.analysis.dead_code import (
    DeadCodeAnalyzer,
    DeadCodeItem,
    DeadCodeReport,
)
from cobolparser.analysis.program_flow import ProgramFlowAnalyzer
from cobolparser.models.ast_base import SourceLocation
from cobolparser.models.program import (
    CobolDivision,
    CobolParagraph,
    CobolProgram,
    CobolSection,
)
from cobolparser.models.statements.call import EntryStatement
from cobolparser.models.statements.control import (
    GoStatement,
    PerformStatement,
    StopStatement,
)
from cobolparser.models.statements.misc import (
    AlterStatement,
    ContinueStatement,
    ExitStatement,
    GobackStatement,
    MergeStatement,
    SortStatement,
)
from cobolparser.parser import parse_cobol

# ---------------------------------------------------------------------------
# Helper to build a minimal AST for unit tests
# ---------------------------------------------------------------------------


def _make_program(
    paragraphs: list[tuple[str, list]],
    sections: list[tuple[str, list[tuple[str, list]]]] | None = None,
) -> CobolProgram:
    """Build a CobolProgram with the given procedure-division layout.

    Args:
        paragraphs: list of (name, [statement, ...]) for top-level paragraphs
        sections: optional list of (section_name, [(para_name, [stmt, ...]), ...])
    """
    loc = SourceLocation(1, 1)
    prog = CobolProgram("TEST-PROG", loc)

    id_div = CobolDivision("IDENTIFICATION", loc)
    prog.add_division(id_div)

    proc_div = CobolDivision("PROCEDURE", loc)
    prog.add_division(proc_div)

    line = 10
    if sections:
        for sec_name, sec_paras in sections:
            sec = CobolSection(sec_name, SourceLocation(line, 8))
            line += 1
            for pname, stmts in sec_paras:
                para = CobolParagraph(pname, SourceLocation(line, 8))
                for s in stmts:
                    para.add_statement(s)
                sec.add_paragraph(para)
                line += 1
            proc_div.add_section(sec)
    else:
        for pname, stmts in paragraphs:
            para = CobolParagraph(pname, SourceLocation(line, 8))
            for s in stmts:
                para.add_statement(s)
            proc_div.add_paragraph(para)
            line += 1

    return prog


def _perform(target: str, thru: str | None = None) -> PerformStatement:
    loc = SourceLocation(1, 12)
    stmt = PerformStatement(loc)
    stmt.set_target_paragraph(target)
    if thru:
        stmt.set_thru_paragraph(thru)
    return stmt


def _goto(target: str) -> GoStatement:
    loc = SourceLocation(1, 12)
    stmt = GoStatement(loc)
    stmt.set_target_paragraph(target)
    return stmt


def _goto_depending(targets: list[str], var: str) -> GoStatement:
    loc = SourceLocation(1, 12)
    stmt = GoStatement(loc)
    # First target is the primary; mirrors go_parser.py's
    # set_target_paragraph()/add_target_paragraph() calls.
    if targets:
        stmt.set_target_paragraph(targets[0])
    for t in targets[1:]:
        stmt.add_target_paragraph(t)
    stmt.set_depending_on_variable(var)
    return stmt


def _sort_with_procedures(
    input_proc: str | None = None,
    input_thru: str | None = None,
    output_proc: str | None = None,
    output_thru: str | None = None,
) -> SortStatement:
    loc = SourceLocation(1, 12)
    stmt = SortStatement(loc)
    stmt.set_file_name("SORT-FILE")
    if input_proc:
        stmt.set_input_procedure(input_proc, input_thru)
    if output_proc:
        stmt.set_output_procedure(output_proc, output_thru)
    return stmt


def _alter(from_para: str, to_para: str) -> AlterStatement:
    loc = SourceLocation(1, 12)
    stmt = AlterStatement(loc)
    stmt.add_alteration(from_para, to_para)
    return stmt


def _continue() -> ContinueStatement:
    return ContinueStatement(SourceLocation(1, 12))


def _stop_run() -> StopStatement:
    stmt = StopStatement(SourceLocation(1, 12))
    stmt.stop_type = "RUN"
    return stmt


def _entry(name: str) -> EntryStatement:
    stmt = EntryStatement(SourceLocation(1, 12))
    stmt.set_entry_name(name)
    return stmt


# ---------------------------------------------------------------------------
# Tests: DeadCodeAnalyzer
# ---------------------------------------------------------------------------


class TestDeadCodeAnalyzer:
    """Tests for the DeadCodeAnalyzer class."""

    def test_no_dead_code_all_referenced(self) -> None:
        """All paragraphs are referenced -> no dead code."""
        prog = _make_program(
            [
                ("MAIN-LOGIC", [_perform("PROCESS-DATA"), _perform("CLEANUP")]),
                ("PROCESS-DATA", [_continue()]),
                ("CLEANUP", [_continue()]),
            ]
        )
        analyzer = DeadCodeAnalyzer()
        report = analyzer.analyze(prog)

        assert not report.has_dead_code
        assert report.dead_count == 0
        assert report.total_procedures == 3
        assert report.referenced_procedures == 3

    def test_detect_unreferenced_paragraph(self) -> None:
        """A paragraph never referenced should be detected as dead.

        PROCESS-DATA ends with STOP RUN so it doesn't fall through into
        UNUSED-PARA -- the only thing under test is direct PERFORM
        reference tracking, not fall-through.
        """
        prog = _make_program(
            [
                ("MAIN-LOGIC", [_perform("PROCESS-DATA")]),
                ("PROCESS-DATA", [_stop_run()]),
                ("UNUSED-PARA", [_continue()]),
            ]
        )
        analyzer = DeadCodeAnalyzer()
        report = analyzer.analyze(prog)

        assert report.has_dead_code
        assert report.dead_count == 1
        assert report.dead_items[0].name == "UNUSED-PARA"
        assert report.dead_items[0].procedure_type == "PARAGRAPH"

    def test_entry_point_always_referenced(self) -> None:
        """The first paragraph is always referenced (entry point).

        ENTRY-POINT ends with STOP RUN so it doesn't fall through into
        UNREFERENCED -- the only thing under test is entry-point marking.
        """
        prog = _make_program(
            [
                ("ENTRY-POINT", [_stop_run()]),
                ("UNREFERENCED", [_continue()]),
            ]
        )
        analyzer = DeadCodeAnalyzer()
        report = analyzer.analyze(prog)

        assert report.dead_count == 1
        assert report.dead_items[0].name == "UNREFERENCED"
        # Entry point is NOT in dead items
        dead_names = [item.name for item in report.dead_items]
        assert "ENTRY-POINT" not in dead_names

    def test_perform_thru_marks_range(self) -> None:
        """PERFORM A THRU C should mark A, B, and C as referenced.

        STEP-C ends with STOP RUN so it doesn't fall through into ORPHAN --
        the only thing under test is THRU-range reference tracking.
        """
        prog = _make_program(
            [
                ("MAIN-LOGIC", [_perform("STEP-A", thru="STEP-C")]),
                ("STEP-A", [_continue()]),
                ("STEP-B", [_continue()]),
                ("STEP-C", [_stop_run()]),
                ("ORPHAN", [_continue()]),
            ]
        )
        analyzer = DeadCodeAnalyzer()
        report = analyzer.analyze(prog)

        dead_names = [item.name for item in report.dead_items]
        assert "STEP-A" not in dead_names
        assert "STEP-B" not in dead_names
        assert "STEP-C" not in dead_names
        assert "ORPHAN" in dead_names

    def test_goto_marks_target(self) -> None:
        """GO TO should mark its target as referenced."""
        prog = _make_program(
            [
                ("MAIN-LOGIC", [_goto("ERROR-HANDLER")]),
                ("ERROR-HANDLER", [_continue()]),
            ]
        )
        analyzer = DeadCodeAnalyzer()
        report = analyzer.analyze(prog)

        assert not report.has_dead_code

    def test_goto_depending_marks_all_targets(self) -> None:
        """GO TO ... DEPENDING ON should mark all target paragraphs.

        STEP-3 ends with STOP RUN so it doesn't fall through into ORPHAN --
        the only thing under test is computed GO TO reference tracking.
        """
        prog = _make_program(
            [
                (
                    "MAIN-LOGIC",
                    [_goto_depending(["STEP-1", "STEP-2", "STEP-3"], "WS-IDX")],
                ),
                ("STEP-1", [_continue()]),
                ("STEP-2", [_continue()]),
                ("STEP-3", [_stop_run()]),
                ("ORPHAN", [_continue()]),
            ]
        )
        analyzer = DeadCodeAnalyzer()
        report = analyzer.analyze(prog)

        dead_names = [item.name for item in report.dead_items]
        assert "STEP-1" not in dead_names
        assert "STEP-2" not in dead_names
        assert "STEP-3" not in dead_names
        assert "ORPHAN" in dead_names

    def test_sort_procedures_referenced(self) -> None:
        """SORT INPUT/OUTPUT PROCEDURE should mark targets as referenced.

        OUTPUT-PROC ends with STOP RUN so it doesn't fall through into
        ORPHAN -- the only thing under test is SORT reference tracking.
        """
        prog = _make_program(
            [
                (
                    "MAIN-LOGIC",
                    [
                        _sort_with_procedures(
                            input_proc="INPUT-PROC", output_proc="OUTPUT-PROC"
                        )
                    ],
                ),
                ("INPUT-PROC", [_continue()]),
                ("OUTPUT-PROC", [_stop_run()]),
                ("ORPHAN", [_continue()]),
            ]
        )
        analyzer = DeadCodeAnalyzer()
        report = analyzer.analyze(prog)

        dead_names = [item.name for item in report.dead_items]
        assert "INPUT-PROC" not in dead_names
        assert "OUTPUT-PROC" not in dead_names
        assert "ORPHAN" in dead_names

    def test_alter_references(self) -> None:
        """ALTER should mark only the new jump target (to_paragraph) as
        referenced, not the paragraph whose GO TO is being modified
        (from_paragraph).

        MAIN-LOGIC and NEW-TARGET both end with STOP RUN so neither falls
        through (into SWITCH-PARA and ORPHAN respectively) -- the only thing
        under test is ALTER subject-vs-target reference tracking.
        """
        prog = _make_program(
            [
                ("MAIN-LOGIC", [_alter("SWITCH-PARA", "NEW-TARGET"), _stop_run()]),
                ("SWITCH-PARA", [_continue()]),
                ("NEW-TARGET", [_stop_run()]),
                ("ORPHAN", [_continue()]),
            ]
        )
        analyzer = DeadCodeAnalyzer()
        report = analyzer.analyze(prog)

        dead_names = [item.name for item in report.dead_items]
        assert "SWITCH-PARA" in dead_names
        assert "NEW-TARGET" not in dead_names
        assert "ORPHAN" in dead_names

    def test_sections_and_nested_paragraphs(self) -> None:
        """Sections and paragraphs within sections should be detected.

        HELPER-PARA ends with STOP RUN so it doesn't fall through into
        UNUSED-SECTION -- the only thing under test is section/paragraph
        reference tracking, not fall-through.
        """
        prog = _make_program(
            paragraphs=[],
            sections=[
                (
                    "MAIN-SECTION",
                    [
                        ("MAIN-PARA", [_perform("HELPER-PARA")]),
                    ],
                ),
                (
                    "USED-SECTION",
                    [
                        ("HELPER-PARA", [_stop_run()]),
                    ],
                ),
                (
                    "UNUSED-SECTION",
                    [
                        ("DEAD-PARA", [_continue()]),
                    ],
                ),
            ],
        )
        analyzer = DeadCodeAnalyzer()
        report = analyzer.analyze(prog)

        dead_names = [item.name for item in report.dead_items]
        # MAIN-SECTION is the entry point
        assert "MAIN-SECTION" not in dead_names
        assert "MAIN-PARA" not in dead_names  # first para in first section
        # HELPER-PARA is PERFORMed, so USED-SECTION must also not be dead
        # (paragraph referenced -> parent section is considered referenced)
        assert "HELPER-PARA" not in dead_names
        assert "USED-SECTION" not in dead_names
        # UNUSED-SECTION and DEAD-PARA are unreferenced
        assert "UNUSED-SECTION" in dead_names
        assert "DEAD-PARA" in dead_names

    def test_empty_procedure_division(self) -> None:
        """Program with empty PROCEDURE DIVISION returns empty report."""
        loc = SourceLocation(1, 1)
        prog = CobolProgram("EMPTY-PROG", loc)
        proc_div = CobolDivision("PROCEDURE", loc)
        prog.add_division(proc_div)

        analyzer = DeadCodeAnalyzer()
        report = analyzer.analyze(prog)

        assert not report.has_dead_code
        assert report.total_procedures == 0

    def test_no_procedure_division(self) -> None:
        """Program without PROCEDURE DIVISION returns empty report."""
        loc = SourceLocation(1, 1)
        prog = CobolProgram("NO-PROC-PROG", loc)
        id_div = CobolDivision("IDENTIFICATION", loc)
        prog.add_division(id_div)

        analyzer = DeadCodeAnalyzer()
        report = analyzer.analyze(prog)

        assert not report.has_dead_code
        assert report.total_procedures == 0

    def test_case_insensitive_matching(self) -> None:
        """Procedure references should match case-insensitively."""
        prog = _make_program(
            [
                ("main-logic", [_perform("Process-Data")]),
                ("process-data", [_continue()]),
            ]
        )
        analyzer = DeadCodeAnalyzer()
        report = analyzer.analyze(prog)

        assert not report.has_dead_code

    def test_multiple_dead_paragraphs(self) -> None:
        """Multiple dead paragraphs should all be reported.

        MAIN-LOGIC ends with STOP RUN, so DEAD-1 is never fallen into --
        which in turn means the fall-through pass never treats DEAD-1 as
        reachable, so it can't credit DEAD-2 either, and so on down the
        chain. Without the STOP RUN, MAIN-LOGIC falling into DEAD-1 falling
        into DEAD-2 falling into DEAD-3 would make this the exact
        straight-line-program shape that's supposed to be *reachable*, not
        dead code.
        """
        prog = _make_program(
            [
                ("MAIN-LOGIC", [_stop_run()]),
                ("DEAD-1", [_continue()]),
                ("DEAD-2", [_continue()]),
                ("DEAD-3", [_continue()]),
            ]
        )
        analyzer = DeadCodeAnalyzer()
        report = analyzer.analyze(prog)

        assert report.dead_count == 3
        dead_names = {item.name for item in report.dead_items}
        assert dead_names == {"DEAD-1", "DEAD-2", "DEAD-3"}


# ---------------------------------------------------------------------------
# Tests: DeadCodeReport
# ---------------------------------------------------------------------------


class TestDeadCodeReport:
    """Tests for the DeadCodeReport data class."""

    def test_to_dict_format(self) -> None:
        """to_dict() should produce the expected JSON structure."""
        report = DeadCodeReport(
            dead_items=[
                DeadCodeItem("UNUSED-PARA", "PARAGRAPH", SourceLocation(20, 8)),
            ],
            total_procedures=5,
            referenced_procedures=4,
        )
        d = report.to_dict()

        assert "dead_code" in d
        assert "summary" in d
        assert len(d["dead_code"]) == 1
        assert d["dead_code"][0]["name"] == "UNUSED-PARA"
        assert d["dead_code"][0]["type"] == "PARAGRAPH"
        assert d["dead_code"][0]["location"]["line"] == 20
        assert d["summary"]["total_procedures"] == 5
        assert d["summary"]["referenced_procedures"] == 4
        assert d["summary"]["dead_procedures"] == 1

    def test_empty_report(self) -> None:
        """Empty report has correct defaults."""
        report = DeadCodeReport()
        assert not report.has_dead_code
        assert report.dead_count == 0
        assert report.total_procedures == 0


# ---------------------------------------------------------------------------
# Tests: CobolProgram.find_dead_code() convenience method
# ---------------------------------------------------------------------------


class TestCobolProgramFindDeadCode:
    """Tests for the find_dead_code() convenience method on CobolProgram."""

    def test_find_dead_code_returns_report(self) -> None:
        """find_dead_code() returns a DeadCodeReport.

        MAIN-LOGIC ends with STOP RUN so it doesn't fall through into
        UNREACHABLE.
        """
        prog = _make_program(
            [
                ("MAIN-LOGIC", [_stop_run()]),
                ("UNREACHABLE", [_continue()]),
            ]
        )
        report = prog.find_dead_code()

        assert isinstance(report, DeadCodeReport)
        assert report.dead_count == 1
        assert report.dead_items[0].name == "UNREACHABLE"


# ---------------------------------------------------------------------------
# Tests: Integration with real COBOL parsing
# ---------------------------------------------------------------------------


class TestDeadCodeIntegration:
    """Integration tests using parse_cobol to build the AST."""

    def test_parsed_program_with_dead_code(self) -> None:
        """Parse a real COBOL program and detect dead paragraphs.

        PROCESS-DATA ends with STOP RUN so it doesn't fall through into
        UNUSED-PARA.
        """
        source = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. DEADTEST.
       PROCEDURE DIVISION.
       MAIN-LOGIC.
           PERFORM PROCESS-DATA
           STOP RUN.
       PROCESS-DATA.
           DISPLAY "PROCESSING"
           STOP RUN.
       UNUSED-PARA.
           DISPLAY "NEVER CALLED".
"""
        result = parse_cobol(source, filename="deadtest.cbl")
        assert result.ast is not None

        analyzer = DeadCodeAnalyzer()
        report = analyzer.analyze(result.ast)

        dead_names = [item.name for item in report.dead_items]
        assert "UNUSED-PARA" in dead_names
        assert "MAIN-LOGIC" not in dead_names
        assert "PROCESS-DATA" not in dead_names

    def test_parsed_program_all_referenced(self) -> None:
        """Parse a program where all paragraphs are referenced."""
        source = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. ALLUSED.
       PROCEDURE DIVISION.
       MAIN-LOGIC.
           PERFORM STEP-1
           PERFORM STEP-2
           STOP RUN.
       STEP-1.
           DISPLAY "STEP 1".
       STEP-2.
           DISPLAY "STEP 2".
"""
        result = parse_cobol(source, filename="allused.cbl")
        assert result.ast is not None

        analyzer = DeadCodeAnalyzer()
        report = analyzer.analyze(result.ast)

        assert not report.has_dead_code

    def test_parsed_program_perform_thru(self) -> None:
        """PERFORM THRU should mark all paragraphs in range as referenced.

        INIT-END ends with STOP RUN so it doesn't fall through into
        ORPHAN-PARA.
        """
        source = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. THRUTEST.
       PROCEDURE DIVISION.
       MAIN-LOGIC.
           PERFORM INIT-START THRU INIT-END
           STOP RUN.
       INIT-START.
           DISPLAY "START".
       INIT-MIDDLE.
           DISPLAY "MIDDLE".
       INIT-END.
           DISPLAY "END"
           STOP RUN.
       ORPHAN-PARA.
           DISPLAY "ORPHAN".
"""
        result = parse_cobol(source, filename="thrutest.cbl")
        assert result.ast is not None

        analyzer = DeadCodeAnalyzer()
        report = analyzer.analyze(result.ast)

        dead_names = [item.name for item in report.dead_items]
        assert "INIT-START" not in dead_names
        assert "INIT-MIDDLE" not in dead_names
        assert "INIT-END" not in dead_names
        assert "ORPHAN-PARA" in dead_names

    def test_top_level_paragraph_before_section_stays_first_in_order(self) -> None:
        """A paragraph before the first SECTION must stay first in physical
        (source) order, not be reordered after all section-owned paragraphs.

        Regression test: ``_collect_procedures`` used to append all
        section-owned paragraphs before top-level paragraphs, so a program
        that legally mixes the two (paragraphs before the first SECTION)
        ended up with an ``_ordered_procedures`` list that no longer matched
        source order. That corrupted entry-point detection (``[0]`` became
        the wrong procedure) since the analyzer always treats the first
        entry as the referenced program entry point.
        """
        source = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TESTPROG.
       PROCEDURE DIVISION.
       INIT-PARA.
           DISPLAY 'INIT'.
       MAIN-SECTION SECTION.
       FIRST-PARA.
           DISPLAY 'FIRST'.
           STOP RUN.
"""
        result = parse_cobol(source, filename="mixedorder.cbl")
        assert result.ast is not None

        analyzer = DeadCodeAnalyzer()
        report = analyzer.analyze(result.ast)

        assert analyzer._ordered_procedures == [
            "INIT-PARA",
            "MAIN-SECTION",
            "FIRST-PARA",
        ]
        # INIT-PARA is the entry point (first in source order), so it must
        # not be reported as dead code even though nothing PERFORMs it.
        dead_names = [item.name for item in report.dead_items]
        assert "INIT-PARA" not in dead_names

    def test_duplicate_name_across_top_level_and_section_not_double_counted(
        self,
    ) -> None:
        """A name reused both as a top-level paragraph and a section-owned
        paragraph must be recorded once in ``_ordered_procedures``, whichever
        occurrence comes first in source order.

        Regression test: interleaving top-level paragraphs and section-owned
        paragraphs by source line (the fix for the mixed-order bug above)
        made the existing dedup guard order-dependent -- it previously only
        guarded the top-level-paragraph branch, which was safe when sections
        were always collected first. Once collection order can put a
        top-level occurrence before a section-owned occurrence of the same
        name, an unguarded section branch would append it a second time.
        """
        source = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. DUPTEST.
       PROCEDURE DIVISION.
       DUP-NAME.
           DISPLAY 'TOP-LEVEL'.
       MAIN-SECTION SECTION.
       DUP-NAME.
           DISPLAY 'IN-SECTION'.
           STOP RUN.
"""
        result = parse_cobol(source, filename="duptest.cbl")
        assert result.ast is not None

        analyzer = DeadCodeAnalyzer()
        report = analyzer.analyze(result.ast)

        assert analyzer._ordered_procedures == ["DUP-NAME", "MAIN-SECTION"]
        assert report.total_procedures == 2

    def test_duplicate_name_across_top_level_paragraph_and_section_header(
        self,
    ) -> None:
        """A name reused as a top-level paragraph and later as a SECTION
        header must be recorded once, and the SECTION's own paragraphs must
        still be tracked under it.

        Regression test: the SECTION-registration branch (unlike the
        paragraph branches) had no dedup guard at all, so a same-named
        top-level paragraph occurring earlier in source would be silently
        overwritten and duplicated in ``_ordered_procedures`` when the
        SECTION was collected. Also verifies ``_section_paragraphs`` is
        still populated for the section even when its own header
        registration was skipped due to the collision, so the paragraph
        loop's ``.append()`` doesn't KeyError.
        """
        source = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. DUPTEST2.
       PROCEDURE DIVISION.
       DUP-NAME.
           DISPLAY 'TOP-LEVEL'.
       DUP-NAME SECTION.
       FIRST-PARA.
           DISPLAY 'FIRST'.
           STOP RUN.
"""
        result = parse_cobol(source, filename="duptest2.cbl")
        assert result.ast is not None

        analyzer = DeadCodeAnalyzer()
        report = analyzer.analyze(result.ast)

        assert analyzer._ordered_procedures == ["DUP-NAME", "FIRST-PARA"]
        assert report.total_procedures == 2
        assert analyzer._section_paragraphs["DUP-NAME"] == ["FIRST-PARA"]

    def test_goto_depending_target_sharing_name_with_variable(self) -> None:
        """A computed GO TO target that shares its name with the DEPENDING
        ON variable must still be marked referenced, not just filtered out.
        """
        # PARA-A and RUN-FLAG each end in STOP RUN so neither is reachable
        # via fall-through -- the only thing that can mark RUN-FLAG
        # referenced is the computed GO TO's own target list, keeping this
        # a precise regression test for the operand-filtering bug (as
        # opposed to also being satisfiable by fall-through crediting).
        source = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. GOTOSHARE.
       PROCEDURE DIVISION.
       MAIN-LOGIC.
           GO TO PARA-A RUN-FLAG DEPENDING ON RUN-FLAG
           STOP RUN.
       PARA-A.
           DISPLAY "A"
           STOP RUN.
       RUN-FLAG.
           DISPLAY "FLAG".
"""
        result = parse_cobol(source, filename="gotoshare.cbl")
        assert result.ast is not None

        analyzer = DeadCodeAnalyzer()
        report = analyzer.analyze(result.ast)

        dead_names = [item.name for item in report.dead_items]
        assert "RUN-FLAG" not in dead_names
        assert "PARA-A" not in dead_names

    def test_find_dead_code_convenience(self) -> None:
        """CobolProgram.find_dead_code() works end-to-end.

        USED-PARA ends with STOP RUN so it doesn't fall through into
        DEAD-PARA.
        """
        source = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. CONVTEST.
       PROCEDURE DIVISION.
       MAIN-LOGIC.
           PERFORM USED-PARA
           STOP RUN.
       USED-PARA.
           DISPLAY "USED"
           STOP RUN.
       DEAD-PARA.
           DISPLAY "DEAD".
"""
        result = parse_cobol(source, filename="convtest.cbl")
        assert result.ast is not None

        report = result.ast.find_dead_code()

        assert report.has_dead_code
        assert report.dead_items[0].name == "DEAD-PARA"


# ---------------------------------------------------------------------------
# _collect_sort_refs with INPUT/OUTPUT PROCEDURE THRU
# ---------------------------------------------------------------------------


def _sort_stmt(
    input_proc: str | None = None,
    input_thru: str | None = None,
    output_proc: str | None = None,
    output_thru: str | None = None,
) -> SortStatement:
    loc = SourceLocation(1, 12)
    stmt = SortStatement(loc)
    stmt.set_file_name("FILE-SORT")
    if input_proc:
        stmt.set_input_procedure(input_proc, input_thru)
    if output_proc:
        stmt.set_output_procedure(output_proc, output_thru)
    return stmt


def _merge_stmt(
    output_proc: str | None = None,
    output_thru: str | None = None,
) -> MergeStatement:
    loc = SourceLocation(1, 12)
    stmt = MergeStatement(loc)
    stmt.set_file_name("FILE-MERGE")
    if output_proc:
        stmt.set_output_procedure(output_proc, output_thru)
    return stmt


class TestSortMergeThruReferences:
    def test_sort_input_procedure_thru_marks_range(self) -> None:
        """IN-END ends with STOP RUN so it doesn't fall through into
        DEAD-PARA."""
        prog = _make_program(
            paragraphs=[
                ("MAIN", [_sort_stmt(input_proc="IN-START", input_thru="IN-END")]),
                ("IN-START", [ContinueStatement(SourceLocation(1, 12))]),
                ("IN-MIDDLE", [ContinueStatement(SourceLocation(1, 12))]),
                ("IN-END", [_stop_run()]),
                ("DEAD-PARA", [ContinueStatement(SourceLocation(1, 12))]),
            ]
        )
        report = DeadCodeAnalyzer().analyze(prog)
        dead = [i.name for i in report.dead_items]
        assert "IN-START" not in dead
        assert "IN-MIDDLE" not in dead
        assert "IN-END" not in dead
        assert "DEAD-PARA" in dead

    def test_sort_output_procedure_thru_marks_range(self) -> None:
        """OUT-B ends with STOP RUN so it doesn't fall through into
        ORPHAN."""
        prog = _make_program(
            paragraphs=[
                ("MAIN", [_sort_stmt(output_proc="OUT-A", output_thru="OUT-B")]),
                ("OUT-A", [ContinueStatement(SourceLocation(1, 12))]),
                ("OUT-B", [_stop_run()]),
                ("ORPHAN", [ContinueStatement(SourceLocation(1, 12))]),
            ]
        )
        report = DeadCodeAnalyzer().analyze(prog)
        dead = [i.name for i in report.dead_items]
        assert "OUT-A" not in dead
        assert "OUT-B" not in dead
        assert "ORPHAN" in dead

    def test_sort_with_both_procedures(self) -> None:
        prog = _make_program(
            paragraphs=[
                (
                    "MAIN",
                    [
                        _sort_stmt(
                            input_proc="IN-PROC",
                            input_thru="IN-END",
                            output_proc="OUT-PROC",
                            output_thru="OUT-END",
                        )
                    ],
                ),
                ("IN-PROC", [ContinueStatement(SourceLocation(1, 12))]),
                ("IN-END", [ContinueStatement(SourceLocation(1, 12))]),
                ("OUT-PROC", [ContinueStatement(SourceLocation(1, 12))]),
                ("OUT-END", [ContinueStatement(SourceLocation(1, 12))]),
            ]
        )
        report = DeadCodeAnalyzer().analyze(prog)
        dead = [i.name for i in report.dead_items]
        assert not dead  # all procedures are referenced

    def test_merge_output_procedure_thru_marks_range(self) -> None:
        """MRG-END ends with STOP RUN so it doesn't fall through into
        DEAD."""
        prog = _make_program(
            paragraphs=[
                ("MAIN", [_merge_stmt(output_proc="MRG-START", output_thru="MRG-END")]),
                ("MRG-START", [ContinueStatement(SourceLocation(1, 12))]),
                ("MRG-MID", [ContinueStatement(SourceLocation(1, 12))]),
                ("MRG-END", [_stop_run()]),
                ("DEAD", [ContinueStatement(SourceLocation(1, 12))]),
            ]
        )
        report = DeadCodeAnalyzer().analyze(prog)
        dead = [i.name for i in report.dead_items]
        assert "MRG-START" not in dead
        assert "MRG-MID" not in dead
        assert "MRG-END" not in dead
        assert "DEAD" in dead


# ---------------------------------------------------------------------------
# _mark_thru_range with inverted range (start > end — no-op)
# ---------------------------------------------------------------------------


class TestMarkThruRangeInverted:
    def test_inverted_thru_range_does_not_mark_procedures(self) -> None:
        # PERFORM PARA-B THRU PARA-A where B comes *after* A in source order
        # _mark_thru_range should be a no-op when start_index > end_index
        prog = _make_program(
            paragraphs=[
                ("MAIN", [_perform("PARA-B", thru="PARA-A")]),
                ("PARA-A", [ContinueStatement(SourceLocation(1, 12))]),
                ("PARA-B", [ContinueStatement(SourceLocation(1, 12))]),
            ]
        )
        report = DeadCodeAnalyzer().analyze(prog)
        dead = [i.name for i in report.dead_items]
        # PARA-A is directly between PARA-A and PARA-B per source order;
        # inverted range means only the direct targets (PARA-A, PARA-B) stay
        # referenced because they were named — range marking itself is skipped.
        assert "PARA-A" not in dead
        assert "PARA-B" not in dead

    def test_thru_range_with_unknown_names_is_noop(self) -> None:
        """MAIN ends with STOP RUN so it doesn't fall through into
        REAL-PARA."""
        prog = _make_program(
            paragraphs=[
                ("MAIN", [_perform("UNKNOWN-START", thru="UNKNOWN-END"), _stop_run()]),
                ("REAL-PARA", [ContinueStatement(SourceLocation(1, 12))]),
            ]
        )
        report = DeadCodeAnalyzer().analyze(prog)
        dead = [i.name for i in report.dead_items]
        assert "REAL-PARA" in dead  # not referenced at all


# ---------------------------------------------------------------------------
# _collect_alter_refs
# ---------------------------------------------------------------------------


class TestAlterReferences:
    def test_alter_marks_only_to_paragraph(self) -> None:
        """Only the ALTER's new target (to_paragraph) counts as a reference.

        The subject of the ALTER (from_paragraph) is the paragraph whose
        internal GO TO is being modified -- naming it in the ALTER is not an
        incoming jump, so it must not be protected from dead-code detection
        just because it appears there.

        MAIN and PARA-Z both end with STOP RUN so neither falls through
        (into PARA-X and DEAD respectively) -- the only thing under test is
        ALTER subject-vs-target reference tracking.
        """
        loc = SourceLocation(1, 12)
        alter = AlterStatement(loc)
        alter.add_alteration("PARA-X", "PARA-Y")
        alter.add_alteration("PARA-Y", "PARA-Z")
        prog = _make_program(
            paragraphs=[
                ("MAIN", [alter, _stop_run()]),
                ("PARA-X", [ContinueStatement(loc)]),
                ("PARA-Y", [ContinueStatement(loc)]),
                ("PARA-Z", [_stop_run()]),
                ("DEAD", [ContinueStatement(loc)]),
            ]
        )
        report = DeadCodeAnalyzer().analyze(prog)
        dead = [i.name for i in report.dead_items]
        # PARA-X is only ever named as an ALTER "from" subject -- never
        # actually jumped to -- so it is genuinely dead.
        assert "PARA-X" in dead
        assert "PARA-Y" not in dead
        assert "PARA-Z" not in dead
        assert "DEAD" in dead

    def test_alter_never_called_paragraph_is_dead(self) -> None:
        """Regression test for the specific repro: a paragraph named only as
        the ALTER subject (never PERFORMed/GONE TO) must be reported dead,
        matching ProgramFlowAnalyzer's unreachable_nodes on the same input.

        Each paragraph ends with GOBACK/STOP RUN so there is no implicit
        fall-through between paragraphs muddying reachability -- the only
        thing under test is the ALTER subject-vs-target handling.
        """
        source = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. ALTERDEAD.
       PROCEDURE DIVISION.
       MAIN-LOGIC.
           ALTER NEVER-CALLED TO PROCEED TO SOME-TARGET
           STOP RUN.
       SOME-TARGET.
           DISPLAY "TARGET"
           GOBACK.
       NEVER-CALLED.
           DISPLAY "NEVER CALLED".
"""
        result = parse_cobol(source, filename="alterdead.cbl")
        assert result.ast is not None

        dead_code_report = DeadCodeAnalyzer().analyze(result.ast)
        dead_names = {i.name for i in dead_code_report.dead_items}
        assert "NEVER-CALLED" in dead_names

        flow_report = ProgramFlowAnalyzer().analyze(result.ast)
        assert "NEVER-CALLED" in flow_report.unreachable_nodes


# ---------------------------------------------------------------------------
# _collect_entry_refs
# ---------------------------------------------------------------------------


class TestEntryReferences:
    """Regression tests for the audit finding: a paragraph containing an
    ENTRY statement is a legitimate alternate external entry point (callable
    via CALL 'entry-name') and must never be reported as dead code, even
    though nothing internally PERFORMs or GOes to it."""

    def test_entry_paragraph_not_reported_dead(self) -> None:
        prog = _make_program(
            paragraphs=[
                ("MAIN-PARA", [_continue()]),
                ("ALT-ENTRY-PARA", [_entry("'ALTENTRY'"), _continue()]),
            ]
        )
        report = DeadCodeAnalyzer().analyze(prog)
        dead = [i.name for i in report.dead_items]
        assert "ALT-ENTRY-PARA" not in dead

    def test_entry_paragraph_not_reported_dead_real_source(self) -> None:
        """End-to-end regression test using the finding's repro shape."""
        source = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. ALTENTRYPROG.
       PROCEDURE DIVISION.
       MAIN-PARA.
           DISPLAY "IN MAIN".
           STOP RUN.
       ALT-ENTRY-PARA.
           ENTRY 'ALTENTRY'.
           DISPLAY "IN ALT ENTRY".
           GOBACK.
"""
        result = parse_cobol(source, filename="altentry.cbl")
        assert result.errors == []

        report = DeadCodeAnalyzer().analyze(result.ast)
        dead = [i.name for i in report.dead_items]
        assert "ALT-ENTRY-PARA" not in dead

    def test_entry_paragraph_in_section_marks_section_referenced_too(self) -> None:
        """The paragraph's parent section must also not be reported dead
        (via ``_propagate_section_references``' upward propagation)."""
        prog = _make_program(
            paragraphs=[],
            sections=[
                (
                    "MAIN-SECTION",
                    [("MAIN-PARA", [_continue()])],
                ),
                (
                    "ALT-ENTRY-SECTION",
                    [("ALT-ENTRY-PARA", [_entry("'ALTENTRY'"), _continue()])],
                ),
            ],
        )
        report = DeadCodeAnalyzer().analyze(prog)
        dead = [i.name for i in report.dead_items]
        assert "ALT-ENTRY-PARA" not in dead
        assert "ALT-ENTRY-SECTION" not in dead

    def test_unrelated_paragraph_still_reported_dead(self) -> None:
        """An ENTRY elsewhere does not blanket-mark every paragraph
        referenced -- an actually-unreferenced paragraph is still dead.

        ALT-ENTRY-PARA ends with STOP RUN so it doesn't fall through into
        TRULY-DEAD.
        """
        prog = _make_program(
            paragraphs=[
                ("MAIN-PARA", [_continue()]),
                ("ALT-ENTRY-PARA", [_entry("'ALTENTRY'"), _stop_run()]),
                ("TRULY-DEAD", [_continue()]),
            ]
        )
        report = DeadCodeAnalyzer().analyze(prog)
        dead = [i.name for i in report.dead_items]
        assert "TRULY-DEAD" in dead
        assert "ALT-ENTRY-PARA" not in dead

    def test_whitespace_entry_name_does_not_mask_dead_paragraph(self) -> None:
        """An ENTRY statement with a whitespace-only literal name isn't a
        real alternate entry point (matches the same filter
        program_flow/scanner.py's collect_entry_points applies), so it must
        not mask an otherwise-dead paragraph.

        MAIN-PARA ends with STOP RUN so it doesn't fall through into
        BOGUS-ENTRY-PARA.
        """
        prog = _make_program(
            paragraphs=[
                ("MAIN-PARA", [_stop_run()]),
                ("BOGUS-ENTRY-PARA", [_entry("\n"), _continue()]),
            ]
        )
        report = DeadCodeAnalyzer().analyze(prog)
        dead = [i.name for i in report.dead_items]
        assert "BOGUS-ENTRY-PARA" in dead

    def test_empty_entry_name_does_not_mask_dead_paragraph(self) -> None:
        """Same as above for an ENTRY literal that is empty after quote
        stripping (``''``).

        MAIN-PARA ends with STOP RUN so it doesn't fall through into
        BOGUS-ENTRY-PARA.
        """
        prog = _make_program(
            paragraphs=[
                ("MAIN-PARA", [_stop_run()]),
                ("BOGUS-ENTRY-PARA", [_entry("''"), _continue()]),
            ]
        )
        report = DeadCodeAnalyzer().analyze(prog)
        dead = [i.name for i in report.dead_items]
        assert "BOGUS-ENTRY-PARA" in dead

    def test_none_entry_name_does_not_mask_dead_paragraph(self) -> None:
        """An EntryStatement whose entry_name was never set (None) doesn't
        mask an otherwise-dead paragraph.

        MAIN-PARA ends with STOP RUN so it doesn't fall through into
        BOGUS-ENTRY-PARA.
        """
        entry = EntryStatement(SourceLocation(1, 12))
        # set_entry_name is deliberately NOT called -> entry_name stays None
        prog = _make_program(
            paragraphs=[
                ("MAIN-PARA", [_stop_run()]),
                ("BOGUS-ENTRY-PARA", [entry, _continue()]),
            ]
        )
        report = DeadCodeAnalyzer().analyze(prog)
        dead = [i.name for i in report.dead_items]
        assert "BOGUS-ENTRY-PARA" in dead


# ---------------------------------------------------------------------------
# _collect_fallthrough_refs
# ---------------------------------------------------------------------------


class TestFallThroughReferences:
    """Regression tests for the audit finding: DeadCodeAnalyzer had no
    concept of fall-through at all, so any paragraph reached purely by
    falling off the end of the previous one -- the default shape of a
    straight-line COBOL program -- was reported dead."""

    def test_straight_line_program_has_no_dead_code(self) -> None:
        """The audit's exact repro: three paragraphs with no PERFORM/GO TO
        between them at all, the last ending in STOP RUN. All three run on
        every execution via fall-through alone."""
        source = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. STRAIGHTLINE.
       PROCEDURE DIVISION.
       MAIN-PARA.
           DISPLAY 'IN MAIN'.
       PARA-TWO.
           DISPLAY 'IN TWO'.
       PARA-THREE.
           DISPLAY 'IN THREE'
           STOP RUN.
"""
        result = parse_cobol(source, filename="straightline.cbl")
        assert result.ast is not None

        report = DeadCodeAnalyzer().analyze(result.ast)
        assert not report.has_dead_code

    def test_stop_run_cuts_off_fall_through(self) -> None:
        """A paragraph ending in STOP RUN does not fall through -- the next
        paragraph is dead unless something else references it."""
        prog = _make_program(
            [
                ("MAIN-PARA", [_stop_run()]),
                ("NEVER-REACHED", [_continue()]),
            ]
        )
        report = DeadCodeAnalyzer().analyze(prog)
        dead = [i.name for i in report.dead_items]
        assert "NEVER-REACHED" in dead

    def test_goback_cuts_off_fall_through(self) -> None:
        """A paragraph ending in GOBACK does not fall through."""
        prog = _make_program(
            [
                ("MAIN-PARA", [GobackStatement(SourceLocation(1, 12))]),
                ("NEVER-REACHED", [_continue()]),
            ]
        )
        report = DeadCodeAnalyzer().analyze(prog)
        dead = [i.name for i in report.dead_items]
        assert "NEVER-REACHED" in dead

    def test_exit_program_cuts_off_fall_through(self) -> None:
        """A paragraph ending in EXIT PROGRAM does not fall through."""
        exit_stmt = ExitStatement(SourceLocation(1, 12))
        exit_stmt.set_exit_type("PROGRAM")
        prog = _make_program(
            [
                ("MAIN-PARA", [exit_stmt]),
                ("NEVER-REACHED", [_continue()]),
            ]
        )
        report = DeadCodeAnalyzer().analyze(prog)
        dead = [i.name for i in report.dead_items]
        assert "NEVER-REACHED" in dead

    def test_unconditional_goto_cuts_off_fall_through(self) -> None:
        """A bare GO TO as a paragraph's own last statement does not fall
        through -- it always jumps away."""
        prog = _make_program(
            [
                ("MAIN-PARA", [_goto("PARA-C")]),
                ("NEVER-REACHED", [_continue()]),
                ("PARA-C", [_stop_run()]),
            ]
        )
        report = DeadCodeAnalyzer().analyze(prog)
        dead = [i.name for i in report.dead_items]
        assert "NEVER-REACHED" in dead

    def test_terminator_earlier_in_paragraph_still_cuts_off_fall_through(
        self,
    ) -> None:
        """A hard terminator that isn't the paragraph's LAST top-level
        statement still cuts off fall-through -- once reached it always
        fires, so anything physically written after it in the same
        paragraph is itself unreachable and doesn't change whether the
        paragraph as a whole falls through."""
        prog = _make_program(
            [
                ("MAIN-PARA", [_stop_run(), _continue()]),
                ("NEVER-REACHED", [_continue()]),
            ]
        )
        report = DeadCodeAnalyzer().analyze(prog)
        dead = [i.name for i in report.dead_items]
        assert "NEVER-REACHED" in dead

    def test_stop_literal_does_not_cut_off_fall_through(self) -> None:
        """STOP 'literal' (as opposed to STOP RUN) merely halts pending
        operator action -- execution continues at the next statement, so it
        must not be treated as a hard terminator."""
        stop_literal = StopStatement(SourceLocation(1, 12))
        stop_literal.stop_type = "literal"
        prog = _make_program(
            [
                ("MAIN-PARA", [stop_literal]),
                ("STILL-REACHED", [_stop_run()]),
            ]
        )
        report = DeadCodeAnalyzer().analyze(prog)
        dead = [i.name for i in report.dead_items]
        assert "STILL-REACHED" not in dead

    def test_computed_goto_does_not_cut_off_fall_through(self) -> None:
        """GO TO ... DEPENDING ON is conditional -- if the subscript matches
        none of the targets, execution falls through -- so it must not
        suppress fall-through crediting even as a paragraph's last
        statement."""
        prog = _make_program(
            [
                ("MAIN-PARA", [_goto_depending(["BRANCH-A", "BRANCH-B"], "WS-IDX")]),
                ("STILL-REACHED", [_stop_run()]),
                ("BRANCH-A", [_stop_run()]),
                ("BRANCH-B", [_stop_run()]),
            ]
        )
        report = DeadCodeAnalyzer().analyze(prog)
        dead = [i.name for i in report.dead_items]
        assert "STILL-REACHED" not in dead

    def test_conditional_goto_inside_if_does_not_cut_off_fall_through(self) -> None:
        """A GO TO nested inside an IF only fires when the condition is
        true -- the paragraph still falls through whenever it isn't, so it
        must not be treated the same as an unconditional last-statement
        GO TO."""
        source = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. CONDGOTO.
       PROCEDURE DIVISION.
       PARA-A.
           IF WS-FLAG = 'Y'
               GO TO PARA-C
           END-IF.
       PARA-B.
           DISPLAY 'B'
           STOP RUN.
       PARA-C.
           DISPLAY 'C'
           STOP RUN.
"""
        result = parse_cobol(source, filename="condgoto.cbl")
        assert result.ast is not None

        report = DeadCodeAnalyzer().analyze(result.ast)
        dead = [i.name for i in report.dead_items]
        assert "PARA-B" not in dead

    def test_fall_through_does_not_cascade_from_an_unreached_paragraph(self) -> None:
        """A chain of non-terminating paragraphs that are themselves never
        reached must not credit each other purely for standing next to one
        another -- fall-through only propagates from a paragraph that is
        itself already known to be reachable."""
        prog = _make_program(
            [
                ("MAIN-PARA", [_stop_run()]),
                ("DEAD-1", [_continue()]),
                ("DEAD-2", [_continue()]),
                ("DEAD-3", [_stop_run()]),
            ]
        )
        report = DeadCodeAnalyzer().analyze(prog)
        dead = [i.name for i in report.dead_items]
        assert "DEAD-1" in dead
        assert "DEAD-2" in dead
        assert "DEAD-3" in dead

    def test_fall_through_into_section_header_reaches_its_first_paragraph(
        self,
    ) -> None:
        """A SECTION header has no statements of its own -- falling into one
        from a non-terminating predecessor must reach its first paragraph
        too."""
        prog = _make_program(
            paragraphs=[],
            sections=[
                ("FIRST-SECTION", [("FIRST-PARA", [_continue()])]),
                ("SECOND-SECTION", [("SECOND-PARA", [_stop_run()])]),
            ],
        )
        report = DeadCodeAnalyzer().analyze(prog)
        dead = [i.name for i in report.dead_items]
        assert not dead

    def test_fall_through_agrees_with_program_flow_analyzer(self) -> None:
        """DeadCodeAnalyzer and ProgramFlowAnalyzer must agree on the
        straight-line case -- prior to this fix they disagreed (dead_code.py
        had no fall-through concept at all)."""
        source = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. AGREETEST.
       PROCEDURE DIVISION.
       MAIN-PARA.
           DISPLAY 'IN MAIN'.
       PARA-TWO.
           DISPLAY 'IN TWO'.
       PARA-THREE.
           DISPLAY 'IN THREE'
           STOP RUN.
"""
        result = parse_cobol(source, filename="agreetest.cbl")
        assert result.ast is not None

        dead_report = DeadCodeAnalyzer().analyze(result.ast)
        flow_report = ProgramFlowAnalyzer().analyze(result.ast)

        assert not dead_report.has_dead_code
        assert flow_report.unreachable_nodes == []


# ---------------------------------------------------------------------------
# _propagate_section_references: downward broadcast must not resurrect
# siblings referenced only indirectly via another paragraph's own direct
# reference (2026-08-13 audit finding).
# ---------------------------------------------------------------------------


class TestSectionPropagationDoesNotResurrectSiblings:
    """Regression tests for the bug fixed by reordering
    `_propagate_section_references` to run its downward pass (section ->
    all paragraphs) before its upward pass (paragraph -> parent section),
    using only references that already existed beforehand.

    Before the fix, the upward pass ran first: any paragraph directly
    PERFORMed/GONE TO bootstrapped its *entire* parent section into
    "referenced," and the subsequent downward pass then broadcast that to
    every sibling paragraph -- including ones nothing actually calls and
    that fall-through never reaches. A plain `PERFORM child-paragraph`
    does not execute the rest of its section, unlike `PERFORM
    section-name`, which does.
    """

    def test_perform_of_one_paragraph_does_not_revive_dead_sibling(self) -> None:
        """PERFORM PARA-B (not PERFORM SEC-A) reaches only PARA-B -- it must
        not resurrect PARA-A, an unrelated sibling in the same section that
        nothing PERFORMs/GOes TO and that fall-through never reaches.

        MAIN-PARA ends with STOP RUN so it doesn't fall through into SEC-A.
        `_make_program` builds either sections or top-level paragraphs, not
        both, so MAIN-PARA lives in its own leading section here (same
        pattern as `test_sections_and_nested_paragraphs`).
        """
        prog = _make_program(
            paragraphs=[],
            sections=[
                ("MAIN-SECTION", [("MAIN-PARA", [_perform("PARA-B"), _stop_run()])]),
                (
                    "SEC-A",
                    [
                        ("PARA-A", [_continue()]),
                        ("PARA-B", [_continue()]),
                    ],
                ),
            ],
        )
        report = DeadCodeAnalyzer().analyze(prog)
        dead = [i.name for i in report.dead_items]
        assert "PARA-A" in dead
        assert "PARA-B" not in dead
        # SEC-A itself is still not dead -- one of its paragraphs is used.
        assert "SEC-A" not in dead

    def test_perform_section_name_still_marks_all_its_paragraphs(self) -> None:
        """A genuine PERFORM of the section name itself is unaffected by the
        fix -- real COBOL semantics say PERFORMing a section runs every
        paragraph in it from first to last, so all of them must stay
        referenced."""
        prog = _make_program(
            paragraphs=[],
            sections=[
                ("MAIN-SECTION", [("MAIN-PARA", [_perform("SEC-A"), _stop_run()])]),
                (
                    "SEC-A",
                    [
                        ("PARA-A", [_continue()]),
                        ("PARA-B", [_continue()]),
                    ],
                ),
            ],
        )
        report = DeadCodeAnalyzer().analyze(prog)
        assert not report.dead_items

    def test_goto_section_name_still_marks_all_its_paragraphs(self) -> None:
        """GO TO the section name itself is a direct reference too -- it
        must still cascade to every paragraph in the section via
        fall-through."""
        prog = _make_program(
            paragraphs=[],
            sections=[
                ("MAIN-SECTION", [("MAIN-PARA", [_goto("SEC-A")])]),
                (
                    "SEC-A",
                    [
                        ("PARA-A", [_continue()]),
                        ("PARA-B", [_stop_run()]),
                    ],
                ),
            ],
        )
        report = DeadCodeAnalyzer().analyze(prog)
        assert not report.dead_items


# ---------------------------------------------------------------------------
# Defensive/edge-case branches: malformed AST shapes and inline statements
# with no procedure-name operand, exercised directly to reach 100% branch
# coverage on this module.
# ---------------------------------------------------------------------------


class TestDefensiveEdgeCases:
    def test_section_with_blank_name_still_collects_its_paragraphs(self) -> None:
        """A CobolSection with no name (a malformed/synthetic node) still has
        its paragraphs collected as procedures -- they just aren't tied to
        any section for propagation purposes, since there is no section name
        to key `_section_paragraphs`/`_paragraph_section` on."""
        prog = _make_program(
            paragraphs=[],
            sections=[("", [("ORPHAN-PARA", [_continue()])])],
        )
        report = DeadCodeAnalyzer().analyze(prog)
        assert report.total_procedures == 1
        dead = [i.name for i in report.dead_items]
        # The first (and only) procedure is the entry point.
        assert "ORPHAN-PARA" not in dead

    def test_invalid_paragraph_name_inside_a_named_section_is_skipped(self) -> None:
        """A synthetic paragraph named '.' inside a real section is excluded
        from the analysis, same as at the top level."""
        prog = _make_program(
            paragraphs=[],
            sections=[
                (
                    "REAL-SECTION",
                    [(".", [_continue()]), ("REAL-PARA", [_continue()])],
                )
            ],
        )
        report = DeadCodeAnalyzer().analyze(prog)
        assert report.total_procedures == 2  # REAL-SECTION + REAL-PARA only

    def test_invalid_top_level_paragraph_name_is_skipped(self) -> None:
        """A synthetic top-level paragraph named '.' is excluded from the
        analysis entirely -- it's neither counted nor reported dead."""
        prog = _make_program(
            paragraphs=[("MAIN-PARA", [_stop_run()]), (".", [_continue()])],
        )
        report = DeadCodeAnalyzer().analyze(prog)
        assert report.total_procedures == 1

    def test_duplicate_top_level_paragraph_name_counted_once(self) -> None:
        """Two top-level paragraphs sharing a name (malformed source) are
        only registered once -- the second occurrence hits the dedup guard
        rather than becoming a duplicate report entry."""
        prog = _make_program(
            paragraphs=[
                ("MAIN-PARA", [_perform("DUP-PARA"), _stop_run()]),
                ("DUP-PARA", [_continue()]),
                ("DUP-PARA", [_continue()]),
            ],
        )
        report = DeadCodeAnalyzer().analyze(prog)
        assert report.total_procedures == 2
        dead = [i.name for i in report.dead_items]
        assert "DUP-PARA" not in dead

    def test_inline_perform_with_no_target_paragraph_adds_no_reference(self) -> None:
        """An inline PERFORM (e.g. PERFORM UNTIL ... END-PERFORM) has no
        `target_paragraph` -- it must not be treated as a reference to
        anything."""
        prog = _make_program(
            paragraphs=[
                ("MAIN-PARA", [PerformStatement(SourceLocation(1, 12)), _stop_run()]),
                ("UNREACHED", [_continue()]),
            ],
        )
        report = DeadCodeAnalyzer().analyze(prog)
        dead = [i.name for i in report.dead_items]
        assert "UNREACHED" in dead

    def test_merge_without_output_procedure_thru_adds_no_range(self) -> None:
        """MERGE with an output procedure but no THRU clause must not touch
        `_mark_thru_range` at all.

        MRG-PROC ends with STOP RUN so it doesn't fall through into
        UNREACHED -- the only thing under test is that the missing THRU
        clause doesn't trigger range-marking.
        """
        prog = _make_program(
            paragraphs=[
                ("MAIN-PARA", [_merge_stmt(output_proc="MRG-PROC"), _stop_run()]),
                ("MRG-PROC", [_stop_run()]),
                ("UNREACHED", [_continue()]),
            ],
        )
        report = DeadCodeAnalyzer().analyze(prog)
        dead = [i.name for i in report.dead_items]
        assert "MRG-PROC" not in dead
        assert "UNREACHED" in dead

    def test_merge_thru_with_no_output_procedure_is_a_noop_range(self) -> None:
        """A MERGE statement whose `output_procedure_thru` is set without a
        corresponding `output_procedure` (malformed/partial construction)
        must not crash `_mark_thru_range` -- the falsy `start` guard returns
        immediately instead of indexing `_ordered_procedures`."""
        stmt = MergeStatement(SourceLocation(1, 12))
        stmt.set_file_name("FILE-MERGE")
        stmt.set_output_procedure("", "MRG-END")
        prog = _make_program(
            paragraphs=[
                ("MAIN-PARA", [stmt, _stop_run()]),
                ("MRG-END", [_continue()]),
            ],
        )
        report = DeadCodeAnalyzer().analyze(prog)
        dead = [i.name for i in report.dead_items]
        # MRG-END is still referenced directly (output_procedure_thru is
        # always added as its own reference), just not via range-marking.
        assert "MRG-END" not in dead

    def test_alter_with_blank_target_adds_no_reference(self) -> None:
        """A malformed ALTER alteration with a blank `to_paragraph` (parser
        error-recovery shape) must not add a bogus empty-string reference."""
        prog = _make_program(
            paragraphs=[
                ("MAIN-PARA", [_alter("SWITCH-PARA", ""), _stop_run()]),
                ("SWITCH-PARA", [_continue()]),
            ],
        )
        report = DeadCodeAnalyzer().analyze(prog)
        dead = [i.name for i in report.dead_items]
        assert "SWITCH-PARA" in dead

    def test_entry_statement_with_no_parent_paragraph_adds_no_reference(self) -> None:
        """An ENTRY statement not attached to any paragraph resolves
        `section_name` to None (nothing to walk up the parent chain to) --
        it must not raise or add a bogus reference."""
        stmt = EntryStatement(SourceLocation(1, 12))
        stmt.set_entry_name("'ORPHAN-ENTRY'")
        prog = _make_program(
            paragraphs=[("MAIN-PARA", [_stop_run()])],
        )
        # Append directly to the paragraph's statement list without going
        # through add_statement()/add_child(), so the statement has no
        # parent and `section_name` falls through to None -- mirrors the
        # defensive path in `_collect_entry_refs`. get_all_statements()
        # still finds it via its dedicated "Paragraph.statements" traversal.
        prog.procedure_division.paragraphs[0].statements.append(stmt)
        report = DeadCodeAnalyzer().analyze(prog)
        assert not report.has_dead_code


class TestFallThroughOnlyEscapesReachableRuns:
    """Regression tests for the audit finding that fall-through was credited
    out of *any* referenced procedure, PERFORM targets included.

    A PERFORM returns to its caller at the end of its range -- it does not
    run on into the next paragraph. Treating it as if it did gave every
    paragraph after a performed one a fall-through edge that cannot happen
    at runtime, and since the canonical COBOL program is a MAIN paragraph
    of PERFORMs followed by the paragraphs it performs, the analyzer
    reported *no dead code at all* for the shape it is most often pointed
    at.
    """

    def test_canonical_perform_structured_program_reports_its_dead_paragraphs(
        self,
    ) -> None:
        """The audit's repro: MAIN performs three paragraphs, two others are
        never referenced by anything."""
        source = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TYPICAL.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 A PIC 9.
       PROCEDURE DIVISION.
       0000-MAIN.
           PERFORM 1000-INIT.
           PERFORM 2000-PROCESS.
           PERFORM 3000-TERM.
           STOP RUN.
       1000-INIT.
           MOVE 1 TO A.
       2000-PROCESS.
           MOVE 2 TO A.
       3000-TERM.
           MOVE 3 TO A.
       9998-ALSO-DEAD.
           MOVE 8 TO A.
       9999-NEVER-CALLED.
           MOVE 9 TO A.
"""
        result = parse_cobol(source, filename="typical.cbl")
        assert result.ast is not None

        report = DeadCodeAnalyzer().analyze(result.ast)
        assert sorted(item.name for item in report.dead_items) == [
            "9998-ALSO-DEAD",
            "9999-NEVER-CALLED",
        ]

    def test_perform_target_does_not_revive_the_paragraph_after_it(self) -> None:
        """The minimal case: PERFORM P-USED returns at P-USED's end, so
        P-ORPHAN is not reached by falling out of it."""
        prog = _make_program(
            [
                ("MAIN-P", [_perform("P-USED"), _stop_run()]),
                ("P-USED", [_continue()]),
                ("P-ORPHAN", [_continue()]),
            ]
        )
        report = DeadCodeAnalyzer().analyze(prog)
        assert [item.name for item in report.dead_items] == ["P-ORPHAN"]

    def test_goto_target_does_still_fall_through(self) -> None:
        """A GO TO lands in its target and carries on from there, so the
        paragraph after the target IS reachable -- unlike a PERFORM."""
        prog = _make_program(
            [
                ("MAIN-P", [_goto("P-B")]),
                ("P-A", [_continue()]),
                ("P-B", [_continue()]),
                ("P-C", [_stop_run()]),
            ]
        )
        report = DeadCodeAnalyzer().analyze(prog)
        assert [item.name for item in report.dead_items] == ["P-A"]

    def test_entry_paragraph_falls_through(self) -> None:
        """An ENTRY paragraph is an external entry point: a CALL starts
        execution there and runs on into what follows."""
        source = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. WITHENTRY.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 A PIC 9.
       PROCEDURE DIVISION.
       MAIN-P.
           STOP RUN.
       ALT-ENTRY.
           ENTRY 'ALTENT'.
           MOVE 1 TO A.
       AFTER-ENTRY.
           MOVE 2 TO A.
           GOBACK.
"""
        result = parse_cobol(source, filename="withentry.cbl")
        assert result.ast is not None

        report = DeadCodeAnalyzer().analyze(result.ast)
        assert [item.name for item in report.dead_items] == []

    def test_straight_line_fall_through_still_works(self) -> None:
        """The behaviour fall-through was added for is unchanged: with no
        PERFORM or GO TO anywhere, every paragraph runs."""
        source = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. STRAIGHTLINE.
       PROCEDURE DIVISION.
       MAIN-PARA.
           DISPLAY 'IN MAIN'.
       PARA-TWO.
           DISPLAY 'IN TWO'.
       PARA-THREE.
           DISPLAY 'IN THREE'
           STOP RUN.
"""
        result = parse_cobol(source, filename="straightline.cbl")
        assert result.ast is not None
        assert not DeadCodeAnalyzer().analyze(result.ast).has_dead_code

    def test_perform_thru_range_is_still_fully_referenced(self) -> None:
        """PERFORM A THRU C marks the whole range, but must not escape past
        C: ORPHAN sits after the range and nothing reaches it."""
        prog = _make_program(
            [
                ("MAIN-P", [_perform("STEP-A", thru="STEP-C"), _stop_run()]),
                ("STEP-A", [_continue()]),
                ("STEP-B", [_continue()]),
                ("STEP-C", [_continue()]),
                ("ORPHAN", [_continue()]),
            ]
        )
        report = DeadCodeAnalyzer().analyze(prog)
        assert [item.name for item in report.dead_items] == ["ORPHAN"]


class TestSectionParagraphsAfterTerminator:
    """A referenced section does not make every paragraph in it live: one
    after a paragraph that ends the run (STOP RUN, GOBACK, an unconditional
    GO TO) is never reached by running the section."""

    def test_paragraph_after_stop_run_in_fallen_into_section_is_dead(self) -> None:
        source = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. FALLSEC.
       PROCEDURE DIVISION.
       MAIN SECTION.
       M1.
           DISPLAY 'M'.
       S2 SECTION.
       P1.
           DISPLAY 'X'
           STOP RUN.
       P2.
           DISPLAY 'Y'.
"""
        result = parse_cobol(source, filename="fallsec.cbl")
        assert result.ast is not None
        report = DeadCodeAnalyzer().analyze(result.ast)
        assert [item.name for item in report.dead_items] == ["P2"]

    def test_paragraph_jumped_over_in_performed_section_is_dead(self) -> None:
        source = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. JUMPSEC.
       PROCEDURE DIVISION.
       MAIN SECTION.
       M1.
           PERFORM S2
           STOP RUN.
       S2 SECTION.
       P1.
           GO TO P3.
       P2.
           DISPLAY 'Y'.
       P3.
           EXIT.
"""
        result = parse_cobol(source, filename="jumpsec.cbl")
        assert result.ast is not None
        report = DeadCodeAnalyzer().analyze(result.ast)
        assert [item.name for item in report.dead_items] == ["P2"]

    def test_performed_section_without_terminator_is_all_live(self) -> None:
        source = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. LIVESEC.
       PROCEDURE DIVISION.
       MAIN SECTION.
       M1.
           PERFORM S2
           STOP RUN.
       S2 SECTION.
       P1.
           DISPLAY 'X'.
       P2.
           DISPLAY 'Y'.
"""
        result = parse_cobol(source, filename="livesec.cbl")
        assert result.ast is not None
        assert not DeadCodeAnalyzer().analyze(result.ast).has_dead_code


class TestContainedProgramScope:
    """Procedure names are local to a program unit: a nested program's
    PERFORM / ENTRY names its own paragraph, never its container's."""

    SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. OUTER.
       PROCEDURE DIVISION.
       MAIN-PARA.
           DISPLAY 'X'
           STOP RUN.
       HELPER.
           DISPLAY 'DEAD IN OUTER'.
       IDENTIFICATION DIVISION.
       PROGRAM-ID. INNER.
       PROCEDURE DIVISION.
       IN-MAIN.
           PERFORM HELPER
           GOBACK.
       HELPER.
           DISPLAY 'LIVE IN INNER'.
       END PROGRAM INNER.
       END PROGRAM OUTER.
"""

    def test_inner_perform_does_not_revive_outer_paragraph(self) -> None:
        result = parse_cobol(self.SOURCE, filename="nested.cbl")
        assert result.ast is not None
        report = DeadCodeAnalyzer().analyze(result.ast)
        assert [item.name for item in report.dead_items] == ["HELPER"]

    def test_inner_program_itself_still_sees_its_own_perform(self) -> None:
        result = parse_cobol(self.SOURCE, filename="nested.cbl")
        assert result.ast is not None
        inner = next(
            unit for unit in result.ast.program_units() if unit.program_name == "INNER"
        )
        assert not DeadCodeAnalyzer().analyze(inner).has_dead_code

    def test_inner_entry_is_not_an_outer_entry_point(self) -> None:
        source = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. OUTER.
       PROCEDURE DIVISION.
       MAIN-PARA.
           STOP RUN.
       ALT-PARA.
           DISPLAY 'DEAD IN OUTER'.
       IDENTIFICATION DIVISION.
       PROGRAM-ID. INNER.
       PROCEDURE DIVISION.
       ALT-PARA.
           ENTRY 'ALTIN'
           GOBACK.
       END PROGRAM INNER.
       END PROGRAM OUTER.
"""
        result = parse_cobol(source, filename="nested_entry.cbl")
        assert result.ast is not None
        dead = [i.name for i in DeadCodeAnalyzer().analyze(result.ast).dead_items]
        assert dead == ["ALT-PARA"]
        flow = ProgramFlowAnalyzer().analyze(result.ast)
        assert "ALT-PARA" not in flow.entry_points
        assert "ALT-PARA" in flow.unreachable_nodes
