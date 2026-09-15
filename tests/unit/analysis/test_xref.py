"""Tests for the cross-reference analyzer (xref.py).

Covers, both on hand-built ASTs and on real parsed COBOL:

- read vs write role separation (MOVE, arithmetic, COMPUTE, STRING/UNSTRING,
  INSPECT TALLYING, ACCEPT, READ INTO, WRITE FROM)
- condition, subscript, perform, goto, call-argument, host-variable and
  file-operation roles
- symbols referenced but never declared landing in ``report.undefined``
- the ``to_dict()`` shape of every dataclass
- a caveat being emitted for each best-effort extraction path
"""

from cobolparser.analysis.xref import (
    KIND_CONDITION_NAME,
    KIND_DATA_ITEM,
    KIND_FILE,
    KIND_PARAGRAPH,
    KIND_SECTION,
    ROLE_CALL_ARGUMENT,
    ROLE_CONDITION,
    ROLE_FILE_OPERATION,
    ROLE_GOTO,
    ROLE_HOST_VARIABLE,
    ROLE_PERFORM,
    ROLE_READ,
    ROLE_REFERENCE,
    ROLE_SUBSCRIPT,
    ROLE_WRITE,
    XREF_ROLES,
    XrefAnalyzer,
    XrefEntry,
    XrefReference,
    XrefReport,
    _partition_operand,
)
from cobolparser.models.ast_base import SourceLocation
from cobolparser.models.data_items import (
    CobolDataItem,
    ConditionNameItem,
    PictureClause,
)
from cobolparser.models.program import (
    CobolDivision,
    CobolParagraph,
    CobolProgram,
    CobolSection,
)
from cobolparser.models.statements.call import CallParameter, CallStatement
from cobolparser.models.statements.control import (
    EvaluateStatement,
    GoStatement,
    PerformStatement,
    WhenClause,
)
from cobolparser.models.statements.data import (
    InitializeStatement,
    MoveStatement,
    SetStatement,
)
from cobolparser.models.statements.io import IOReadStatement
from cobolparser.models.statements.misc import XmlJsonStatement
from cobolparser.parser import parse_cobol

LOC = SourceLocation(20, 12)


# ---------------------------------------------------------------------------
# Hand-built AST helpers
# ---------------------------------------------------------------------------


def _data_item(name: str, level: int = 1, line: int = 5) -> CobolDataItem:
    item = CobolDataItem(name, level, SourceLocation(line, 8))
    item.set_picture_clause(PictureClause("X(10)", SourceLocation(line, 30)))
    return item


def _make_program(
    paragraphs: list[tuple[str, list]],
    data_items: list[CobolDataItem] | None = None,
    section_name: str = "WORKING-STORAGE",
    program_name: str = "TEST-PROG",
) -> CobolProgram:
    """Build a CobolProgram with a WORKING-STORAGE section and paragraphs."""
    loc = SourceLocation(1, 1)
    prog = CobolProgram(program_name, loc)
    prog.add_division(CobolDivision("IDENTIFICATION", loc))

    if data_items:
        data_div = CobolDivision("DATA", SourceLocation(3, 8))
        section = CobolSection(section_name, SourceLocation(4, 8))
        for item in data_items:
            section.add_data_item(item)
        data_div.add_section(section)
        prog.add_division(data_div)

    proc_div = CobolDivision("PROCEDURE", SourceLocation(9, 8))
    line = 10
    for pname, stmts in paragraphs:
        para = CobolParagraph(pname, SourceLocation(line, 8))
        for stmt in stmts:
            para.add_statement(stmt)
        proc_div.add_paragraph(para)
        line += 1
    prog.add_division(proc_div)
    return prog


def _move(source: str, *targets: str, line: int = 20) -> MoveStatement:
    stmt = MoveStatement(SourceLocation(line, 12))
    stmt.set_source(source)
    for target in targets:
        stmt.add_target(target)
    return stmt


def _roles(report: XrefReport, name: str) -> list[str]:
    entry = report.entry_for(name)
    assert entry is not None, f"no entry for {name}"
    return [ref.role for ref in entry.references]


def _analyze_source(source: str) -> XrefReport:
    result = parse_cobol(source)
    assert result.ast is not None
    return XrefAnalyzer().analyze(result.ast)


# ---------------------------------------------------------------------------
# Roles: read vs write
# ---------------------------------------------------------------------------


def test_move_separates_read_and_write_roles():
    prog = _make_program(
        [("MAIN-PARA", [_move("WS-SOURCE", "WS-TARGET")])],
        data_items=[_data_item("WS-SOURCE", line=5), _data_item("WS-TARGET", line=6)],
    )
    report = XrefAnalyzer().analyze(prog)

    assert _roles(report, "WS-SOURCE") == [ROLE_READ]
    assert _roles(report, "WS-TARGET") == [ROLE_WRITE]


def test_move_reference_carries_location_statement_and_context():
    prog = _make_program(
        [("MAIN-PARA", [_move("WS-A", "WS-B", line=42)])],
        data_items=[_data_item("WS-A"), _data_item("WS-B")],
    )
    report = XrefAnalyzer().analyze(prog)

    ref = report.entry_for("WS-A").references[0]
    assert ref.location.line == 42
    assert ref.location.column == 12
    assert ref.statement == "MoveStatement"
    assert ref.context == "MAIN-PARA"
    assert ref.role in XREF_ROLES


def test_move_multiple_targets_all_written():
    prog = _make_program(
        [("MAIN-PARA", [_move("WS-A", "WS-B", "WS-C")])],
        data_items=[_data_item("WS-A"), _data_item("WS-B"), _data_item("WS-C")],
    )
    report = XrefAnalyzer().analyze(prog)

    assert _roles(report, "WS-B") == [ROLE_WRITE]
    assert _roles(report, "WS-C") == [ROLE_WRITE]


def test_arithmetic_roles_from_source():
    report = _analyze_source("""
       IDENTIFICATION DIVISION.
       PROGRAM-ID. ARITH.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-A  PIC 9(4).
       01  WS-B  PIC 9(4).
       01  WS-TOTAL PIC 9(6).
       PROCEDURE DIVISION.
       MAIN-PARA.
           ADD WS-A TO WS-B
           ADD WS-A WS-B GIVING WS-TOTAL
           STOP RUN.
""")
    assert _roles(report, "WS-TOTAL") == [ROLE_WRITE]
    assert ROLE_READ in _roles(report, "WS-A")
    # `ADD WS-A TO WS-B` writes WS-B; the second statement reads it.
    assert set(_roles(report, "WS-B")) == {ROLE_WRITE, ROLE_READ}


def test_arithmetic_target_recorded_once_per_statement():
    """`target` and `targets` hold the same operand -- one reference, not two."""
    report = _analyze_source("""
       IDENTIFICATION DIVISION.
       PROGRAM-ID. ARITH2.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-COUNT PIC 9(4).
       PROCEDURE DIVISION.
       MAIN-PARA.
           ADD 1 TO WS-COUNT
           STOP RUN.
""")
    assert _roles(report, "WS-COUNT") == [ROLE_WRITE]


def test_compute_target_is_write_and_operands_are_read():
    report = _analyze_source("""
       IDENTIFICATION DIVISION.
       PROGRAM-ID. COMP.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-A  PIC 9(4).
       01  WS-B  PIC 9(4).
       01  WS-C  PIC 9(4).
       PROCEDURE DIVISION.
       MAIN-PARA.
           COMPUTE WS-C = WS-A + WS-B
           STOP RUN.
""")
    assert _roles(report, "WS-C") == [ROLE_WRITE]
    assert _roles(report, "WS-A") == [ROLE_READ]
    assert _roles(report, "WS-B") == [ROLE_READ]


