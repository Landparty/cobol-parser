"""InputDependenceAnalyzer: which IF / EVALUATE an input can change, and
what a measured run proves unreachable."""

from __future__ import annotations

import pytest

from cobolparser import parse_cobol
from cobolparser.analysis.input_dependence import (
    REASON_DEAD,
    REASON_FIXED,
    InputDependenceAnalyzer,
    InputDependenceReport,
)


def _program(procedure: str, working: str = "", files: str = "") -> str:
    """A fixed-format program; `procedure` lines start in Area A."""
    env = ""
    file_section = ""
    if files:
        env = (
            "       ENVIRONMENT DIVISION.\n"
            "       INPUT-OUTPUT SECTION.\n"
            "       FILE-CONTROL.\n"
            "           SELECT IN-FILE ASSIGN TO INDD\n"
            "               FILE STATUS IS WS-FS.\n"
        )
        file_section = (
            "       FILE SECTION.\n"
            "       FD  IN-FILE.\n"
            "       01  IN-REC PIC X(10).\n"
        )
    return (
        "       IDENTIFICATION DIVISION.\n"
        "       PROGRAM-ID. P.\n"
        + env
        + "       DATA DIVISION.\n"
        + file_section
        + "       WORKING-STORAGE SECTION.\n"
        "       01  WS-A PIC 9 VALUE 0.\n"
        "       01  WS-B PIC 9 VALUE 0.\n"
        "       01  WS-N PIC 99 VALUE 0.\n"
        "       01  WS-FS PIC XX.\n"
        "       01  WS-EOF PIC X VALUE 'N'.\n"
        + working
        + "       PROCEDURE DIVISION.\n"
        + procedure
    )


def _analyze(source: str, **kwargs: object) -> tuple[InputDependenceReport, list[str]]:
    result = parse_cobol(source, filename="P.cbl")
    assert result.ast is not None, result.errors
    lines = source.split("\n")
    return InputDependenceAnalyzer().analyze(result.ast, **kwargs), lines


def _line_of(lines: list[str], text: str) -> int:
    for number, line in enumerate(lines, start=1):
        if text in line:
            return number
    raise AssertionError(text)


SELF_CHECK = _program(
    "       MAIN-PARA.\n"
    "           ACCEPT WS-B\n"
    "           MOVE 1 TO WS-A\n"
    "           IF WS-A = 1\n"
    "               PERFORM PASS-PARA\n"
    "           ELSE\n"
    "               PERFORM FAIL-PARA\n"
    "           END-IF\n"
    "           IF WS-B = 1\n"
    "               DISPLAY 'ONE'\n"
    "           END-IF\n"
    "           STOP RUN.\n"
    "       PASS-PARA.\n"
    "           DISPLAY 'PASS'.\n"
    "       FAIL-PARA.\n"
    "           DISPLAY 'FAIL'.\n"
    "       DEAD-PARA.\n"
    "           DISPLAY 'DEAD'.\n"
)


def test_constant_decision_is_independent_and_accept_makes_one_dependent():
    report, lines = _analyze(SELF_CHECK)
    fixed = report.decision("IF", _line_of(lines, "IF WS-A = 1"))
    varies = report.decision("IF", _line_of(lines, "IF WS-B = 1"))
    assert fixed is not None and not fixed.input_dependent
    assert fixed.outcomes == ["true", "false"]
    assert varies is not None and varies.input_dependent and varies.reason
    assert "WS-B" in report.input_records
    assert report.entry_names == ["MAIN-PARA"]
    assert report.decision("IF", 1) is None
    as_dict = report.to_dict()
    assert as_dict["incomplete"] is None and len(as_dict["decisions"]) == 2


def test_untaken_outcome_prunes_the_paragraph_behind_it():
    report, lines = _analyze(SELF_CHECK)
    if_a = _line_of(lines, "IF WS-A = 1")
    if_b = _line_of(lines, "IF WS-B = 1")
    found = report.unreachable({("IF", if_a): {0}, ("IF", if_b): {1}})
    assert found.outcomes[("IF", if_a)] == {1: REASON_FIXED}
    assert ("IF", if_b) not in found.outcomes  # an input can take it
    assert found.paragraphs["DEAD-PARA"] == REASON_DEAD
    assert "reached only through" in found.paragraphs["FAIL-PARA"]
    assert "PASS-PARA" not in found.paragraphs
    assert _line_of(lines, "DISPLAY 'FAIL'") in found.statements
    assert found.statements[_line_of(lines, "DISPLAY 'DEAD'")] == REASON_DEAD


