"""Regression tests: five parser causes of false lint findings (2026-11-12).

Found by running ``lint`` over a private IBM Enterprise COBOL codebase; the
fixtures here are synthetic reproductions of each shape.

1. A line holding only ``EJECT`` / ``SKIPn`` / ``TITLE`` became a statement
   of the paragraph above it: after ``STOP RUN.`` perform-range said the
   paragraph fell through, and an empty paragraph was not empty.
2. A level-88 name starting with a digit (``88-EXP-TXN-AVANCE``) was not
   recognised as a condition, and ``_shape()`` ignored the text it kept, so
   two different ones read as the same condition (duplicate-branch).
3. A MOVE into a field of a ``FILLER REDEFINES X`` was not counted as
   storing into X (uninitialized).
4. Site abend routines (``CALL 'CBLTBNC2'``) could not be declared
   non-returning, and an IF / ELSE arm ending in a PERFORM of an abend
   paragraph did not end the paragraph (perform-range).
5. io-sequence judged a subprogram that OPENs, READs and CLOSEs on separate
   CALLs, and an ``FD ... IS EXTERNAL`` file, as if every file started
   closed.
"""

from __future__ import annotations

import textwrap

import pytest

from cobolparser import parse_cobol
from cobolparser.analysis import (
    IOSequenceAnalyzer,
    LintAnalyzer,
    set_site_abend_programs,
    site_abend_programs,
    using_site_abend_programs,
)


def _program(body: str, data: str = "", env: str = "") -> str:
    """A free-form program: each part dedented on its own, then joined."""
    parts = [
        "IDENTIFICATION DIVISION.\nPROGRAM-ID. LFP.\n",
        textwrap.dedent(env),
        "DATA DIVISION.\n",
        textwrap.dedent(data),
        "PROCEDURE DIVISION.\n",
        textwrap.dedent(body),
    ]
    return "".join(p if p.endswith("\n") or not p else p + "\n" for p in parts)


def _parse(source: str):
    result = parse_cobol(source, filename="lfp.cbl")
    assert result.success, result.errors
    return result


def _findings(source: str, rule: str) -> list[dict]:
    report = LintAnalyzer(rules=[rule]).analyze(_parse(source).ast).to_dict()
    return [f for f in report["findings"] if f["rule"] == rule]


_WS = """\
WORKING-STORAGE SECTION.
01 WS-A PIC 9 VALUE 0.
"""


class TestListingDirectivesAreNotStatements:
    def test_eject_after_stop_run_is_not_a_fall_through(self):
        source = _program(
            """\
            MAIN-PARA.
                PERFORM P1
                STOP RUN.
            EJECT
            P1.
                MOVE 1 TO WS-A.
            SKIP1
            """,
            data=_WS,
        )
        assert _findings(source, "perform-range") == []
        main, p1 = _parse(source).ast.find_all_by_type("CobolParagraph")
        assert [type(s).__name__ for s in main.statements] == [
            "PerformStatement",
            "StopStatement",
        ]
        assert [type(s).__name__ for s in p1.statements] == ["MoveStatement"]

    def test_paragraph_holding_only_directives_is_empty(self):
        source = _program("""\
            MAIN-PARA.
                STOP RUN.
            P2.
                EJECT.
                SKIP2
                TITLE 'NEXT PAGE'.
            P3.
                STOP RUN.
            """)
        paras = _parse(source).ast.find_all_by_type("CobolParagraph")
        assert paras[1].statements == []

    @pytest.mark.parametrize("directive", ["EJECT", "EJECT.", "SKIP3", "TITLE 'X'"])
    def test_directive_inside_if_and_evaluate_bodies(self, directive):
        source = _program(
            f"""\
            MAIN-PARA.
                IF WS-A = 1
                   MOVE 2 TO WS-A
            {directive}
                ELSE
                   MOVE 3 TO WS-A
                END-IF
                EVALUATE WS-A
                  WHEN 1
            {directive}
                    DISPLAY 'A'
                  WHEN OTHER
                    DISPLAY 'B'
                END-EVALUATE
                STOP RUN.
            """,
            data=_WS,
        )
        result = _parse(source)
        assert result.warnings == []
        [para] = result.ast.find_all_by_type("CobolParagraph")
        if_stmt, evaluate, stop = para.statements
        assert [type(s).__name__ for s in if_stmt.then_statements] == ["MoveStatement"]
        assert [type(s).__name__ for s in if_stmt.else_statements] == ["MoveStatement"]
        when = evaluate.to_dict()["when_clauses"][0]
        assert when["selectors"] == [{"type": "Literal", "value": "1"}]
        assert type(stop).__name__ == "StopStatement"

    def test_directive_between_operands(self):
        source = _program(
            """\
            MAIN-PARA.
                MOVE 1
            EJECT
                  TO WS-A
                STOP RUN.
            """,
            data=_WS,
        )
        [para] = _parse(source).ast.find_all_by_type("CobolParagraph")
        move = para.statements[0]
        assert move.source == "1"
        assert move.targets == ["WS-A"]

    def test_directive_sharing_a_line_is_still_a_statement(self):
        source = _program("""\
            MAIN-PARA.
                CONTINUE EJECT
                STOP RUN.
            """)
        [para] = _parse(source).ast.find_all_by_type("CobolParagraph")
        assert [type(s).__name__ for s in para.statements] == [
            "ContinueStatement",
            "EjectStatement",
            "StopStatement",
        ]