def test_string_unstring_and_inspect_roles():
    report = _analyze_source("""
       IDENTIFICATION DIVISION.
       PROGRAM-ID. STR.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-PART  PIC X(10).
       01  WS-TEXT  PIC X(30).
       01  WS-PTR   PIC 9(4).
       01  WS-COUNT PIC 9(4).
       PROCEDURE DIVISION.
       MAIN-PARA.
           STRING WS-PART DELIMITED BY SIZE INTO WS-TEXT
               WITH POINTER WS-PTR
           END-STRING
           UNSTRING WS-TEXT DELIMITED BY ',' INTO WS-PART
           END-UNSTRING
           INSPECT WS-TEXT TALLYING WS-COUNT FOR ALL 'A'
           STOP RUN.
""")
    assert ROLE_WRITE in _roles(report, "WS-TEXT")  # STRING INTO
    assert ROLE_READ in _roles(report, "WS-TEXT")  # UNSTRING source / INSPECT
    assert ROLE_READ in _roles(report, "WS-PART")  # STRING source
    assert ROLE_WRITE in _roles(report, "WS-PART")  # UNSTRING INTO
    assert _roles(report, "WS-PTR") == [ROLE_WRITE]
    assert _roles(report, "WS-COUNT") == [ROLE_WRITE]  # TALLYING counter


def test_accept_and_display_roles():
    report = _analyze_source("""
       IDENTIFICATION DIVISION.
       PROGRAM-ID. ACC.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-IN   PIC X(10).
       PROCEDURE DIVISION.
       MAIN-PARA.
           ACCEPT WS-IN
           DISPLAY WS-IN
           STOP RUN.
""")
    assert set(_roles(report, "WS-IN")) == {ROLE_WRITE, ROLE_READ}


# ---------------------------------------------------------------------------
# Roles: condition / subscript
# ---------------------------------------------------------------------------


def test_if_condition_operands_get_condition_role():
    report = _analyze_source("""
       IDENTIFICATION DIVISION.
       PROGRAM-ID. COND.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-A  PIC 9(4).
       01  WS-B  PIC 9(4).
       PROCEDURE DIVISION.
       MAIN-PARA.
           IF WS-A > WS-B
               DISPLAY 'BIG'
           END-IF
           STOP RUN.
""")
    assert _roles(report, "WS-A") == [ROLE_CONDITION]
    assert _roles(report, "WS-B") == [ROLE_CONDITION]


def test_perform_until_guard_is_a_condition():
    report = _analyze_source("""
       IDENTIFICATION DIVISION.
       PROGRAM-ID. PU.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-IDX  PIC 9(4).
       PROCEDURE DIVISION.
       MAIN-PARA.
           PERFORM UNTIL WS-IDX > 10
               ADD 1 TO WS-IDX
           END-PERFORM
           STOP RUN.
""")
    assert ROLE_CONDITION in _roles(report, "WS-IDX")


def test_evaluate_subject_is_a_condition():
    report = _analyze_source("""
       IDENTIFICATION DIVISION.
       PROGRAM-ID. EV.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-CODE  PIC X.
       01  WS-OUT   PIC X.
       PROCEDURE DIVISION.
       MAIN-PARA.
           EVALUATE WS-CODE
               WHEN 'A' MOVE 'X' TO WS-OUT
               WHEN OTHER MOVE 'Y' TO WS-OUT
           END-EVALUATE
           STOP RUN.
""")
    assert _roles(report, "WS-CODE") == [ROLE_CONDITION]
    assert set(_roles(report, "WS-OUT")) == {ROLE_WRITE}


def test_subscript_role_from_a_table_reference():
    report = _analyze_source("""
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SUBS.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-IDX  PIC 9(4).
       01  WS-NAME PIC X(5).
       01  WS-TBL.
           05  WS-ENTRY OCCURS 10 TIMES PIC X(5).
       PROCEDURE DIVISION.
       MAIN-PARA.
           MOVE WS-ENTRY (WS-IDX) TO WS-NAME
           STOP RUN.
""")
    assert _roles(report, "WS-ENTRY") == [ROLE_READ]
    assert _roles(report, "WS-IDX") == [ROLE_SUBSCRIPT]
    assert _roles(report, "WS-NAME") == [ROLE_WRITE]


def test_reference_modification_is_not_a_subscript():
    report = _analyze_source("""
       IDENTIFICATION DIVISION.
       PROGRAM-ID. REFMOD.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-TEXT PIC X(30).
       01  WS-PART PIC X(5).
       PROCEDURE DIVISION.
       MAIN-PARA.
           MOVE WS-TEXT (1:5) TO WS-PART
           STOP RUN.
""")
    assert _roles(report, "WS-TEXT") == [ROLE_READ]
    assert ROLE_SUBSCRIPT not in _roles(report, "WS-TEXT")


def test_index_name_from_indexed_by_is_a_declared_symbol():
    report = _analyze_source("""
       IDENTIFICATION DIVISION.
       PROGRAM-ID. IDX.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-TBL.
           05  WS-ROW OCCURS 5 TIMES INDEXED BY WS-I.
               10  WS-KEY PIC X(4).
       PROCEDURE DIVISION.
       MAIN-PARA.
           SET WS-I TO 1
           STOP RUN.
""")
    entry = report.entry_for("WS-I")
    assert entry is not None
    assert entry.kind == KIND_DATA_ITEM
    assert entry.definition is not None
    assert entry.level is None
    assert [ref.role for ref in entry.references] == [ROLE_WRITE]
    assert "WS-I" not in report.undefined


# ---------------------------------------------------------------------------
# Roles: control flow, calls, files, SQL
# ---------------------------------------------------------------------------


def test_perform_and_goto_roles_on_procedures():
    perform = PerformStatement(SourceLocation(21, 12))
    perform.set_target_paragraph("WORK-PARA")
    goto = GoStatement(SourceLocation(22, 12))
    goto.set_target_paragraph("END-PARA")

    prog = _make_program(
        [
            ("MAIN-PARA", [perform, goto]),
            ("WORK-PARA", []),
            ("END-PARA", []),
        ]
    )
    report = XrefAnalyzer().analyze(prog)

    work = report.entry_for("WORK-PARA")
    assert work.kind == KIND_PARAGRAPH
    assert [ref.role for ref in work.references] == [ROLE_PERFORM]
    assert _roles(report, "END-PARA") == [ROLE_GOTO]
    assert report.entry_for("MAIN-PARA").is_referenced is False


def test_perform_thru_marks_both_endpoints():
    report = _analyze_source("""
       IDENTIFICATION DIVISION.
       PROGRAM-ID. THRU.
       PROCEDURE DIVISION.
       MAIN-PARA.
           PERFORM A-PARA THRU C-PARA
           STOP RUN.
       A-PARA.
           CONTINUE.
       C-PARA.
           CONTINUE.
""")
    assert _roles(report, "A-PARA") == [ROLE_PERFORM]
    assert _roles(report, "C-PARA") == [ROLE_PERFORM]


def test_call_arguments_get_the_call_argument_role():
    call = CallStatement(SourceLocation(21, 12))
    call.set_called_program("'SUBPROG'")
    call.using_parameters.append(CallParameter(name="WS-ARG"))

    prog = _make_program(
        [("MAIN-PARA", [call])], data_items=[_data_item("WS-ARG", line=5)]
    )
    report = XrefAnalyzer().analyze(prog)

    assert _roles(report, "WS-ARG") == [ROLE_CALL_ARGUMENT]


