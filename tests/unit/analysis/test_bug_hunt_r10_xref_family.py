"""Bug hunt round 10: xref, program signatures, unused variables, diff,
SQL/CICS lint and complexity.

Each test reproduces one defect found by feeding a small, valid COBOL
program through the public analyzer API.
"""

from __future__ import annotations

from cobolparser import parse_cobol
from cobolparser.analysis.ast_diff import ProgramDiffer
from cobolparser.analysis.complexity import ComplexityAnalyzer
from cobolparser.analysis.program_signature import ProgramSignatureExtractor
from cobolparser.analysis.sql_cics_lint import (
    KIND_NO_SQLCODE_CHECK,
    SqlCicsAnalyzer,
)
from cobolparser.analysis.unused_variables import UnusedVariableAnalyzer
from cobolparser.analysis.xref import XrefAnalyzer


def _parse(source: str):
    result = parse_cobol(source)
    assert not result.errors, result.errors
    return result.ast


def _program(procedure: str, working_storage: str = "") -> str:
    return (
        "       IDENTIFICATION DIVISION.\n"
        "       PROGRAM-ID. T1.\n"
        "       DATA DIVISION.\n"
        "       WORKING-STORAGE SECTION.\n"
        f"{working_storage}"
        "       PROCEDURE DIVISION.\n"
        f"{procedure}"
    )


# ---------------------------------------------------------------------------
# xref
# ---------------------------------------------------------------------------


def test_xref_indexed_by_name_is_not_a_duplicate_declaration():
    ast = _parse(
        _program(
            "       P1.\n"
            "           SET IX TO 1\n"
            "           DISPLAY WS-T (IX)\n"
            "           STOP RUN.\n",
            "       01 WS-TAB.\n" "          05 WS-T PIC 9 OCCURS 5 INDEXED BY IX.\n",
        )
    )
    report = XrefAnalyzer().analyze(ast)
    assert report.duplicate_declarations == []
    assert not any("declared more than once" in c for c in report.caveats)
    assert report.entry_for("IX") is not None


_FILE_PROGRAM = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. T1.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT IN-FILE ASSIGN TO INDD
               FILE STATUS IS WS-FS.
       DATA DIVISION.
       FILE SECTION.
       FD IN-FILE RECORD VARYING FROM 1 TO 80 DEPENDING ON WS-LEN.
       01 IN-REC PIC X(80).
       WORKING-STORAGE SECTION.
       01 WS-FS PIC XX.
          88 WS-FS-OK VALUE '00'.
       01 WS-LEN PIC 9(4).
       01 WS-N PIC 9(4).
       01 WS-TAB.
          05 WS-E PIC X OCCURS 1 TO 10 DEPENDING ON WS-N.
       PROCEDURE DIVISION.
       P1.
           OPEN INPUT IN-FILE
           IF WS-FS-OK DISPLAY WS-TAB END-IF
           STOP RUN.
"""


def test_xref_records_select_and_data_division_references():
    """FILE STATUS, FD DEPENDING ON and OCCURS DEPENDING ON items are used
    (UnusedVariableAnalyzer says so); xref listed them unreferenced."""
    ast = _parse(_FILE_PROGRAM)
    report = XrefAnalyzer().analyze(ast)
    for name in ("WS-FS", "WS-LEN", "WS-N"):
        entry = report.entry_for(name)
        assert entry is not None
        assert entry.is_referenced, name
    unused = {u.name for u in UnusedVariableAnalyzer().analyze(ast).unused_items}
    assert not unused & {"WS-FS", "WS-LEN", "WS-N"}
    assert report.undefined == []


# ---------------------------------------------------------------------------
# program signatures
# ---------------------------------------------------------------------------

_SUBPROGRAM = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. SUBP.
       DATA DIVISION.
       LINKAGE SECTION.
       01 LK-REC.
          05 LK-F1 PIC X(5).
          05 LK-F2 PIC 9(3).
       01 LK-STAT PIC X.
          88 LK-OK VALUE 'Y'.
       01 LK-FLAG PIC X.
          88 LK-ON VALUE 'Y'.
       PROCEDURE DIVISION USING LK-REC LK-STAT LK-FLAG.
       P1.
           DISPLAY LK-REC
           MOVE 1 TO LK-F2
           SET LK-OK TO TRUE
           IF LK-ON DISPLAY 'ON' END-IF
           GOBACK.
"""


def test_signature_group_read_whole_and_written_by_field_is_input_output():
    signature = ProgramSignatureExtractor().analyze(_parse(_SUBPROGRAM))
    assert signature.primary is not None
    directions = {p.name: p.direction for p in signature.primary.parameters}
    # Was "input": the whole-group DISPLAY hid the write into LK-F2.
    assert directions["LK-REC"] == "input-output"


def test_signature_parameter_used_only_through_level_88():
    signature = ProgramSignatureExtractor().analyze(_parse(_SUBPROGRAM))
    assert signature.primary is not None
    directions = {p.name: p.direction for p in signature.primary.parameters}
    # Was "unknown ... unreferenced in the PROCEDURE DIVISION".
    assert directions["LK-STAT"] == "output"  # SET LK-OK TO TRUE
    assert directions["LK-FLAG"] == "input"  # IF LK-ON
    assert not any("unreferenced" in note for note in signature.unchecked)


# ---------------------------------------------------------------------------
# unused variables
# ---------------------------------------------------------------------------

_NESTED = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. OUTER.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-A PIC X.
       01 WS-B PIC X.
       01 WS-G PIC X IS GLOBAL.
       PROCEDURE DIVISION.
       P1.
           DISPLAY WS-A
           CALL 'INNER'
           STOP RUN.
       IDENTIFICATION DIVISION.
       PROGRAM-ID. INNER.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-B PIC X.
       PROCEDURE DIVISION.
       IP.
           DISPLAY WS-B
           DISPLAY WS-G
           GOBACK.
       END PROGRAM INNER.
       END PROGRAM OUTER.