def test_nothing_measured_claims_only_dead_code():
    report, _lines = _analyze(SELF_CHECK)
    found = report.unreachable({})
    assert set(found.paragraphs) == {"DEAD-PARA"}
    assert found.outcomes == {}


def test_extra_inputs_make_a_setup_move_target_input_fed():
    report, lines = _analyze(SELF_CHECK, extra_inputs=["ws-a"])
    decision = report.decision("IF", _line_of(lines, "IF WS-A = 1"))
    # MOVE 1 TO WS-A still overwrites it, but the record is seeded.
    assert decision is not None
    assert "WS-A" in report.input_records


READ_LOOP = _program(
    "       MAIN-PARA.\n"
    "           OPEN INPUT IN-FILE\n"
    "           PERFORM UNTIL WS-EOF = 'Y'\n"
    "               READ IN-FILE\n"
    "                   AT END MOVE 'Y' TO WS-EOF\n"
    "                   NOT AT END ADD 1 TO WS-N\n"
    "               END-READ\n"
    "           END-PERFORM\n"
    "           IF WS-N > 5\n"
    "               DISPLAY 'MANY'\n"
    "           END-IF\n"
    "           IF WS-FS = '00'\n"
    "               DISPLAY 'OK'\n"
    "           END-IF\n"
    "           CLOSE IN-FILE\n"
    "           STOP RUN.\n",
    files="yes",
)


def test_counter_bumped_under_a_read_clause_is_input_dependent():
    report, lines = _analyze(READ_LOOP)
    many = report.decision("IF", _line_of(lines, "IF WS-N > 5"))
    status = report.decision("IF", _line_of(lines, "IF WS-FS = '00'"))
    assert many is not None and many.input_dependent
    assert status is not None and status.input_dependent
    found = report.unreachable({("IF", many.line): {1}, ("IF", status.line): {0}})
    assert found.outcomes == {}


EVALUATE = _program(
    "       MAIN-PARA.\n"
    "           MOVE 2 TO WS-A\n"
    "           EVALUATE WS-A\n"
    "               WHEN 1\n"
    "                   DISPLAY 'ONE'\n"
    "               WHEN 2\n"
    "                   DISPLAY 'TWO'\n"
    "               WHEN OTHER\n"
    "                   DISPLAY 'OTHER'\n"
    "           END-EVALUATE\n"
    "           STOP RUN.\n"
)


def test_evaluate_outcomes_one_per_when_group():
    report, lines = _analyze(EVALUATE)
    line = _line_of(lines, "EVALUATE WS-A")
    decision = report.decision("EVALUATE", line)
    assert decision is not None and not decision.input_dependent
    assert decision.outcomes[-1] == "WHEN OTHER" and len(decision.outcomes) == 3
    found = report.unreachable({("EVALUATE", line): {1}})
    assert found.outcomes[("EVALUATE", line)] == {0: REASON_FIXED, 2: REASON_FIXED}
    assert _line_of(lines, "DISPLAY 'ONE'") in found.statements
    assert _line_of(lines, "DISPLAY 'TWO'") not in found.statements


def test_a_decision_inside_an_unreachable_outcome_is_unreachable_too():
    source = _program(
        "       MAIN-PARA.\n"
        "           IF WS-A = 1\n"
        "               IF WS-B = 1\n"
        "                   DISPLAY 'X'\n"
        "               END-IF\n"
        "           END-IF\n"
        "           STOP RUN.\n"
    )
    report, lines = _analyze(source)
    outer = _line_of(lines, "IF WS-A = 1")
    inner = _line_of(lines, "IF WS-B = 1")
    found = report.unreachable({("IF", outer): {1}})
    assert found.outcomes[("IF", inner)] == {0: REASON_FIXED, 1: REASON_FIXED}


def test_size_error_clause_pruned_with_executed_lines():
    source = _program(
        "       MAIN-PARA.\n"
        "           ADD 1 TO WS-A\n"
        "               ON SIZE ERROR\n"
        "                   DISPLAY 'OVERFLOW'\n"
        "           END-ADD\n"
        "           STOP RUN.\n"
    )
    report, lines = _analyze(source)
    add = _line_of(lines, "ADD 1 TO WS-A")
    stop = _line_of(lines, "STOP RUN")
    body = _line_of(lines, "DISPLAY 'OVERFLOW'")
    assert body in report.unreachable({}, [add, stop]).statements
    assert body not in report.unreachable({}).statements