def test_call_arguments_from_source():
    report = _analyze_source("""
       IDENTIFICATION DIVISION.
       PROGRAM-ID. CALLER.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-ARG   PIC X(10).
       01  WS-COUNT PIC 9(4).
       PROCEDURE DIVISION.
       MAIN-PARA.
           CALL 'SUBPROG' USING WS-ARG WS-COUNT
           STOP RUN.
""")
    assert _roles(report, "WS-ARG") == [ROLE_CALL_ARGUMENT]
    assert _roles(report, "WS-COUNT") == [ROLE_CALL_ARGUMENT]


def test_file_name_gets_the_file_operation_role():
    report = _analyze_source("""
       IDENTIFICATION DIVISION.
       PROGRAM-ID. FILEOPS.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT CUST-FILE ASSIGN TO 'CUST.DAT'
               ORGANIZATION IS SEQUENTIAL.
       DATA DIVISION.
       FILE SECTION.
       FD  CUST-FILE.
       01  CUST-REC.
           05  CUST-ID PIC X(6).
       WORKING-STORAGE SECTION.
       01  WS-BUF PIC X(6).
       PROCEDURE DIVISION.
       MAIN-PARA.
           OPEN INPUT CUST-FILE
           READ CUST-FILE INTO WS-BUF
           END-READ
           CLOSE CUST-FILE
           STOP RUN.
""")
    entry = report.entry_for("CUST-FILE")
    assert entry is not None
    assert entry.kind == KIND_FILE
    assert entry.definition is not None
    assert [ref.role for ref in entry.references] == [ROLE_FILE_OPERATION] * 3
    assert _roles(report, "WS-BUF") == [ROLE_WRITE]  # READ INTO


def test_file_declared_by_select_and_fd_is_one_entry():
    report = _analyze_source("""
       IDENTIFICATION DIVISION.
       PROGRAM-ID. ONEFILE.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT OUT-FILE ASSIGN TO 'OUT.DAT'
               ORGANIZATION IS SEQUENTIAL.
       DATA DIVISION.
       FILE SECTION.
       FD  OUT-FILE.
       01  OUT-REC PIC X(20).
       WORKING-STORAGE SECTION.
       01  WS-LINE PIC X(20).
       PROCEDURE DIVISION.
       MAIN-PARA.
           OPEN OUTPUT OUT-FILE
           WRITE OUT-REC FROM WS-LINE
           CLOSE OUT-FILE
           STOP RUN.
""")
    files = report.entries_of_kind(KIND_FILE)
    assert [entry.name for entry in files] == ["OUT-FILE"]
    assert not any("declared more than once" in caveat for caveat in report.caveats)
    assert _roles(report, "WS-LINE") == [ROLE_READ]  # WRITE FROM


def test_sql_host_variables_get_the_host_variable_role():
    report = _analyze_source("""
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SQLPROG.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-NAME PIC X(20).
       01  WS-ID   PIC 9(6).
       PROCEDURE DIVISION.
       MAIN-PARA.
           EXEC SQL
               SELECT NAME INTO :WS-NAME FROM CUST WHERE ID = :WS-ID
           END-EXEC
           STOP RUN.
""")
    assert ROLE_HOST_VARIABLE in _roles(report, "WS-NAME")
    assert ROLE_HOST_VARIABLE in _roles(report, "WS-ID")


# ---------------------------------------------------------------------------
# Definitions: kinds, levels, sections
# ---------------------------------------------------------------------------


def test_data_item_entry_carries_level_and_section():
    report = _analyze_source("""
       IDENTIFICATION DIVISION.
       PROGRAM-ID. DEFS.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-GRP.
           05  WS-CHILD PIC X(4).
       LINKAGE SECTION.
       01  LK-PARM PIC X(4).
       PROCEDURE DIVISION USING LK-PARM.
       MAIN-PARA.
           MOVE LK-PARM TO WS-CHILD
           STOP RUN.
""")
    child = report.entry_for("WS-CHILD")
    assert child.kind == KIND_DATA_ITEM
    assert child.level == 5
    assert child.section == "WORKING-STORAGE"

    parm = report.entry_for("LK-PARM")
    assert parm.section == "LINKAGE"
    assert parm.level == 1


def test_condition_name_entry_and_set_to_true():
    report = _analyze_source("""
       IDENTIFICATION DIVISION.
       PROGRAM-ID. COND88.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-FLAG PIC X VALUE 'N'.
           88  WS-DONE VALUE 'Y'.
       PROCEDURE DIVISION.
       MAIN-PARA.
           SET WS-DONE TO TRUE
           IF WS-DONE
               DISPLAY 'DONE'
           END-IF
           STOP RUN.
""")
    entry = report.entry_for("WS-DONE")
    assert entry.kind == KIND_CONDITION_NAME
    assert entry.level == 88
    assert entry.section == "WORKING-STORAGE"
    assert {ref.role for ref in entry.references} == {ROLE_WRITE, ROLE_CONDITION}


def test_sections_and_paragraphs_are_both_declared():
    report = _analyze_source("""
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SECS.
       PROCEDURE DIVISION.
       MAIN-SECTION SECTION.
       MAIN-PARA.
           PERFORM WORK-SECTION
           STOP RUN.
       WORK-SECTION SECTION.
       WORK-PARA.
           CONTINUE.
""")
    assert {e.name for e in report.entries_of_kind(KIND_SECTION)} == {
        "MAIN-SECTION",
        "WORK-SECTION",
    }
    assert {e.name for e in report.entries_of_kind(KIND_PARAGRAPH)} == {
        "MAIN-PARA",
        "WORK-PARA",
    }
    assert _roles(report, "WORK-SECTION") == [ROLE_PERFORM]


def test_entries_sorted_by_kind_then_name():
    report = _analyze_source("""
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SORTED.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-Z PIC X.
       01  WS-A PIC X.
           88  WS-A-ON VALUE 'Y'.
       PROCEDURE DIVISION.
       Z-PARA.
           MOVE WS-A TO WS-Z.
       A-PARA.
           CONTINUE.
""")
    kinds = [entry.kind for entry in report.entries]
    assert kinds == sorted(
        kinds,
        key=lambda k: [
            "data-item",
            "condition-name",
            "file",
            "paragraph",
            "section",
        ].index(k),
    )
    data_names = [e.name for e in report.entries_of_kind(KIND_DATA_ITEM)]
    assert data_names == sorted(data_names)
    para_names = [e.name for e in report.entries_of_kind(KIND_PARAGRAPH)]
    assert para_names == ["A-PARA", "Z-PARA"]


def test_program_without_divisions_produces_an_empty_report():
    prog = CobolProgram("EMPTY", SourceLocation(1, 1))
    report = XrefAnalyzer().analyze(prog)
    assert report.entries == []
    assert report.undefined == []
    assert report.caveats == []
    assert report.total_references == 0


def test_declared_but_never_referenced_item_has_an_empty_entry():
    prog = _make_program(
        [("MAIN-PARA", [])], data_items=[_data_item("WS-UNUSED", line=5)]
    )
    report = XrefAnalyzer().analyze(prog)
    entry = report.entry_for("WS-UNUSED")
    assert entry.reference_count == 0
    assert entry.is_referenced is False
    assert entry.definition.line == 5


def test_entry_for_is_case_insensitive_and_returns_none_for_unknown():
    prog = _make_program(
        [("MAIN-PARA", [_move("WS-A", "WS-B")])],
        data_items=[_data_item("WS-A"), _data_item("WS-B")],
    )
    report = XrefAnalyzer().analyze(prog)
    assert report.entry_for("ws-a") is report.entry_for("WS-A")
    assert report.entry_for("NOPE") is None


