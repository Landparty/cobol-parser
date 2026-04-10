"""Tests for dead code (unreferenced procedure) detection."""

from cobolparser.analysis.dead_code import (
    DeadCodeAnalyzer,
    DeadCodeItem,
    DeadCodeReport,
)
from cobolparser.models.ast_base import SourceLocation
from cobolparser.models.program import (
    CobolDivision,
    CobolParagraph,
    CobolProgram,
    CobolSection,
)
from cobolparser.models.statements.control import (
    GoStatement,
    PerformStatement,
)
from cobolparser.models.statements.misc import (
    AlterStatement,
    ContinueStatement,
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
    # First target is the primary
    if targets:
        stmt.set_target_paragraph(targets[0])
    for t in targets[1:]:
        stmt.add_operand(t)
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
        """A paragraph never referenced should be detected as dead."""
        prog = _make_program(
            [
                ("MAIN-LOGIC", [_perform("PROCESS-DATA")]),
                ("PROCESS-DATA", [_continue()]),
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
        """The first paragraph is always referenced (entry point)."""
        prog = _make_program(
            [
                ("ENTRY-POINT", [_continue()]),
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
        """PERFORM A THRU C should mark A, B, and C as referenced."""
        prog = _make_program(
            [
                ("MAIN-LOGIC", [_perform("STEP-A", thru="STEP-C")]),
                ("STEP-A", [_continue()]),
                ("STEP-B", [_continue()]),
                ("STEP-C", [_continue()]),
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
        """GO TO ... DEPENDING ON should mark all target paragraphs."""
        prog = _make_program(
            [
                (
                    "MAIN-LOGIC",
                    [_goto_depending(["STEP-1", "STEP-2", "STEP-3"], "WS-IDX")],
                ),
                ("STEP-1", [_continue()]),
                ("STEP-2", [_continue()]),
                ("STEP-3", [_continue()]),
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
        """SORT INPUT/OUTPUT PROCEDURE should mark targets as referenced."""
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
                ("OUTPUT-PROC", [_continue()]),
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
        """ALTER should mark both from and to paragraphs as referenced."""
        prog = _make_program(
            [
                ("MAIN-LOGIC", [_alter("SWITCH-PARA", "NEW-TARGET")]),
                ("SWITCH-PARA", [_continue()]),
                ("NEW-TARGET", [_continue()]),
                ("ORPHAN", [_continue()]),
            ]
        )
        analyzer = DeadCodeAnalyzer()
        report = analyzer.analyze(prog)

        dead_names = [item.name for item in report.dead_items]
        assert "SWITCH-PARA" not in dead_names
        assert "NEW-TARGET" not in dead_names
        assert "ORPHAN" in dead_names

    def test_sections_and_nested_paragraphs(self) -> None:
        """Sections and paragraphs within sections should be detected."""
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
                        ("HELPER-PARA", [_continue()]),
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
        # HELPER-PARA is PERFORMed
        assert "HELPER-PARA" not in dead_names
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
        """Multiple dead paragraphs should all be reported."""
        prog = _make_program(
            [
                ("MAIN-LOGIC", [_continue()]),
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
        """find_dead_code() returns a DeadCodeReport."""
        prog = _make_program(
            [
                ("MAIN-LOGIC", [_continue()]),
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
        """Parse a real COBOL program and detect dead paragraphs."""
        source = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. DEADTEST.
       PROCEDURE DIVISION.
       MAIN-LOGIC.
           PERFORM PROCESS-DATA
           STOP RUN.
       PROCESS-DATA.
           DISPLAY "PROCESSING".
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
        """PERFORM THRU should mark all paragraphs in range as referenced."""
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
           DISPLAY "END".
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

    def test_find_dead_code_convenience(self) -> None:
        """CobolProgram.find_dead_code() works end-to-end."""
        source = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. CONVTEST.
       PROCEDURE DIVISION.
       MAIN-LOGIC.
           PERFORM USED-PARA
           STOP RUN.
       USED-PARA.
           DISPLAY "USED".
       DEAD-PARA.
           DISPLAY "DEAD".
"""
        result = parse_cobol(source, filename="convtest.cbl")
        assert result.ast is not None

        report = result.ast.find_dead_code()

        assert report.has_dead_code
        assert report.dead_items[0].name == "DEAD-PARA"