_TXN = """\
WORKING-STORAGE SECTION.
01 WS-TYPE PIC X.
   88 88-EXP-TXN-AVANCE VALUE 'A'.
   88 88-EXP-TXN-RETARD VALUE 'R'.
01 WS-B PIC 9.
"""


class TestDigitLeadingConditionNames:
    def test_condition_name_is_structured(self):
        source = _program(
            """\
            MAIN-PARA.
                IF 88-EXP-TXN-AVANCE
                   MOVE 1 TO WS-B
                END-IF
                STOP RUN.
            """,
            data=_TXN,
        )
        [para] = _parse(source).ast.find_all_by_type("CobolParagraph")
        condition = para.statements[0].to_dict()["condition"]
        assert condition["operator"] == "CONDITION_NAME"
        assert condition["left_operand"] == "88-EXP-TXN-AVANCE"

    def test_different_conditions_are_not_duplicate_branches(self):
        source = _program(
            """\
            MAIN-PARA.
                IF 88-EXP-TXN-AVANCE
                   MOVE 1 TO WS-B
                ELSE
                   IF 88-EXP-TXN-RETARD
                      MOVE 2 TO WS-B
                   END-IF
                END-IF
                STOP RUN.
            """,
            data=_TXN,
        )
        assert _findings(source, "duplicate-branch") == []

    def test_same_condition_is_still_a_duplicate_branch(self):
        source = _program(
            """\
            MAIN-PARA.
                IF 88-EXP-TXN-AVANCE
                   MOVE 1 TO WS-B
                ELSE
                   IF 88-EXP-TXN-AVANCE
                      MOVE 2 TO WS-B
                   END-IF
                END-IF
                STOP RUN.
            """,
            data=_TXN,
        )
        assert len(_findings(source, "duplicate-branch")) == 1

    def test_unstructured_conditions_keep_their_text(self):
        from cobolparser.analysis.code_patterns import _shape

        def blank(raw: str) -> dict:
            return {
                "node_type": "Expression",
                "expression_type": "COMPARISON",
                "operator": "COMPARISON",
                "operands": [],
                "left_operand": None,
                "right_operand": None,
                "metadata": {"raw_condition": raw},
            }

        assert _shape(blank("X-ONE")) != _shape(blank("X-TWO"))
        assert _shape(blank("X-ONE")) == _shape(blank("x-one"))


class TestFillerRedefinesWrites:
    @pytest.mark.parametrize(
        "data",
        [
            """\
            WORKING-STORAGE SECTION.
            01 WS-REC.
               05 WS-DATE.
                  10 WS-YYYY PIC 9(4).
                  10 WS-MM   PIC 99.
               05 FILLER REDEFINES WS-DATE.
                  10 WS-DATE-X PIC X(6).
            """,
            """\
            WORKING-STORAGE SECTION.
            01 WS-DATE.
               05 WS-YYYY PIC 9(4).
               05 WS-MM   PIC 99.
            01 FILLER REDEFINES WS-DATE.
               05 WS-DATE-X PIC X(6).
            """,
        ],
        ids=["level-05", "level-01"],
    )
    def test_write_through_filler_redefines_initializes(self, data):
        source = _program(
            """\
            MAIN-PARA.
                MOVE '202611' TO WS-DATE-X
                DISPLAY WS-YYYY WS-MM
                STOP RUN.
            """,
            data=textwrap.dedent(data),
        )
        assert _findings(source, "uninitialized") == []

    def test_never_written_item_is_still_reported(self):
        source = _program(
            """\
            MAIN-PARA.
                DISPLAY WS-YYYY
                STOP RUN.
            """,
            data=textwrap.dedent("""\
                WORKING-STORAGE SECTION.
                01 WS-DATE.
                   05 WS-YYYY PIC 9(4).
                01 FILLER REDEFINES WS-DATE.
                   05 WS-DATE-X PIC X(4).
                """),
        )
        assert [f["symbol"] for f in _findings(source, "uninitialized")] == ["WS-YYYY"]