# ---------------------------------------------------------------------------
# Undefined symbols
# ---------------------------------------------------------------------------


def test_undefined_data_name_is_reported_not_guessed():
    prog = _make_program(
        [("MAIN-PARA", [_move("WS-A", "WS-MISSING")])],
        data_items=[_data_item("WS-A")],
    )
    report = XrefAnalyzer().analyze(prog)

    assert report.undefined == ["WS-MISSING"]
    entry = report.entry_for("WS-MISSING")
    assert entry.definition is None
    assert entry.kind == KIND_DATA_ITEM
    assert [ref.role for ref in entry.references] == [ROLE_WRITE]
    assert any("inferred from the role" in caveat for caveat in report.caveats)


def test_undefined_paragraph_is_reported_as_a_procedure():
    perform = PerformStatement(SourceLocation(21, 12))
    perform.set_target_paragraph("NO-SUCH-PARA")
    prog = _make_program([("MAIN-PARA", [perform])])
    report = XrefAnalyzer().analyze(prog)

    assert report.undefined == ["NO-SUCH-PARA"]
    assert report.entry_for("NO-SUCH-PARA").kind == KIND_PARAGRAPH


def test_undefined_file_is_reported_as_a_file():
    report = _analyze_source("""
       IDENTIFICATION DIVISION.
       PROGRAM-ID. NOFILE.
       PROCEDURE DIVISION.
       MAIN-PARA.
           OPEN INPUT GHOST-FILE
           STOP RUN.
""")
    assert "GHOST-FILE" in report.undefined
    assert report.entry_for("GHOST-FILE").kind == KIND_FILE


def test_best_effort_extraction_never_invents_an_undefined_symbol():
    """A SEARCH WHEN's raw text may hold keywords/literals -- never undefined."""
    report = _analyze_source("""
       IDENTIFICATION DIVISION.
       PROGRAM-ID. NOGUESS.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-TBL.
           05  WS-ROW OCCURS 5 TIMES INDEXED BY WS-I.
               10  WS-KEY PIC X(4).
       PROCEDURE DIVISION.
       MAIN-PARA.
           SEARCH WS-ROW
               WHEN WS-KEY (WS-I) = 'ABCD' DISPLAY 'FOUND'
           END-SEARCH
           STOP RUN.
""")
    assert report.undefined == []
    assert _roles(report, "WS-KEY") == [ROLE_CONDITION]
    assert _roles(report, "WS-I") == [ROLE_SUBSCRIPT]


# ---------------------------------------------------------------------------
# Caveats
# ---------------------------------------------------------------------------


def test_search_when_emits_a_best_effort_caveat():
    report = _analyze_source("""
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SRCH.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-TBL.
           05  WS-ROW OCCURS 5 TIMES INDEXED BY WS-I.
               10  WS-KEY PIC X(4).
       PROCEDURE DIVISION.
       MAIN-PARA.
           SEARCH WS-ROW
               WHEN WS-KEY (WS-I) = 'ABCD' DISPLAY 'FOUND'
           END-SEARCH
           STOP RUN.
""")
    assert any("SEARCH WHEN" in caveat for caveat in report.caveats)


def test_exec_cics_emits_a_best_effort_caveat_and_a_reference_role():
    report = _analyze_source("""
       IDENTIFICATION DIVISION.
       PROGRAM-ID. CICSP.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-TEXT PIC X(30).
       PROCEDURE DIVISION.
       MAIN-PARA.
           EXEC CICS SEND TEXT FROM(WS-TEXT) END-EXEC
           STOP RUN.
""")
    assert any("EXEC CICS" in caveat for caveat in report.caveats)
    assert _roles(report, "WS-TEXT") == [ROLE_REFERENCE]


def test_unmapped_statement_type_emits_the_generic_sweep_caveat():
    report = _analyze_source("""
       IDENTIFICATION DIVISION.
       PROGRAM-ID. LEGACY.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-A PIC 9(4).
       PROCEDURE DIVISION.
       MAIN-PARA.
           EXHIBIT NAMED WS-A
           STOP RUN.
""")
    assert any("no dedicated role mapping" in caveat for caveat in report.caveats)
    assert _roles(report, "WS-A") == [ROLE_REFERENCE]


def test_intrinsic_function_reference_emits_a_caveat():
    report = _analyze_source("""
       IDENTIFICATION DIVISION.
       PROGRAM-ID. FUNC.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-IN  PIC X(10).
       01  WS-OUT PIC X(10).
       PROCEDURE DIVISION.
       MAIN-PARA.
           MOVE FUNCTION UPPER-CASE(WS-IN) TO WS-OUT
           STOP RUN.
""")
    assert any("intrinsic FUNCTION" in caveat for caveat in report.caveats)
    assert ROLE_READ in _roles(report, "WS-IN")
    # The function's own name is not a data item and must not be invented.
    assert "UPPER-CASE" not in report.undefined


def test_statement_without_a_location_falls_back_to_its_paragraph():
    stmt = _move("WS-A", "WS-B")
    stmt.location = SourceLocation(0, 0)
    prog = _make_program(
        [("MAIN-PARA", [stmt])],
        data_items=[_data_item("WS-A"), _data_item("WS-B")],
    )
    report = XrefAnalyzer().analyze(prog)

    assert report.entry_for("WS-A").references[0].location.line == 10
    assert any("no usable statement location" in caveat for caveat in report.caveats)


def test_duplicate_declaration_emits_a_caveat_and_shares_one_entry():
    prog = _make_program(
        [("MAIN-PARA", [_move("WS-DUP", "WS-DUP")])],
        data_items=[_data_item("WS-DUP", line=5), _data_item("WS-DUP", line=6)],
    )
    report = XrefAnalyzer().analyze(prog)

    entries = [e for e in report.entries if e.name == "WS-DUP"]
    assert len(entries) == 1
    assert entries[0].definition.line == 5
    assert any("declared more than once" in caveat for caveat in report.caveats)


def test_caveats_are_deduplicated():
    report = _analyze_source("""
       IDENTIFICATION DIVISION.
       PROGRAM-ID. DUPCAV.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-IN  PIC X(10).
       01  WS-OUT PIC X(10).
       PROCEDURE DIVISION.
       MAIN-PARA.
           MOVE FUNCTION UPPER-CASE(WS-IN) TO WS-OUT
           MOVE FUNCTION LOWER-CASE(WS-IN) TO WS-OUT
           STOP RUN.
""")
    assert len(report.caveats) == len(set(report.caveats))


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------


def test_reference_to_dict_shape():
    ref = XrefReference(
        location=SourceLocation(12, 4), role=ROLE_WRITE, statement="MoveStatement"
    )
    assert ref.to_dict() == {
        "location": {"line": 12, "column": 4},
        "role": "write",
        "statement": "MoveStatement",
        "context": None,
    }


def test_entry_to_dict_shape():
    entry = XrefEntry(
        name="WS-A",
        kind=KIND_DATA_ITEM,
        definition=SourceLocation(5, 8),
        references=[
            XrefReference(SourceLocation(20, 12), ROLE_READ, "MoveStatement", "MAIN")
        ],
        level=1,
        section="WORKING-STORAGE",
    )
    payload = entry.to_dict()
    assert payload["name"] == "WS-A"
    assert payload["kind"] == "data-item"
    assert payload["definition"] == {"line": 5, "column": 8}
    assert payload["level"] == 1
    assert payload["section"] == "WORKING-STORAGE"
    assert payload["reference_count"] == 1
    assert payload["references"][0]["role"] == "read"
    assert payload["references"][0]["context"] == "MAIN"


