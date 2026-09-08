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
from cobolparser.models.statements.control import GoStatement, PerformStatement
from cobolparser.models.statements.data import MoveStatement
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

    assert set(payload) == {"entries", "undefined", "caveats", "summary"}
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