def _abend_program(last: str) -> str:
    return _program(
        f"""\
        MAIN-PARA.
            PERFORM P1
        {last}
        P1.
            MOVE 1 TO WS-A.
        ABEND-PARA.
            CALL 'CEE3ABD'.
        """,
        data=_WS,
    )


class TestSiteAbendRoutines:
    def setup_method(self):
        set_site_abend_programs(None)

    def teardown_method(self):
        set_site_abend_programs(None)

    def test_unknown_routine_is_assumed_to_return(self):
        source = _abend_program("    CALL 'CBLTBNC2'.")
        assert len(_findings(source, "perform-range")) == 1

    def test_declared_routine_ends_the_paragraph(self):
        source = _abend_program("    CALL 'CBLTBNC2'.")
        with using_site_abend_programs(["cbltbnc2", "CSDABEND"]):
            assert site_abend_programs() == {"CBLTBNC2", "CSDABEND"}
            assert _findings(source, "perform-range") == []
        assert site_abend_programs() == frozenset()

    def test_dynamic_call_is_never_an_abend(self):
        source = _abend_program("    CALL WS-A.")
        with using_site_abend_programs(["WS-A"]):
            assert len(_findings(source, "perform-range")) == 1

    def test_if_else_ending_in_perform_of_abend_paragraph(self):
        source = _abend_program("""\
            IF WS-A = 1
               GOBACK
            ELSE
               PERFORM ABEND-PARA
            END-IF.""")
        assert _findings(source, "perform-range") == []

    def test_if_without_else_still_falls_through(self):
        source = _abend_program("""\
            IF WS-A = 1
               PERFORM ABEND-PARA
            END-IF.""")
        assert len(_findings(source, "perform-range")) == 1


_FILE_ENV = """\
ENVIRONMENT DIVISION.
INPUT-OUTPUT SECTION.
FILE-CONTROL.
    SELECT IN-FILE ASSIGN TO INFILE.
"""


def _file_data(fd: str = "FD IN-FILE.", linkage: bool = False) -> str:
    text = f"FILE SECTION.\n{fd}\n01 IN-REC PIC X(80).\n"
    if linkage:
        text += "LINKAGE SECTION.\n01 LK-FUNC PIC X.\n"
    return text


_DISPATCHER = """\
MAIN-PARA.
    EVALUATE LK-FUNC
      WHEN 'O' PERFORM DO-OPEN
      WHEN 'R' PERFORM DO-READ
      WHEN 'C' PERFORM DO-CLOSE
    END-EVALUATE
    GOBACK.
DO-OPEN.
    OPEN INPUT IN-FILE.
DO-READ.
    READ IN-FILE.
DO-CLOSE.
    CLOSE IN-FILE.
"""


def _io_kinds(source: str) -> list[str]:
    report = IOSequenceAnalyzer().analyze(_parse(source).ast)
    return [v.kind.name for v in report.violations]


def _dispatcher(program_id: str) -> str:
    return (
        f"IDENTIFICATION DIVISION.\nPROGRAM-ID. {program_id}.\n{_FILE_ENV}"
        f"DATA DIVISION.\n{_file_data(linkage=True)}"
        f"PROCEDURE DIVISION USING LK-FUNC.\n{_DISPATCHER}"
    )


class TestIoSequenceCarriedFiles:
    def test_subprogram_dispatcher_is_clean(self):
        assert _io_kinds(_dispatcher("DISP")) == []

    def test_initial_subprogram_starts_closed(self):
        kinds = _io_kinds(_dispatcher("DISP IS INITIAL"))
        assert "READ_BEFORE_OPEN" in kinds
        assert "CLOSE_NOT_OPEN" in kinds

    def test_external_file_may_be_open_already(self):
        source = _program(
            """\
            MAIN-PARA.
                READ IN-FILE
                CLOSE IN-FILE
                GOBACK.
            """,
            data=_file_data("FD IN-FILE IS EXTERNAL."),
            env=_FILE_ENV,
        )
        assert _io_kinds(source) == []

    def test_internal_file_in_main_program_is_still_checked(self):
        source = _program(
            """\
            MAIN-PARA.
                READ IN-FILE
                CLOSE IN-FILE
                GOBACK.
            """,
            data=_file_data(),
            env=_FILE_ENV,
        )
        assert _io_kinds(source) == ["READ_BEFORE_OPEN", "CLOSE_NOT_OPEN"]

    def test_read_after_its_own_close_is_still_reported(self):
        source = _program(
            """\
            MAIN-PARA.
                READ IN-FILE
                CLOSE IN-FILE
                READ IN-FILE
                GOBACK.
            """,
            data=_file_data("FD IN-FILE IS EXTERNAL."),
            env=_FILE_ENV,
        )
        assert _io_kinds(source) == ["READ_BEFORE_OPEN"]