def test_entry_to_dict_serializes_a_missing_definition_as_none():
    entry = XrefEntry(name="WS-X", kind=KIND_DATA_ITEM, definition=None)
    assert entry.to_dict()["definition"] is None


def test_report_to_dict_shape():
    prog = _make_program(
        [("MAIN-PARA", [_move("WS-A", "WS-MISSING")])],
        data_items=[_data_item("WS-A"), _data_item("WS-UNUSED")],
    )
    payload = XrefAnalyzer().analyze(prog).to_dict()

    assert set(payload) == {
        "entries",
        "undefined",
        "caveats",
        "duplicate_declarations",
        "summary",
    }
    assert payload["undefined"] == ["WS-MISSING"]
    summary = payload["summary"]
    assert summary["total_symbols"] == 4  # WS-A, WS-UNUSED, MAIN-PARA, WS-MISSING
    assert summary["defined_symbols"] == 3
    assert summary["referenced_symbols"] == 1
    assert summary["unreferenced_symbols"] == 2
    assert summary["undefined_symbols"] == 1
    assert summary["total_references"] == 2
    assert isinstance(payload["entries"], list)
    assert payload["entries"][0]["name"] == "WS-A"


def test_report_is_json_serializable():
    import json

    report = _analyze_source("""
       IDENTIFICATION DIVISION.
       PROGRAM-ID. JSONP.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-A PIC X.
       01  WS-B PIC X.
       PROCEDURE DIVISION.
       MAIN-PARA.
           MOVE WS-A TO WS-B
           STOP RUN.
""")
    text = json.dumps(report.to_dict())
    assert '"role": "write"' in text


def test_every_emitted_role_is_in_the_published_vocabulary():
    report = _analyze_source("""
       IDENTIFICATION DIVISION.
       PROGRAM-ID. ALLROLES.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT IN-FILE ASSIGN TO 'IN.DAT'
               ORGANIZATION IS SEQUENTIAL.
       DATA DIVISION.
       FILE SECTION.
       FD  IN-FILE.
       01  IN-REC PIC X(10).
       WORKING-STORAGE SECTION.
       01  WS-IDX  PIC 9(4).
       01  WS-NAME PIC X(10).
       01  WS-TBL.
           05  WS-ENTRY OCCURS 3 TIMES PIC X(10).
       PROCEDURE DIVISION.
       MAIN-PARA.
           OPEN INPUT IN-FILE
           MOVE WS-ENTRY (WS-IDX) TO WS-NAME
           IF WS-IDX > 1
               PERFORM WORK-PARA
           END-IF
           EXEC SQL SELECT 1 INTO :WS-IDX FROM T END-EXEC
           CALL 'SUB' USING WS-NAME
           CLOSE IN-FILE
           GO TO END-PARA.
       WORK-PARA.
           DISPLAY WS-NAME.
       END-PARA.
           STOP RUN.
""")
    emitted = {ref.role for entry in report.entries for ref in entry.references}
    assert emitted <= XREF_ROLES
    assert {
        ROLE_READ,
        ROLE_WRITE,
        ROLE_CONDITION,
        ROLE_SUBSCRIPT,
        ROLE_PERFORM,
        ROLE_GOTO,
        ROLE_CALL_ARGUMENT,
        ROLE_HOST_VARIABLE,
        ROLE_FILE_OPERATION,
    } <= emitted


def test_analyzer_is_reusable_across_programs():
    analyzer = XrefAnalyzer()
    first = analyzer.analyze(
        _make_program(
            [("MAIN-PARA", [_move("WS-A", "WS-B")])],
            data_items=[_data_item("WS-A"), _data_item("WS-B")],
        )
    )
    second = analyzer.analyze(
        _make_program(
            [("OTHER-PARA", [_move("WS-C", "WS-D")])],
            data_items=[_data_item("WS-C"), _data_item("WS-D")],
        )
    )
    assert {e.name for e in second.entries} == {"WS-C", "WS-D", "OTHER-PARA"}
    assert {e.name for e in first.entries} == {"WS-A", "WS-B", "MAIN-PARA"}


def test_nested_statements_are_cross_referenced_with_their_paragraph():
    report = _analyze_source("""
       IDENTIFICATION DIVISION.
       PROGRAM-ID. NESTED.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-A PIC 9(4).
       01  WS-B PIC 9(4).
       PROCEDURE DIVISION.
       MAIN-PARA.
           IF WS-A > 0
               MOVE WS-A TO WS-B
           ELSE
               MOVE 0 TO WS-B
           END-IF
           STOP RUN.
""")
    contexts = {ref.context for ref in report.entry_for("WS-B").references}
    assert contexts == {"MAIN-PARA"}
    assert _roles(report, "WS-B") == [ROLE_WRITE, ROLE_WRITE]


def test_references_are_sorted_by_source_position():
    report = _analyze_source("""
       IDENTIFICATION DIVISION.
       PROGRAM-ID. ORDERED.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-A PIC 9(4).
       01  WS-B PIC 9(4).
       PROCEDURE DIVISION.
       LAST-PARA.
           DISPLAY WS-A
           MOVE WS-A TO WS-B
           ADD 1 TO WS-A
           STOP RUN.
""")
    lines = [ref.location.line for ref in report.entry_for("WS-A").references]
    assert lines == sorted(lines)


def test_condition_name_declaration_from_a_hand_built_ast():
    item = _data_item("WS-FLAG", line=5)
    condition = ConditionNameItem("WS-DONE", SourceLocation(6, 12))
    condition.add_value("'Y'")
    item.add_child(condition)

    prog = _make_program([("MAIN-PARA", [])], data_items=[item])
    report = XrefAnalyzer().analyze(prog)

    entry = report.entry_for("WS-DONE")
    assert entry.kind == KIND_CONDITION_NAME
    assert entry.level == 88
    assert entry.definition.line == 6
    assert entry.is_referenced is False


# ---------------------------------------------------------------------------
# Wider statement coverage
# ---------------------------------------------------------------------------

