"""Dynamic program references resolved through VALUE-built tables and
EXEC CICS LINK / XCTL / LOAD ``PROGRAM(data-name)``.

The CardDemo menu pattern (COMEN01C + COMEN02Y): a group of FILLERs with
VALUE clauses holds the program names, a ``REDEFINES`` lays an OCCURS table
over it, and ``EXEC CICS XCTL PROGRAM(CDEMO-MENU-OPT-PGMNAME(WS-OPTION))``
transfers to whichever entry was picked.
"""

from __future__ import annotations

from typing import Any

from cobolparser import parse_cobol
from cobolparser.analysis import DynamicCallAnalyzer


def _program(working_storage: str, procedure: str, linkage: str = "") -> str:
    lines = [
        "       IDENTIFICATION DIVISION.",
        "       PROGRAM-ID. MENUPGM.",
        "       DATA DIVISION.",
        "       WORKING-STORAGE SECTION.",
        working_storage.rstrip("\n"),
    ]
    if linkage:
        lines += ["       LINKAGE SECTION.", linkage.rstrip("\n")]
    lines += [
        "       PROCEDURE DIVISION.",
        procedure.rstrip("\n"),
        "           GOBACK.",
    ]
    return "\n".join(lines) + "\n"


MENU_TABLE = """\
       01 WS-OPTION                 PIC 9(02) VALUE 1.
       01 MENU-OPTIONS.
         05 MENU-OPT-COUNT          PIC 9(02) VALUE 3.
         05 MENU-OPTIONS-DATA.
           10 FILLER                PIC 9(02) VALUE 1.
           10 FILLER                PIC X(10) VALUE 'Account'.
           10 FILLER                PIC X(08) VALUE 'COACTVWC'.
           10 FILLER                PIC 9(02) VALUE 2.
           10 FILLER                PIC X(10) VALUE 'Payment'.
           10 FILLER                PIC X(08) VALUE 'COBIL00C'.
           10 FILLER                PIC 9(02) VALUE 3.
           10 FILLER                PIC X(10) VALUE
               'Pending   '.
           10 FILLER                PIC X(08) VALUE 'COPAUS0C'.
         05 MENU-OPTS REDEFINES MENU-OPTIONS-DATA.
           10 MENU-OPT OCCURS {times} TIMES.
             15 MENU-OPT-NUM        PIC 9(02).
             15 MENU-OPT-NAME       PIC X(10).
             15 MENU-OPT-PGMNAME    PIC X(08).
"""

XCTL_OPTION = """\
           EXEC CICS XCTL
               PROGRAM(MENU-OPT-PGMNAME(WS-OPTION))
           END-EXEC
"""


def _analyze(source: str) -> Any:
    result = parse_cobol(source)
    assert result.ast is not None, result.errors
    DynamicCallAnalyzer().analyze(result.ast)
    return result.ast


def _cics(ast: Any) -> list[dict[str, Any]]:
    return [
        stmt.to_dict()
        for stmt in ast.find_all_by_type("EXEC_CICS")
        if stmt.cics_command in ("LINK", "XCTL", "LOAD")
    ]


class TestRedefinesTable:
    def test_xctl_through_table_gets_every_entry(self) -> None:
        ast = _analyze(_program(MENU_TABLE.format(times=3), XCTL_OPTION))
        [xctl] = _cics(ast)
        assert xctl["possible_values"] == ["COACTVWC", "COBIL00C", "COPAUS0C"]
        assert "possible_values_incomplete" not in xctl

    def test_occurrence_past_the_values_is_incomplete(self) -> None:
        # OCCURS 4 over three entries: the fourth slot's bytes are not set by
        # any VALUE, so the list is kept but not exhaustive.
        ast = _analyze(_program(MENU_TABLE.format(times=4), XCTL_OPTION))
        [xctl] = _cics(ast)
        assert xctl["possible_values"] == ["COACTVWC", "COBIL00C", "COPAUS0C"]
        assert xctl["possible_values_incomplete"] is True

    def test_dynamic_call_through_table(self) -> None:
        ast = _analyze(
            _program(
                MENU_TABLE.format(times=3),
                "           CALL MENU-OPT-PGMNAME(WS-OPTION)",
            )
        )
        [call] = ast.find_all_by_type("CallStatement")
        assert call.possible_values == ["COACTVWC", "COBIL00C", "COPAUS0C"]
        assert not call.get_metadata("possible_values_incomplete")

    def test_write_to_the_redefined_data_is_incomplete(self) -> None:
        ast = _analyze(
            _program(
                MENU_TABLE.format(times=3),
                "           MOVE SPACES TO MENU-OPTIONS-DATA\n" + XCTL_OPTION,
            )
        )
        [xctl] = _cics(ast)
        assert xctl["possible_values_incomplete"] is True

    def test_filler_without_value_leaves_that_slot_unknown(self) -> None:
        ws = """\
       01 WS-I                      PIC 9(02) VALUE 1.
       01 PGM-DATA.
         05 FILLER                  PIC X(08) VALUE 'PGMA'.
         05 FILLER                  PIC X(08).
       01 PGM-TAB REDEFINES PGM-DATA.
         05 PGM-NAME                PIC X(08) OCCURS 2 TIMES.
"""
        ast = _analyze(_program(ws, "           CALL PGM-NAME(WS-I)"))
        [call] = ast.find_all_by_type("CallStatement")
        assert call.possible_values == ["PGMA"]
        assert call.get_metadata("possible_values_incomplete") is True

    def test_elementary_redefined_item(self) -> None:
        ws = """\
       01 WS-I                      PIC 9(02) VALUE 1.
       01 PGM-NAMES                 PIC X(16) VALUE 'PGMAAAAAPGMB'.
       01 PGM-TAB REDEFINES PGM-NAMES.
         05 PGM-NAME                PIC X(08) OCCURS 2 TIMES.
"""
        ast = _analyze(_program(ws, "           CALL PGM-NAME(WS-I)"))
        [call] = ast.find_all_by_type("CallStatement")
        assert call.possible_values == ["PGMAAAAA", "PGMB"]