def test_call_and_linkage_feed_inputs():
    source = (
        "       IDENTIFICATION DIVISION.\n"
        "       PROGRAM-ID. P.\n"
        "       DATA DIVISION.\n"
        "       WORKING-STORAGE SECTION.\n"
        "       01  WS-A PIC 9 VALUE 0.\n"
        "       01  WS-C PIC 9 VALUE 0.\n"
        "       LINKAGE SECTION.\n"
        "       01  LK-A PIC 9.\n"
        "       PROCEDURE DIVISION USING LK-A.\n"
        "       MAIN-PARA.\n"
        "           CALL 'SUB' USING WS-C\n"
        "           IF WS-C = 1\n"
        "               DISPLAY 'C'\n"
        "           END-IF\n"
        "           IF LK-A = 1\n"
        "               DISPLAY 'L'\n"
        "           END-IF\n"
        "           GOBACK.\n"
    )
    report, lines = _analyze(source)
    for text in ("IF WS-C = 1", "IF LK-A = 1"):
        decision = report.decision("IF", _line_of(lines, text))
        assert decision is not None and decision.input_dependent, text


def test_sections_and_declaratives_pick_the_entry_point():
    source = _program(
        "       DECLARATIVES.\n"
        "       ERR-SECTION SECTION.\n"
        "           USE AFTER ERROR PROCEDURE ON IN-FILE.\n"
        "       ERR-PARA.\n"
        "           MOVE 'Y' TO WS-EOF.\n"
        "       END DECLARATIVES.\n"
        "       MAIN-SECTION SECTION.\n"
        "       MAIN-PARA.\n"
        "           OPEN INPUT IN-FILE\n"
        "           IF WS-EOF = 'Y'\n"
        "               DISPLAY 'ERR'\n"
        "           END-IF\n"
        "           STOP RUN.\n",
        files="yes",
    )
    report, lines = _analyze(source)
    assert report.entry_names == ["MAIN-SECTION", "MAIN-PARA"]
    decision = report.decision("IF", _line_of(lines, "IF WS-EOF = 'Y'"))
    # The declarative runs on an I/O error: WS-EOF is input-fed.
    assert decision is not None and decision.input_dependent
    found = report.unreachable({("IF", decision.line): {1}})
    assert "ERR-PARA" not in found.paragraphs


def test_altered_go_to_reaches_its_new_target():
    source = _program(
        "       MAIN-PARA.\n"
        "           ALTER SWITCH-PARA TO PROCEED TO SECOND-PARA\n"
        "           GO TO SWITCH-PARA.\n"
        "       SWITCH-PARA.\n"
        "           GO TO FIRST-PARA.\n"
        "       FIRST-PARA.\n"
        "           DISPLAY 'FIRST'\n"
        "           STOP RUN.\n"
        "       SECOND-PARA.\n"
        "           DISPLAY 'SECOND'\n"
        "           STOP RUN.\n"
    )
    report, _lines = _analyze(source)
    found = report.unreachable({})
    assert "SECOND-PARA" not in found.paragraphs
    assert "FIRST-PARA" not in found.paragraphs


def test_go_to_and_perform_thru():
    source = _program(
        "       MAIN-PARA.\n"
        "           PERFORM A-PARA THRU B-PARA\n"
        "           PERFORM VARYING WS-N FROM 1 BY 1 UNTIL WS-N > 3\n"
        "               ADD 1 TO WS-A\n"
        "           END-PERFORM\n"
        "           GO TO END-PARA.\n"
        "       A-PARA.\n"
        "           DISPLAY 'A'.\n"
        "       B-PARA.\n"
        "           DISPLAY 'B'.\n"
        "       SKIPPED-PARA.\n"
        "           DISPLAY 'S'.\n"
        "       END-PARA.\n"
        "           STOP RUN.\n"
    )
    report, _lines = _analyze(source)
    found = report.unreachable({})
    assert set(found.paragraphs) == {"SKIPPED-PARA"}


def test_two_decisions_on_one_line_are_never_pruned():
    source = _program(
        "       MAIN-PARA.\n"
        "           IF WS-A = 1 DISPLAY 'X' END-IF IF WS-B = 1 DISPLAY 'Y' END-IF\n"
        "           STOP RUN.\n"
    )
    report, lines = _analyze(source)
    line = _line_of(lines, "IF WS-A = 1")
    assert report.unreachable({("IF", line): {1}}).outcomes == {}