_KITCHEN_SINK = """
       IDENTIFICATION DIVISION.
       PROGRAM-ID. PROBE.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT WORK-FILE ASSIGN TO 'W.DAT'
               ORGANIZATION IS SEQUENTIAL.
           SELECT SORT-FILE ASSIGN TO 'S.DAT'.
           SELECT OUT-FILE ASSIGN TO 'O.DAT'
               ORGANIZATION IS INDEXED
               ACCESS MODE IS DYNAMIC
               RECORD KEY IS OUT-KEY.
       DATA DIVISION.
       FILE SECTION.
       FD  WORK-FILE.
       01  WORK-REC PIC X(20).
       SD  SORT-FILE.
       01  SORT-REC.
           05  SORT-KEY PIC X(4).
       FD  OUT-FILE.
       01  OUT-REC.
           05  OUT-KEY  PIC X(4).
       WORKING-STORAGE SECTION.
       01  WS-A     PIC 9(4).
       01  WS-B     PIC 9(4).
       01  WS-Q     PIC 9(4).
       01  WS-REM   PIC 9(4).
       01  WS-TEXT  PIC X(30).
       01  WS-DOC   PIC X(99).
       01  WS-N     PIC 9(4).
       01  WS-CODE  PIC X.
       PROCEDURE DIVISION.
       MAIN-PARA.
           DIVIDE WS-A BY WS-B GIVING WS-Q REMAINDER WS-REM
           SET WS-A TO 1
           INITIALIZE WS-TEXT REPLACING ALPHANUMERIC BY WS-CODE
           INSPECT WS-TEXT REPLACING ALL 'A' BY 'B'
           INSPECT WS-TEXT CONVERTING 'AB' TO 'CD'
           XML GENERATE WS-DOC FROM WS-TEXT
           SORT SORT-FILE ON ASCENDING KEY SORT-KEY
               INPUT PROCEDURE IS IN-PARA
               OUTPUT PROCEDURE IS OUT-PARA
           MERGE SORT-FILE ON ASCENDING KEY SORT-KEY
               USING WORK-FILE OUT-FILE
               GIVING WORK-FILE
           PERFORM WORK-PARA WS-N TIMES
           GO TO IN-PARA OUT-PARA DEPENDING ON WS-A
           REWRITE OUT-REC FROM WS-TEXT
           DELETE OUT-FILE RECORD
           START OUT-FILE KEY IS EQUAL TO OUT-KEY
           END-START
           UNLOCK OUT-FILE
           EXEC DLI GU SEGMENT(EMPLOYEE) INTO(WS-TEXT) END-EXEC
           EVALUATE TRUE
               WHEN WS-A > 5 MOVE 1 TO WS-B
           END-EVALUATE
           EVALUATE WS-CODE
               WHEN 'A' THRU 'M' MOVE 1 TO WS-B
           END-EVALUATE
           ALTER IN-PARA TO PROCEED TO OUT-PARA
           STOP RUN.
       WORK-PARA.
           ENTRY 'ALT-ENTRY' USING WS-TEXT.
       IN-PARA.
           CALL WS-TEXT USING WS-A
           GOBACK.
       OUT-PARA.
           CONTINUE.
"""


def test_divide_giving_and_remainder_are_writes():
    report = _analyze_source(_KITCHEN_SINK)
    assert ROLE_WRITE in _roles(report, "WS-Q")
    assert ROLE_WRITE in _roles(report, "WS-REM")
    assert ROLE_READ in _roles(report, "WS-A")


def test_initialize_and_inspect_replacing_roles():
    report = _analyze_source(_KITCHEN_SINK)
    text_roles = _roles(report, "WS-TEXT")
    # INITIALIZE target, INSPECT REPLACING target and INSPECT CONVERTING
    # target are all receiving fields.
    assert text_roles.count(ROLE_WRITE) >= 3
    assert ROLE_READ in _roles(report, "WS-CODE")  # REPLACING ... BY WS-CODE


def test_xml_generate_target_is_write_and_from_item_is_read():
    report = _analyze_source(_KITCHEN_SINK)
    assert _roles(report, "WS-DOC") == [ROLE_WRITE]
    assert ROLE_READ in _roles(report, "WS-TEXT")


def test_sort_and_merge_files_keys_and_procedures():
    report = _analyze_source(_KITCHEN_SINK)
    assert _roles(report, "SORT-KEY") == [ROLE_READ, ROLE_READ]
    assert _roles(report, "SORT-FILE") == [ROLE_FILE_OPERATION, ROLE_FILE_OPERATION]
    assert ROLE_FILE_OPERATION in _roles(report, "WORK-FILE")
    assert ROLE_PERFORM in _roles(report, "IN-PARA")
    assert ROLE_PERFORM in _roles(report, "OUT-PARA")


def test_perform_times_with_a_variable_count_is_a_read():
    report = _analyze_source(_KITCHEN_SINK)
    assert _roles(report, "WS-N") == [ROLE_READ]
    assert ROLE_PERFORM in _roles(report, "WORK-PARA")


def test_go_to_depending_on_marks_targets_and_the_selector():
    report = _analyze_source(_KITCHEN_SINK)
    assert ROLE_GOTO in _roles(report, "IN-PARA")
    assert ROLE_GOTO in _roles(report, "OUT-PARA")
    assert ROLE_READ in _roles(report, "WS-A")


def test_alter_names_both_procedures():
    report = _analyze_source(_KITCHEN_SINK)
    in_para = report.entry_for("IN-PARA")
    assert sum(1 for ref in in_para.references if ref.role == ROLE_GOTO) == 2


def test_rewrite_delete_start_and_unlock_file_operations():
    report = _analyze_source(_KITCHEN_SINK)
    out_file = _roles(report, "OUT-FILE")
    # MERGE USING, DELETE, START, UNLOCK
    assert out_file.count(ROLE_FILE_OPERATION) == 4
    assert _roles(report, "OUT-REC") == [ROLE_READ]  # REWRITE source record
    assert _roles(report, "OUT-KEY") == [ROLE_READ]  # START KEY IS


def test_entry_using_parameters_are_call_arguments():
    report = _analyze_source(_KITCHEN_SINK)
    statements = {ref.statement for ref in report.entry_for("WS-TEXT").references}
    assert "EntryStatement" in statements
    assert ROLE_CALL_ARGUMENT in _roles(report, "WS-TEXT")


def test_dynamic_call_program_name_is_a_read():
    report = _analyze_source(_KITCHEN_SINK)
    call_refs = [
        ref
        for ref in report.entry_for("WS-TEXT").references
        if ref.statement == "CallStatement"
    ]
    assert [ref.role for ref in call_refs] == [ROLE_READ]


def test_exec_dli_argument_is_a_reference_not_a_subscript():
    report = _analyze_source(_KITCHEN_SINK)
    dli_refs = [
        ref
        for ref in report.entry_for("WS-TEXT").references
        if ref.statement == "ExecImsStatement"
    ]
    assert [ref.role for ref in dli_refs] == [ROLE_REFERENCE]
    assert any("EXEC IMS/DLI" in caveat for caveat in report.caveats)


def test_evaluate_range_selector_does_not_invent_symbols():
    report = _analyze_source(_KITCHEN_SINK)
    assert report.undefined == []


def test_perform_varying_variable_is_written_and_bounds_are_read():
    report = _analyze_source("""
       IDENTIFICATION DIVISION.
       PROGRAM-ID. VARY.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-I     PIC 9(4).
       01  WS-J     PIC 9(4).
       01  WS-STEP  PIC 9(4).
       01  WS-MAX   PIC 9(4).
       PROCEDURE DIVISION.
       MAIN-PARA.
           PERFORM VARYING WS-I FROM 1 BY WS-STEP UNTIL WS-I > WS-MAX
               AFTER WS-J FROM 1 BY 1 UNTIL WS-J > 3
               CONTINUE
           END-PERFORM
           STOP RUN.
""")
    assert ROLE_WRITE in _roles(report, "WS-I")
    assert ROLE_CONDITION in _roles(report, "WS-I")
    assert _roles(report, "WS-STEP") == [ROLE_READ]
    assert _roles(report, "WS-MAX") == [ROLE_CONDITION]
    assert ROLE_WRITE in _roles(report, "WS-J")


def test_set_with_several_groups_writes_every_target():
    report = _analyze_source("""
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SETG.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-P1 USAGE IS POINTER.
       01  WS-P2 USAGE IS POINTER.
       PROCEDURE DIVISION.
       MAIN-PARA.
           SET WS-P1 TO NULL
           SET WS-P2 TO NULL
           STOP RUN.
""")
    assert _roles(report, "WS-P1") == [ROLE_WRITE]
    assert _roles(report, "WS-P2") == [ROLE_WRITE]


def test_call_returning_target_is_a_write():
    call = CallStatement(SourceLocation(21, 12))
    call.set_called_program("'SUBPROG'")
    call.set_returning_parameter("WS-RC")
    prog = _make_program([("MAIN-PARA", [call])], data_items=[_data_item("WS-RC")])
    report = XrefAnalyzer().analyze(prog)
    assert _roles(report, "WS-RC") == [ROLE_WRITE]