class TestCicsProgramOperand:
    def test_values_carry_through_moves_from_a_value_clause(self) -> None:
        # MOVE WS-PGMNAME TO WS-FROM, then XCTL PROGRAM(WS-TO) after
        # MOVE WS-FROM TO WS-TO: the value is WS-PGMNAME's VALUE, not a name.
        ws = """\
       01 WS-PGMNAME                PIC X(08) VALUE 'COMEN01C'.
       01 WS-FROM                   PIC X(08).
       01 WS-TO                     PIC X(08).
"""
        procedure = """\
           MOVE WS-PGMNAME TO WS-FROM
           MOVE WS-FROM TO WS-TO
           EXEC CICS XCTL PROGRAM(WS-TO) END-EXEC
           EXEC CICS LINK PROGRAM(WS-FROM) END-EXEC
"""
        ast = _analyze(_program(ws, procedure))
        xctl, link = _cics(ast)
        assert xctl["possible_values"] == ["COMEN01C"]
        assert link["possible_values"] == ["COMEN01C"]
        assert "possible_values_incomplete" not in xctl

    def test_literal_program_is_left_alone(self) -> None:
        ast = _analyze(
            _program(
                "       01 WS-X PIC X.\n",
                "           EXEC CICS XCTL PROGRAM('COSGN00C') END-EXEC",
            )
        )
        [xctl] = _cics(ast)
        assert "possible_values" not in xctl

    def test_commarea_item_is_incomplete(self) -> None:
        # Filled from DFHCOMMAREA: the caller decides what it holds.
        ws = """\
       01 CARDDEMO-COMMAREA.
         05 CDEMO-TO-PROGRAM        PIC X(08).
"""
        linkage = """\
       01 DFHCOMMAREA               PIC X(08).
"""
        procedure = """\
           MOVE DFHCOMMAREA TO CARDDEMO-COMMAREA
           IF CDEMO-TO-PROGRAM = SPACES
               MOVE 'COSGN00C' TO CDEMO-TO-PROGRAM
           END-IF
           EXEC CICS XCTL PROGRAM(CDEMO-TO-PROGRAM) END-EXEC
"""
        ast = _analyze(_program(ws, procedure, linkage))
        [xctl] = _cics(ast)
        assert xctl["possible_values"] == ["COSGN00C"]
        assert xctl["possible_values_incomplete"] is True

    def test_untracked_write_marks_cics_operand_incomplete(self) -> None:
        # ACCEPT is not a MOVE: an untracked write reaches CICS operands just
        # as it reaches CALL variables.
        ws = "       01 WS-PGM PIC X(08) VALUE 'PGMA'.\n"
        procedure = """\
           ACCEPT WS-PGM
           EXEC CICS LINK PROGRAM(WS-PGM) END-EXEC
"""
        ast = _analyze(_program(ws, procedure))
        [link] = _cics(ast)
        assert link["possible_values"] == ["PGMA"]
        assert link["possible_values_incomplete"] is True

    def test_reference_modified_operand_is_not_resolved(self) -> None:
        ws = "       01 WS-PGM PIC X(08) VALUE 'PGMA'.\n"
        ast = _analyze(
            _program(ws, "           EXEC CICS LINK PROGRAM(WS-PGM(1:4)) END-EXEC")
        )
        [link] = _cics(ast)
        assert link["possible_values"] == []
        assert link["possible_values_incomplete"] is True


class TestResolveVariable:
    def test_subscripted_and_qualified_operands(self) -> None:
        result = parse_cobol(_program(MENU_TABLE.format(times=3), XCTL_OPTION))
        tracker = DynamicCallAnalyzer()
        tracker.analyze(result.ast)
        expected = (["COACTVWC", "COBIL00C", "COPAUS0C"], False)
        assert tracker.resolve_variable("MENU-OPT-PGMNAME(WS-OPTION)") == expected
        assert tracker.resolve_variable("MENU-OPT-PGMNAME ( WS-OPTION )") == expected
        assert tracker.resolve_variable("menu-opt-pgmname of menu-opt") == expected

    def test_reference_name(self) -> None:
        assert DynamicCallAnalyzer.reference_name("A-B(I)") == ("A-B", False)
        assert DynamicCallAnalyzer.reference_name("A-B(I)(1:5)") == ("A-B", True)
        assert DynamicCallAnalyzer.reference_name("A-B OF G") == ("A-B", False)