"""


def test_unused_variables_ignores_contained_program_references():
    """INNER's WS-B is its own; OUTER's WS-B is unused. OUTER's GLOBAL
    WS-G is visible to INNER, so INNER's reference still counts."""
    ast = _parse(_NESTED)
    unused = {u.name for u in UnusedVariableAnalyzer().analyze(ast).unused_items}
    assert unused == {"WS-B"}
    inner = ast.contained_programs[0]
    assert UnusedVariableAnalyzer().analyze(inner).unused_items == []


# ---------------------------------------------------------------------------
# ast diff
# ---------------------------------------------------------------------------

_DIFF_WS = (
    "       01 WS-A PIC X(20).\n"
    "       01 WS-TAB.\n"
    "          05 WS-T PIC 9 OCCURS 5 ASCENDING KEY WS-T INDEXED BY IX.\n"
)


def _diff_statement(old: str, new: str):
    def build(statement: str):
        return _parse(
            _program(
                f"       MAIN-PARA.\n           {statement}\n           STOP RUN.\n",
                _DIFF_WS,
            )
        )

    return ProgramDiffer().diff(build(old), build(new))


def test_diff_sees_inspect_converting_before_after_change():
    report = _diff_statement(
        "INSPECT WS-A CONVERTING 'abc' TO 'ABC' BEFORE INITIAL '.'",
        "INSPECT WS-A CONVERTING 'abc' TO 'ABC' AFTER INITIAL '.'",
    )
    assert report.has_changes


def test_diff_sees_search_becoming_search_all():
    report = _diff_statement(
        "SEARCH WS-T WHEN WS-T (IX) = 1 DISPLAY 'F' END-SEARCH",
        "SEARCH ALL WS-T WHEN WS-T (IX) = 1 DISPLAY 'F' END-SEARCH",
    )
    assert report.has_changes


# ---------------------------------------------------------------------------
# SQL / CICS lint
# ---------------------------------------------------------------------------


def test_sqlcode_check_inside_perform_thru_range_is_seen():
    ast = _parse(
        _program(
            "       MAIN-PARA.\n"
            "           EXEC SQL UPDATE T1 SET C1 = 1 END-EXEC\n"
            "           PERFORM 9000-START THRU 9000-EXIT\n"
            "           STOP RUN.\n"
            "       9000-START.\n"
            "           DISPLAY 'CHECKING'.\n"
            "       9000-CHECK.\n"
            "           IF SQLCODE NOT = 0 DISPLAY 'ERR' END-IF.\n"
            "       9000-EXIT.\n"
            "           EXIT.\n",
            "       01 WS-A PIC X(10).\n           EXEC SQL INCLUDE SQLCA END-EXEC.\n",
        )
    )
    report = SqlCicsAnalyzer().analyze(ast)
    assert report.violations_of_kind(KIND_NO_SQLCODE_CHECK) == []


def test_sqlcode_check_outside_perform_thru_range_still_missing():
    ast = _parse(
        _program(
            "       MAIN-PARA.\n"
            "           EXEC SQL UPDATE T1 SET C1 = 1 END-EXEC\n"
            "           PERFORM 9000-START THRU 9000-EXIT\n"
            "           STOP RUN.\n"
            "       9000-START.\n"
            "           DISPLAY 'CHECKING'.\n"
            "       9000-EXIT.\n"
            "           EXIT.\n"
            "       9100-CHECK.\n"
            "           IF SQLCODE NOT = 0 DISPLAY 'ERR' END-IF.\n",
            "       01 WS-A PIC X(10).\n           EXEC SQL INCLUDE SQLCA END-EXEC.\n",
        )
    )
    report = SqlCicsAnalyzer().analyze(ast)
    assert len(report.violations_of_kind(KIND_NO_SQLCODE_CHECK)) == 1


# ---------------------------------------------------------------------------
# complexity
# ---------------------------------------------------------------------------

_COMPLEXITY_WS = (
    "       01 WS-A PIC 9.\n"
    "       01 WS-B PIC 9.\n"
    "       01 WS-F PIC X.\n"
    "          88 WS-FLAG VALUE 'Y'.\n"
    "       01 WS-TAB.\n"
    "          05 WS-T PIC 9 OCCURS 5 INDEXED BY IX.\n"
)


def _extended(body: str) -> int:
    ast = _parse(
        _program(f"       MAIN-PARA.\n{body}           STOP RUN.\n", _COMPLEXITY_WS)
    )
    return ComplexityAnalyzer().analyze(ast).procedures[0].extended_complexity


def test_extended_complexity_counts_evaluate_true_when_and_or():
    body = (
        "           EVALUATE TRUE\n"
        "             WHEN WS-A = 1 AND WS-B = 2 DISPLAY 'A'\n"
        "           END-EVALUATE\n"
    )
    assert _extended(body) == 3  # 1 + one WHEN + one AND


def test_extended_complexity_counts_search_when_and_or():
    body = (
        "           SEARCH WS-T WHEN WS-T (IX) = 1 AND WS-A = 2 DISPLAY 'F'\n"
        "           END-SEARCH\n"
    )
    assert _extended(body) == 3


def test_extended_complexity_ignores_quoted_and_or_in_search_condition():
    body = (
        "           SEARCH WS-T WHEN WS-T (IX) = 'A OR B' DISPLAY 'F'\n"
        "           END-SEARCH\n"
    )
    assert _extended(body) == 2


def test_extended_complexity_does_not_count_unary_not():
    body = "           IF NOT WS-FLAG DISPLAY 'X' END-IF\n"
    assert _extended(body) == 2