def test_no_procedure_division_and_too_large_programs_claim_nothing(monkeypatch):
    source = (
        "       IDENTIFICATION DIVISION.\n"
        "       PROGRAM-ID. P.\n"
        "       DATA DIVISION.\n"
        "       WORKING-STORAGE SECTION.\n"
        "       01  WS-A PIC 9.\n"
    )
    empty, _ = _analyze(source)
    assert empty.decisions == [] and empty.unreachable({}).paragraphs == {}
    monkeypatch.setattr(InputDependenceAnalyzer, "max_nodes", 1)
    report, _ = _analyze(SELF_CHECK)
    assert report.incomplete == "program too large"
    assert report.unreachable({("IF", 1): {0}}).paragraphs == {}


@pytest.mark.parametrize(
    "statement",
    [
        "MOVE FUNCTION CURRENT-DATE TO WS-SINK",
        "ACCEPT WS-SINK FROM DATE",
        "READ IN-FILE INTO WS-SINK END-READ",
        "STRING IN-REC DELIMITED BY SIZE INTO WS-SINK END-STRING",
    ],
)
def test_input_sources_taint_what_they_write(statement):
    source = _program(
        "       MAIN-PARA.\n"
        "           OPEN INPUT IN-FILE\n"
        f"           {statement}\n"
        "           IF WS-SINK = SPACES\n"
        "               DISPLAY 'BLANK'\n"
        "           END-IF\n"
        "           STOP RUN.\n",
        working="       01  WS-SINK PIC X(21).\n",
        files="yes",
    )
    report, lines = _analyze(source)
    decision = report.decision("IF", _line_of(lines, "IF WS-SINK = SPACES"))
    assert decision is not None and decision.input_dependent, statement


CONTROL_FLOW = _program(
    "       MAIN-SECTION SECTION.\n"
    "       MAIN-PARA.\n"
    "           SET T-IX TO 1\n"
    "           SEARCH T-ENTRY\n"
    "               AT END DISPLAY 'NOT FOUND'\n"
    "               WHEN T-ENTRY (T-IX) = 'B'\n"
    "                   DISPLAY 'FOUND'\n"
    "           END-SEARCH\n"
    "           DIVIDE 7 BY 2 GIVING WS-A REMAINDER WS-B\n"
    "           IF WS-B = 1\n"
    "               NEXT SENTENCE\n"
    "           END-IF\n"
    "           PERFORM UNTIL WS-N > 2\n"
    "               ADD 1 TO WS-N\n"
    "               IF WS-N = 2\n"
    "                   EXIT PERFORM\n"
    "               END-IF\n"
    "           END-PERFORM\n"
    "           PERFORM SUB-PARA\n"
    "           PERFORM OTHER-SECTION\n"
    "           STOP 'PAUSE'\n"
    "           GO TO A-PARA B-PARA DEPENDING ON WS-A.\n"
    "       A-PARA.\n"
    "           EXIT PROGRAM.\n"
    "       B-PARA.\n"
    "           STOP RUN.\n"
    "       SUB-PARA.\n"
    "           IF WS-A = 3\n"
    "               EXIT PARAGRAPH\n"
    "           END-IF\n"
    "           DISPLAY 'SUB'.\n"
    "       OTHER-SECTION SECTION.\n"
    "       O-PARA.\n"
    "           IF WS-A = 3\n"
    "               EXIT SECTION\n"
    "           END-IF\n"
    "           EXIT.\n"
    "       O-END.\n"
    "           DISPLAY 'O'.\n",
    working=(
        "       01  T-TABLE VALUE 'ABC'.\n"
        "           05  T-ENTRY PIC X OCCURS 3 INDEXED BY T-IX.\n"
    ),
)


def test_search_go_to_depending_and_exits_are_modeled():
    report, lines = _analyze(CONTROL_FLOW)
    assert report.incomplete is None
    assert report.entry_names == ["MAIN-SECTION", "MAIN-PARA"]
    found = report.unreachable({})
    # Every procedure is reached by some PERFORM, GO TO or fall-through.
    assert found.paragraphs == {}
    remainder = report.decision("IF", _line_of(lines, "IF WS-B = 1"))
    assert remainder is not None and not remainder.input_dependent
    found = report.unreachable(
        {("IF", remainder.line): {1}},
        executed_lines=[_line_of(lines, "SEARCH T-ENTRY")],
    )
    assert found.outcomes[("IF", remainder.line)] == {0: REASON_FIXED}