def test_data_division_exec_sql_is_cross_referenced_without_a_context():
    report = _analyze_source("""
       IDENTIFICATION DIVISION.
       PROGRAM-ID. DCLP.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
           EXEC SQL BEGIN DECLARE SECTION END-EXEC.
       01  WS-ID PIC 9(6).
           EXEC SQL END DECLARE SECTION END-EXEC.
       PROCEDURE DIVISION.
       MAIN-PARA.
           EXEC SQL SELECT ID INTO :WS-ID FROM T END-EXEC
           STOP RUN.
""")
    entry = report.entry_for("WS-ID")
    assert entry is not None
    assert ROLE_HOST_VARIABLE in [ref.role for ref in entry.references]


def test_synthetic_period_paragraph_is_not_declared():
    prog = _make_program([(".", []), ("REAL-PARA", [])])
    report = XrefAnalyzer().analyze(prog)
    assert [e.name for e in report.entries_of_kind(KIND_PARAGRAPH)] == ["REAL-PARA"]


def test_qualified_reference_credits_both_names():
    report = _analyze_source("""
       IDENTIFICATION DIVISION.
       PROGRAM-ID. QUAL.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-GRP.
           05  WS-FLD PIC X(4).
       01  WS-OUT PIC X(4).
       PROCEDURE DIVISION.
       MAIN-PARA.
           MOVE WS-FLD OF WS-GRP TO WS-OUT
           STOP RUN.
""")
    assert _roles(report, "WS-FLD") == [ROLE_READ]
    assert _roles(report, "WS-GRP") == [ROLE_READ]


# ---------------------------------------------------------------------------
# Operand partitioning helper
# ---------------------------------------------------------------------------


def test_partition_operand_shapes():
    assert _partition_operand("") == (set(), set(), True)
    assert _partition_operand("WS-A") == ({"WS-A"}, set(), True)
    assert _partition_operand("WS-TBL (WS-IDX)") == ({"WS-TBL"}, {"WS-IDX"}, True)
    # Nested subscripts: both index names are subscripts.
    base, subs, exact = _partition_operand("WS-TBL (WS-OUTER (WS-INNER))")
    assert base == {"WS-TBL"}
    assert subs == {"WS-OUTER", "WS-INNER"}
    assert exact is True
    # Reference modification is not a subscript.
    assert _partition_operand("WS-TEXT (WS-OFF:5)") == (
        {"WS-TEXT", "WS-OFF"},
        set(),
        True,
    )
    # An intrinsic function reference is inexact and never a subscript.
    base, subs, exact = _partition_operand("FUNCTION UPPER-CASE(WS-X)")
    assert "WS-X" in base
    assert subs == set()
    assert exact is False


# ---------------------------------------------------------------------------
# Remaining statement shapes
# ---------------------------------------------------------------------------

_IO_AND_STRINGS = """
       IDENTIFICATION DIVISION.
       PROGRAM-ID. PROBE2.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT IX-FILE ASSIGN TO 'I.DAT'
               ORGANIZATION IS INDEXED
               ACCESS MODE IS RANDOM
               RECORD KEY IS IX-KEY.
       DATA DIVISION.
       FILE SECTION.
       FD  IX-FILE.
       01  IX-REC.
           05  IX-KEY PIC X(4).
       WORKING-STORAGE SECTION.
       01  WS-TEXT  PIC X(30).
       01  WS-P1    PIC X(10).
       01  WS-C1    PIC 9(4).
       01  WS-PTR   PIC 9(4).
       01  WS-TALLY PIC 9(4).
       01  WS-DOC   PIC X(99).
       01  WS-IDX   PIC 9(4).
       01  WS-TBL.
           05  WS-ROW OCCURS 5 TIMES.
               10 WS-K PIC X(4).
       PROCEDURE DIVISION.
       MAIN-PARA.
           READ IX-FILE RECORD INTO WS-TEXT KEY IS IX-KEY
           END-READ
           UNSTRING WS-TEXT DELIMITED BY ',' INTO WS-P1
               COUNT IN WS-C1 WITH POINTER WS-PTR TALLYING IN WS-TALLY
           END-UNSTRING
           XML PARSE WS-DOC PROCESSING PROCEDURE IS HANDLER-PARA
           SEARCH WS-ROW VARYING WS-IDX
               AT END CONTINUE
           END-SEARCH
           STOP RUN.
       HANDLER-PARA.
           CONTINUE.
"""


def test_read_into_and_key_roles():
    report = _analyze_source(_IO_AND_STRINGS)
    assert _roles(report, "WS-TEXT")[0] == ROLE_WRITE  # READ ... INTO
    assert _roles(report, "IX-KEY") == [ROLE_READ]  # READ ... KEY IS
    assert _roles(report, "IX-FILE") == [ROLE_FILE_OPERATION]


def test_unstring_count_pointer_and_tallying_are_writes():
    report = _analyze_source(_IO_AND_STRINGS)
    assert _roles(report, "WS-P1") == [ROLE_WRITE]
    assert _roles(report, "WS-C1") == [ROLE_WRITE]
    assert _roles(report, "WS-PTR") == [ROLE_WRITE]
    assert _roles(report, "WS-TALLY") == [ROLE_WRITE]


def test_xml_parse_reads_its_document_and_performs_its_handler():
    report = _analyze_source(_IO_AND_STRINGS)
    assert _roles(report, "WS-DOC") == [ROLE_READ]
    assert _roles(report, "HANDLER-PARA") == [ROLE_PERFORM]


def test_search_varying_index_is_written():
    report = _analyze_source(_IO_AND_STRINGS)
    assert _roles(report, "WS-IDX") == [ROLE_WRITE]
    assert _roles(report, "WS-ROW") == [ROLE_READ]


def test_truncated_operand_is_dropped_with_a_caveat():
    """The UNSTRING parser can hand back a bare ``"WS-"`` for DELIMITER IN.

    A hyphen-terminated fragment is not a COBOL word, so it must not be
    reported as an undeclared symbol -- it is dropped and counted instead.
    """
    report = _analyze_source("""
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TRUNC.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-TEXT PIC X(30).
       01  WS-P1   PIC X(10).
       01  WS-D1   PIC X.
       PROCEDURE DIVISION.
       MAIN-PARA.
           UNSTRING WS-TEXT DELIMITED BY ',' INTO WS-P1 DELIMITER IN WS-D1
           END-UNSTRING
           STOP RUN.
""")
    assert report.undefined == []
    assert any("truncated operand" in caveat for caveat in report.caveats)


def test_set_with_multiple_groups_from_a_hand_built_statement():
    stmt = SetStatement(SourceLocation(21, 12))
    stmt.set_set_type("TO")
    stmt.add_target("WS-A")
    stmt.set_value("1")
    stmt.add_group(["WS-B"], "TO", "WS-C")

    prog = _make_program(
        [("MAIN-PARA", [stmt])],
        data_items=[_data_item("WS-A"), _data_item("WS-B"), _data_item("WS-C")],
    )
    report = XrefAnalyzer().analyze(prog)
    assert _roles(report, "WS-A") == [ROLE_WRITE]
    assert _roles(report, "WS-B") == [ROLE_WRITE]
    assert _roles(report, "WS-C") == [ROLE_READ]