def test_sort_input_procedure_runs_on_an_event():
    source = (
        "       IDENTIFICATION DIVISION.\n"
        "       PROGRAM-ID. P.\n"
        "       ENVIRONMENT DIVISION.\n"
        "       INPUT-OUTPUT SECTION.\n"
        "       FILE-CONTROL.\n"
        "           SELECT SORT-FILE ASSIGN TO SORTWK.\n"
        "           SELECT OUT-FILE ASSIGN TO OUTDD.\n"
        "       DATA DIVISION.\n"
        "       FILE SECTION.\n"
        "       SD  SORT-FILE.\n"
        "       01  SORT-REC PIC X(10).\n"
        "       FD  OUT-FILE.\n"
        "       01  OUT-REC PIC X(10).\n"
        "       WORKING-STORAGE SECTION.\n"
        "       01  WS-A PIC 9 VALUE 0.\n"
        "       PROCEDURE DIVISION.\n"
        "       MAIN-PARA.\n"
        "           SORT SORT-FILE ON ASCENDING KEY SORT-REC\n"
        "               INPUT PROCEDURE IS FEED-PARA\n"
        "               GIVING OUT-FILE\n"
        "           STOP RUN.\n"
        "       FEED-PARA.\n"
        "           MOVE 'X' TO SORT-REC\n"
        "           RELEASE SORT-REC.\n"
    )
    report, _lines = _analyze(source)
    assert "FEED-PARA" not in report.unreachable({}).paragraphs


@pytest.mark.parametrize(
    "condition, reason",
    [
        (
            "IF FUNCTION CURRENT-DATE(1:4) > '2025'",
            "reads the clock (FUNCTION CURRENT-DATE)",
        ),
        ("IF FUNCTION RANDOM > 0.5", "reads the environment (FUNCTION RANDOM)"),
    ],
)
def test_environment_function_in_a_decision_is_input_dependent(condition, reason):
    # #857: the function in the decision's own operands, not via a MOVE.
    source = _program(
        "       MAIN-PARA.\n"
        f"           {condition}\n"
        "               DISPLAY 'LATE'\n"
        "           END-IF\n"
        "           STOP RUN.\n",
    )
    report, lines = _analyze(source)
    decision = report.decision("IF", _line_of(lines, condition))
    assert decision is not None and decision.input_dependent
    assert decision.reason == reason
    assert report.unreachable({("IF", decision.line): {0}}).outcomes == {}


def test_nested_program_decision_on_a_global_item_is_input_dependent():
    # #857: INNER reads OUTER's GLOBAL WS-FLAG, filled from a READ.
    source = (
        "       IDENTIFICATION DIVISION.\n"
        "       PROGRAM-ID. OUTER.\n"
        "       ENVIRONMENT DIVISION.\n"
        "       INPUT-OUTPUT SECTION.\n"
        "       FILE-CONTROL.\n"
        "           SELECT IN-FILE ASSIGN TO INDD.\n"
        "       DATA DIVISION.\n"
        "       FILE SECTION.\n"
        "       FD  IN-FILE.\n"
        "       01  IN-REC PIC X(10).\n"
        "       WORKING-STORAGE SECTION.\n"
        "       01  WS-FLAG PIC X VALUE 'N' GLOBAL.\n"
        "       PROCEDURE DIVISION.\n"
        "       MAIN-PARA.\n"
        "           OPEN INPUT IN-FILE\n"
        "           READ IN-FILE END-READ\n"
        "           MOVE IN-REC(1:1) TO WS-FLAG\n"
        "           CALL 'INNER'\n"
        "           STOP RUN.\n"
        "       IDENTIFICATION DIVISION.\n"
        "       PROGRAM-ID. INNER.\n"
        "       DATA DIVISION.\n"
        "       WORKING-STORAGE SECTION.\n"
        "       01  WS-LOCAL PIC X VALUE 'N'.\n"
        "       PROCEDURE DIVISION.\n"
        "       INNER-PARA.\n"
        "           IF WS-FLAG = 'Y'\n"
        "               DISPLAY 'YES'\n"
        "           END-IF\n"
        "           IF WS-LOCAL = 'Y'\n"
        "               DISPLAY 'NEVER'\n"
        "           END-IF\n"
        "           GOBACK.\n"
        "       END PROGRAM INNER.\n"
        "       END PROGRAM OUTER.\n"
    )
    result = parse_cobol(source, filename="OUTER.cbl")
    assert result.ast is not None, result.errors
    inner = result.ast.contained_programs[0]
    report = InputDependenceAnalyzer().analyze(inner)
    lines = source.split("\n")
    flag = report.decision("IF", _line_of(lines, "IF WS-FLAG = 'Y'"))
    local = report.decision("IF", _line_of(lines, "IF WS-LOCAL = 'Y'"))
    assert flag is not None and flag.input_dependent
    assert local is not None and not local.input_dependent