def test_evaluate_identifier_and_unknown_selectors():
    when_clause = WhenClause(
        [
            {"type": "Identifier", "value": "WS-A"},
            {"type": "SomethingNew", "value": "WS-B"},
        ],
        SourceLocation(21, 12),
    )
    stmt = EvaluateStatement(SourceLocation(20, 12))
    stmt.add_subject("WS-CODE")
    stmt.add_when_clause(when_clause)

    prog = _make_program(
        [("MAIN-PARA", [stmt])],
        data_items=[_data_item("WS-A"), _data_item("WS-B"), _data_item("WS-CODE")],
    )
    report = XrefAnalyzer().analyze(prog)
    assert _roles(report, "WS-A") == [ROLE_CONDITION]
    assert _roles(report, "WS-CODE") == [ROLE_CONDITION]
    # An unrecognized selector shape contributes nothing rather than a guess.
    assert report.entry_for("WS-B").is_referenced is False


def test_perform_varying_clause_with_non_string_values():
    stmt = PerformStatement(SourceLocation(21, 12))
    stmt.set_target_paragraph("WORK-PARA")
    stmt.varying_clause = {
        "variable": "WS-I",
        "from_value": 1,  # an int, not operand text
        "by_value": None,
        "until_condition": None,
    }
    prog = _make_program(
        [("MAIN-PARA", [stmt]), ("WORK-PARA", [])],
        data_items=[_data_item("WS-I")],
    )
    report = XrefAnalyzer().analyze(prog)
    assert _roles(report, "WS-I") == [ROLE_WRITE]


def test_statement_outside_any_paragraph_keeps_its_own_location():
    stmt = _move("WS-A", "WS-B")
    stmt.location = SourceLocation(0, 0)

    prog = _make_program([("MAIN-PARA", [])], data_items=[_data_item("WS-A")])
    data_div = prog.get_division("DATA")
    data_div.add_child(stmt)

    report = XrefAnalyzer().analyze(prog)
    ref = report.entry_for("WS-A").references[0]
    assert ref.context is None
    assert ref.location.line == 0
    # No paragraph to fall back to, so no fallback caveat either.
    assert not any("no usable statement location" in c for c in report.caveats)


def test_read_record_name_is_a_write():
    stmt = IOReadStatement(SourceLocation(21, 12))
    stmt.set_file_name("IN-FILE")
    stmt.set_record_name("IN-REC")

    prog = _make_program([("MAIN-PARA", [stmt])], data_items=[_data_item("IN-REC")])
    report = XrefAnalyzer().analyze(prog)
    assert _roles(report, "IN-REC") == [ROLE_WRITE]
    # No SELECT/FD in this hand-built AST, so the file is undefined but named.
    assert report.entry_for("IN-FILE").kind == KIND_FILE


def test_xml_processing_procedure_thru_range():
    stmt = XmlJsonStatement("XML", "PARSE", SourceLocation(21, 12))
    stmt.set_primary_operand("WS-DOC")
    stmt.processing_procedure = "A-PARA"
    stmt.processing_procedure_thru = "C-PARA"

    prog = _make_program(
        [("MAIN-PARA", [stmt]), ("A-PARA", []), ("C-PARA", [])],
        data_items=[_data_item("WS-DOC")],
    )
    report = XrefAnalyzer().analyze(prog)
    assert _roles(report, "A-PARA") == [ROLE_PERFORM]
    assert _roles(report, "C-PARA") == [ROLE_PERFORM]


def test_clause_value_of_none_contributes_nothing():
    stmt = InitializeStatement(SourceLocation(21, 12))
    stmt.add_target("WS-A")
    stmt.replacing_clauses.append({"category": "ALPHANUMERIC", "by_value": None})

    prog = _make_program([("MAIN-PARA", [stmt])], data_items=[_data_item("WS-A")])
    report = XrefAnalyzer().analyze(prog)
    assert _roles(report, "WS-A") == [ROLE_WRITE]
    assert report.undefined == []


def test_reserved_and_intrinsic_names_are_never_reported_undefined():
    report = _analyze_source("""
       IDENTIFICATION DIVISION.
       PROGRAM-ID. RESW.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-A PIC X(21).
       PROCEDURE DIVISION.
       MAIN-PARA.
           MOVE FUNCTION CURRENT-DATE TO WS-A
           STOP RUN.
""")
    assert report.undefined == []
    assert _roles(report, "WS-A") == [ROLE_WRITE]
    assert any(
        "reserved word, an intrinsic function name" in caveat
        for caveat in report.caveats
    )


# ---------------------------------------------------------------------------
# Review follow-ups (PR #212)
# ---------------------------------------------------------------------------


def test_digit_led_procedure_names_are_credited_verbatim():
    """``PERFORM 1000-INIT THRU 1000-EXIT`` must credit those paragraphs, not
    split them into ``INIT``/``EXIT`` (the dominant mainframe convention)."""
    report = _analyze_source("""       IDENTIFICATION DIVISION.
       PROGRAM-ID. DIGITS.
       PROCEDURE DIVISION.
       0000-MAIN.
           PERFORM 1000-INIT THRU 1000-EXIT
           GO TO 2000-LOOP.
       1000-INIT.
           CONTINUE.
       1000-EXIT.
           EXIT.
       2000-LOOP.
           STOP RUN.
""")
    by_name = {entry.name: entry for entry in report.entries}
    assert by_name["1000-INIT"].reference_count == 1
    assert by_name["1000-EXIT"].reference_count == 1
    assert by_name["2000-LOOP"].reference_count == 1
    assert report.undefined == []


def test_contained_program_references_never_read_as_the_outer_units_undefined():
    report = _analyze_source("""       IDENTIFICATION DIVISION.
       PROGRAM-ID. OUTER.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-OUT PIC X.
       PROCEDURE DIVISION.
       MAIN.
           MOVE 'A' TO WS-OUT
           STOP RUN.
       IDENTIFICATION DIVISION.
       PROGRAM-ID. INNER.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-IN PIC X.
       PROCEDURE DIVISION.
       INNER-MAIN.
           MOVE 'B' TO WS-IN
           GOBACK.
       END PROGRAM INNER.
       END PROGRAM OUTER.
""")
    assert report.undefined == []
    assert {entry.name for entry in report.entries} >= {"WS-OUT", "MAIN"}
    assert "WS-IN" not in {entry.name for entry in report.entries}


def test_string_literal_words_are_not_undefined_symbols():
    report = _analyze_source("""       IDENTIFICATION DIVISION.
       PROGRAM-ID. STRLIT.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-OUT PIC X(40).
       PROCEDURE DIVISION.
       MAIN.
           STRING 'VERY LONG TEXT' DELIMITED BY SIZE INTO WS-OUT
           STOP RUN.
""")
    assert report.undefined == []


def test_special_registers_are_excluded_from_undefined_with_a_caveat():
    report = _analyze_source("""       IDENTIFICATION DIVISION.
       PROGRAM-ID. REGS.
       PROCEDURE DIVISION.
       MAIN.
           MOVE 8 TO RETURN-CODE
           STOP RUN.
""")
    assert "RETURN-CODE" not in report.undefined
    assert any("RETURN-CODE" in caveat for caveat in report.caveats)


def test_duplicate_declarations_are_reported_on_the_report():
    report = _analyze_source("""       IDENTIFICATION DIVISION.
       PROGRAM-ID. DUPS.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-REC.
          05 CUST-ID PIC X(5).
       LINKAGE SECTION.
       01 LK-REC.
          05 CUST-ID PIC X(5).
       PROCEDURE DIVISION USING LK-REC.
       MAIN.
           MOVE 'A' TO CUST-ID OF WS-REC
           GOBACK.
""")
    assert report.duplicate_declarations == ["CUST-ID"]
    assert "duplicate_declarations" in report.to_dict()
