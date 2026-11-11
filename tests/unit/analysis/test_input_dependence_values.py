"""The value pass behind InputDependenceAnalyzer: IF outcomes no value the
program can hold takes, each PERFORM judged with its own caller's values."""

from __future__ import annotations

import pytest

from cobolparser import parse_cobol
from cobolparser.analysis import _values
from cobolparser.analysis.input_dependence import (
    REASON_VALUES,
    InputDependenceAnalyzer,
    InputDependenceReport,
)


def _program(procedure: str, working: str = "", extra_divisions: str = "") -> str:
    return (
        "       IDENTIFICATION DIVISION.\n"
        "       PROGRAM-ID. P.\n" + extra_divisions + "       DATA DIVISION.\n"
        "       WORKING-STORAGE SECTION.\n"
        + working
        + "       PROCEDURE DIVISION.\n"
        + procedure
    )


def _analyze(source: str, **kwargs: object) -> tuple[InputDependenceReport, list[str]]:
    result = parse_cobol(source, filename="P.cbl")
    assert result.ast is not None, result.errors
    return InputDependenceAnalyzer().analyze(result.ast, **kwargs), source.split("\n")


def _line(lines: list[str], text: str) -> int:
    for number, line in enumerate(lines, start=1):
        if text in line:
            return number
    raise AssertionError(text)


class _Cuts(dict[int, set[int]]):
    def __missing__(self, key: int) -> set[int]:
        return set()


def _infeasible(report: InputDependenceReport) -> _Cuts:
    graph = report._graph
    assert graph is not None
    return _Cuts(
        {graph.statement_lines[n]: cut for n, cut in report._infeasible.items()}
    )


CCVS = _program(
    "       MAIN-PARA.\n"
    "           ACCEPT WS-IN\n"
    "           IF WS-IN = 1\n"
    "               PERFORM PASS-PARA\n"
    "           ELSE\n"
    "               MOVE WS-IN TO COMPUTED-N\n"
    "               PERFORM FAIL-PARA\n"
    "           END-IF\n"
    "           ADD 1 TO REC-CT\n"
    "           PERFORM PASS-PARA\n"
    "           STOP RUN.\n"
    "       PASS-PARA.\n"
    "           MOVE 'PASS ' TO P-OR-F\n"
    "           ADD 1 TO LINE-CT\n"
    "           PERFORM PRINT-DETAIL.\n"
    "       FAIL-PARA.\n"
    "           MOVE 'FAIL*' TO P-OR-F\n"
    "           PERFORM PRINT-DETAIL.\n"
    "       PRINT-DETAIL.\n"
    "           IF REC-CT NOT EQUAL TO ZERO\n"
    "               DISPLAY 'DOT'\n"
    "           END-IF\n"
    "           IF P-OR-F EQUAL TO 'FAIL*'\n"
    "               PERFORM FAIL-ROUTINE\n"
    "           ELSE\n"
    "               PERFORM BAIL-OUT\n"
    "           END-IF\n"
    "           MOVE SPACE TO COMPUTED-X.\n"
    "       FAIL-ROUTINE.\n"
    "           IF COMPUTED-X NOT EQUAL TO SPACE\n"
    "               DISPLAY 'COMPUTED'\n"
    "           END-IF.\n"
    "       BAIL-OUT.\n"
    "           IF COMPUTED-A NOT EQUAL TO SPACE\n"
    "               DISPLAY 'INFO'\n"
    "           END-IF.\n",
    "       01  WS-IN PIC 9.\n"
    "       01  REC-CT PIC 99 VALUE ZERO.\n"
    "       01  LINE-CT PIC 9(5) VALUE ZERO.\n"
    "       01  TEST-RESULTS.\n"
    "           02 FILLER PIC X VALUE SPACE.\n"
    "           02 P-OR-F PIC X(5) VALUE SPACE.\n"
    "       01  TEST-COMPUTED.\n"
    "           02 COMPUTED-X.\n"
    "              03 COMPUTED-A PIC X(6) VALUE SPACE.\n"
    "              03 COMPUTED-N REDEFINES COMPUTED-A PIC -9(5).\n",
)


def test_each_perform_of_shared_code_is_judged_with_its_callers_values() -> None:
    report, lines = _analyze(CCVS)
    found = _infeasible(report)
    # BAIL-OUT runs only for a passing test, and COMPUTED-A is spaces there.
    assert found[_line(lines, "IF COMPUTED-A NOT EQUAL")] == {0}
    # FAIL-ROUTINE runs after MOVE WS-IN TO COMPUTED-N: its 9 positions are
    # digits, so COMPUTED-X is never spaces there.
    assert found[_line(lines, "IF COMPUTED-X NOT EQUAL")] == {1}
    # REC-CT is 0 on the first PRINT-DETAIL and 1 on the second.
    assert found[_line(lines, "IF REC-CT NOT EQUAL")] == set()
    # The input decides the test itself.
    assert found[_line(lines, "IF WS-IN = 1")] == set()


def test_value_pruning_needs_a_run_from_the_entry_point() -> None:
    report, lines = _analyze(CCVS)
    bail = _line(lines, "IF COMPUTED-A NOT EQUAL")
    assert ("IF", bail) not in report.unreachable({}).outcomes
    found = report.unreachable({}, executed_lines=[])
    assert found.outcomes[("IF", bail)] == {0: REASON_VALUES}
    assert _line(lines, "DISPLAY 'INFO'") in found.statements


def test_a_copy_nothing_reaches_does_not_make_live_code_dependent() -> None:
    # FAIL-PARA's fall-through copy (from the unperformed SPARE-PARA) sits
    # under an input decision: it must not taint FLAG, which only MAIN
    # writes.
    source = _program(
        "       MAIN-PARA.\n"
        "           MOVE 1 TO FLAG\n"
        "           PERFORM CHECK-PARA\n"
        "           STOP RUN.\n"
        "       SPARE-PARA.\n"
        "           DISPLAY 'SPARE'.\n"
        "       CHECK-PARA.\n"
        "           ACCEPT WS-IN\n"
        "           IF WS-IN = 1\n"
        "               DISPLAY 'ONE'\n"
        "           END-IF\n"
        "           IF FLAG = 1\n"
        "               DISPLAY 'FLAG'\n"
        "           END-IF.\n",
        "       01  WS-IN PIC 9.\n       01  FLAG PIC 9 VALUE 0.\n",
    )
    report, lines = _analyze(source)
    decision = report.decision("IF", _line(lines, "IF FLAG = 1"))
    assert decision is not None and not decision.input_dependent


def test_filler_values_are_trusted_only_while_nothing_overwrites_them() -> None:
    working = (
        "       01  REC.\n"
        "           02 FILLER PIC X(2) VALUE 'AB'.\n"
        "           02 NAMED PIC X(2) VALUE 'CD'.\n"
        "       01  OTHER-REC.\n"
        "           02 FILLER PIC X(2) VALUE 'EF'.\n"
        "           02 NAMED2 PIC X(2) VALUE 'GH'.\n"
    )
    source = _program(
        "       MAIN-PARA.\n"
        "           MOVE 'XY' TO NAMED\n"
        "           IF REC = 'ABXY'\n"
        "               DISPLAY 'SAME'\n"
        "           END-IF\n"
        "           MOVE 'ZZZZ' TO OTHER-REC\n"
        "           IF OTHER-REC = 'ZZZZ'\n"
        "               DISPLAY 'Z'\n"
        "           END-IF\n"
        "           STOP RUN.\n",
        working,
    )
    report, lines = _analyze(source)
    found = _infeasible(report)
    assert found[_line(lines, "IF REC = 'ABXY'")] == {1}
    # OTHER's FILLER is overwritten, so its VALUE is not trusted -- but the
    # MOVE itself makes the whole record known again.
    assert found[_line(lines, "IF OTHER-REC = 'ZZZZ'")] == {1}


def test_a_filler_overwritten_later_is_not_trusted_earlier() -> None:
    source = _program(
        "       MAIN-PARA.\n"
        "           IF REC = 'ABCD'\n"
        "               DISPLAY 'START'\n"
        "           END-IF\n"
        "           MOVE 'QQQQ' TO REC\n"
        "           STOP RUN.\n",
        "       01  REC.\n"
        "           02 FILLER PIC X(2) VALUE 'AB'.\n"
        "           02 NAMED PIC X(2) VALUE 'CD'.\n",
    )
    report, lines = _analyze(source)
    assert _infeasible(report)[_line(lines, "IF REC = 'ABCD'")] == set()


@pytest.mark.parametrize(
    ("statements", "condition", "cut"),
    [
        ("MOVE 5 TO N1", "N1 > 4", {1}),
        ("MOVE 5 TO N1", "N1 IS POSITIVE", {1}),
        ("MOVE 0 TO N1", "N1 IS NOT ZERO", {0}),
        ("MOVE 123 TO N1", "N1 = 23", {1}),  # MOVE truncates high digits
        ("MOVE 12.5 TO N2", "N2 = 12.5", {1}),
        ("MOVE 9 TO N1 | ADD 1 TO N1", "N1 = 10", {1}),
        ("SUBTRACT 3 FROM N1", "N1 = 4", {1}),
        ("ADD N1 3 GIVING N2", "N2 = 10", {1}),
        ("SUBTRACT 1 FROM N1 GIVING N2", "N2 = 6", {1}),
        ("ADD 100 TO N1", "N1 = 7", set()),  # does not fit: not followed
        ("SUBTRACT 9 FROM N1", "N1 = 0", set()),  # negative: not followed
        ("MOVE ZERO TO T1", "T1 = '000'", {1}),
        ("MOVE ALL 'AB' TO T1", "T1 = 'ABA'", {1}),
        ("MOVE 42 TO T1", "T1 = '42'", {1}),
        ("MOVE N1 TO T1", "T1 = '07'", {1}),
        ("MOVE HIGH-VALUES TO T1", "T1 = HIGH-VALUES", {1}),
        ("MOVE QUOTE TO T1", "T1 = QUOTES", {1}),
        ("MOVE 'A' TO T1", "T1 = 'A' AND N1 = 7", {1}),
        ("MOVE 'A' TO T1", "T1 = 'B' OR N1 = 7", {1}),
        ("MOVE 'A' TO T1", "NOT T1 = 'A'", {0}),
        ("MOVE 'A' TO T1", "T1 = 'A' OR WS-IN = 1", {1}),
        ("MOVE 'A' TO T1", "T1 = 'B' AND WS-IN = 1", {0}),
        ("MOVE 'A' TO T1", "T1 = 'B' OR WS-IN = 1", set()),
        ("MOVE 'A' TO T1", "T1 > 'B'", set()),  # collating sequence
        ("MOVE 'A' TO T1", "T1 = 1", set()),
        ("MOVE 'Y' TO T1", "IS-YES", {1}),
        ("MOVE 'N' TO T1", "IS-YES", {0}),
        ("MOVE 3 TO N1", "IN-RANGE", {1}),
        ("MOVE 9 TO N1", "IN-RANGE", {0}),
        ("MOVE 'A' TO T1 OF GRP", "T1 IN GRP = 'A'", {1}),
        ("MOVE 'AB' TO T1 (1:2)", "T1 = 'AB'", set()),
        ("MOVE 7 TO TAB-ENTRY (1)", "N1 = 7", {1}),
        ("MOVE 1 TO PACKED", "PACKED = 1", set()),
        ("MOVE CORRESPONDING GRP TO GRP2", "T9 = ' '", set()),
        ("INITIALIZE GRP", "T1 = ' '", set()),
        ("ACCEPT N1", "N1 = 7", set()),
        ("MOVE 'A' TO T1", "T1 = 'B' OR 'A'", set()),  # abbreviated
        ("MOVE 'A' TO T1", "T1 = 'B' OR T1 = 'C'", set()),  # subject twice
        ("MOVE 'A' TO T1", "T1 = 'A  X'", set()),  # literal past the item
        ("MOVE 'A' TO T1", "T1 = 'A    '", {1}),
    ],
)
def test_statements_and_conditions_the_pass_follows(
    statements: str, condition: str, cut: set[int]
) -> None:
    body = "".join(f"           {s}\n" for s in statements.split(" | "))
    source = _program(
        "       MAIN-PARA.\n"
        "           ACCEPT WS-IN\n" + body + f"           IF {condition}\n"
        "               DISPLAY 'Y'\n"
        "           END-IF\n"
        "           STOP RUN.\n",
        "       01  WS-IN PIC 9.\n"
        "       01  N1 PIC 99 VALUE 7.\n"
        "           88 IN-RANGE VALUE 1 THRU 5.\n"
        "       01  N2 PIC 99V9 VALUE 0.\n"
        "       01  GRP.\n"
        "           02 T1 PIC X(3) VALUE SPACE.\n"
        "              88 IS-YES VALUE 'Y'.\n"
        "       01  GRP2.\n"
        "           02 T9 PIC X(3) VALUE SPACE.\n"
        "       01  PACKED PIC 9(3) COMP-3 VALUE 0.\n"
        "       01  TAB.\n"
        "           02 TAB-ENTRY PIC 9 OCCURS 3 TIMES.\n",
    )
    report, lines = _analyze(source)
    assert _infeasible(report).get(_line(lines, f"IF {condition}"), set()) == cut


def test_states_merge_at_a_loop_and_the_pass_terminates() -> None:
    source = _program(
        "       MAIN-PARA.\n"
        "           PERFORM VARYING I FROM 1 BY 1 UNTIL I > 50\n"
        "               ADD 1 TO CT\n"
        "               IF FLAG = 'Y'\n"
        "                   DISPLAY 'NEVER'\n"
        "               END-IF\n"
        "               IF CT = 3\n"
        "                   DISPLAY 'THREE'\n"
        "               END-IF\n"
        "           END-PERFORM\n"
        "           STOP RUN.\n",
        "       01  I PIC 99 VALUE 0.\n"
        "       01  CT PIC 999 VALUE 0.\n"
        "       01  FLAG PIC X VALUE 'N'.\n",
    )
    report, lines = _analyze(source)
    found = _infeasible(report)
    assert found[_line(lines, "IF FLAG = 'Y'")] == {0}
    assert found[_line(lines, "IF CT = 3")] == set()


def test_edited_receiver_from_a_numeric_item_holds_digits() -> None:
    source = _program(
        "       MAIN-PARA.\n"
        "           ACCEPT WS-IN\n"
        "           MOVE WS-IN TO EDITED\n"
        "           IF EDITED = SPACES\n"
        "               DISPLAY 'BLANK'\n"
        "           END-IF\n"
        "           IF EDITED = '  5'\n"
        "               DISPLAY 'FIVE'\n"
        "           END-IF\n"
        "           MOVE WS-IN TO BWZ\n"
        "           IF BWZ = SPACES\n"
        "               DISPLAY 'BWZ'\n"
        "           END-IF\n"
        "           STOP RUN.\n",
        "       01  WS-IN PIC 9.\n"
        "       01  EDITED PIC ZZ9.\n"
        "       01  BWZ PIC ZZ9 BLANK WHEN ZERO.\n",
    )
    report, lines = _analyze(source)
    found = _infeasible(report)
    assert found[_line(lines, "IF EDITED = SPACES")] == {0}
    assert found[_line(lines, "IF EDITED = '  5'")] == set()
    assert found[_line(lines, "IF BWZ = SPACES")] == set()


def test_digits_survive_arithmetic_on_unknown_values() -> None:
    source = _program(
        "       MAIN-PARA.\n"
        "           ACCEPT WS-IN\n"
        "           MOVE ZERO TO CT\n"
        "           IF WS-IN = 1\n"
        "               ADD 1 TO CT\n"
        "           END-IF\n"
        "           ADD CT TO CT2\n"
        "           ADD CT 1 GIVING CT3\n"
        "           MOVE CT2 TO TXT\n"
        "           IF TXT = SPACES\n"
        "               DISPLAY 'BLANK'\n"
        "           END-IF\n"
        "           MOVE CT3 TO TXT\n"
        "           IF TXT = 'AB'\n"
        "               DISPLAY 'AB'\n"
        "           END-IF\n"
        "           STOP RUN.\n",
        "       01  WS-IN PIC 9.\n"
        "       01  CT PIC 99 VALUE 0.\n"
        "       01  CT2 PIC 99 VALUE 0.\n"
        "       01  CT3 PIC 99 VALUE 0.\n"
        "       01  TXT PIC XX VALUE SPACES.\n",
    )
    report, lines = _analyze(source)
    found = _infeasible(report)
    assert found[_line(lines, "IF TXT = SPACES")] == {0}
    assert found[_line(lines, "IF TXT = 'AB'")] == {0}


@pytest.mark.parametrize(
    "case",
    [
        "entry",
        "declaratives",
        "address",
        "external",
        "extra",
        "budget",
        "comparisons",
        "sync",
    ],
)
def test_what_the_pass_does_not_trust(
    case: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    working = "       01  FLAG PIC X VALUE 'N'.\n       01  PTR USAGE POINTER.\n"
    main = (
        "           IF FLAG = 'Y'\n"
        "               DISPLAY 'YES'\n"
        "           END-IF\n"
        "           STOP RUN.\n"
    )
    procedure = "       MAIN-PARA.\n" + main
    extra = ""
    kwargs: dict[str, object] = {}
    if case == "entry":
        procedure = "       MAIN-PARA.\n           ENTRY 'ALT'\n" + main
    elif case == "declaratives":
        extra = (
            "       ENVIRONMENT DIVISION.\n"
            "       INPUT-OUTPUT SECTION.\n"
            "       FILE-CONTROL.\n"
            "           SELECT IN-FILE ASSIGN TO INDD.\n"
        )
        procedure = (
            "       DECLARATIVES.\n"
            "       ERR SECTION.\n"
            "           USE AFTER ERROR PROCEDURE ON IN-FILE.\n"
            "       ERR-PARA.\n"
            "           MOVE 'Y' TO FLAG.\n"
            "       END DECLARATIVES.\n"
            "       MAIN SECTION.\n"
            "       MAIN-PARA.\n"
            "           OPEN INPUT IN-FILE\n" + main
        )
    elif case == "address":
        procedure = "       MAIN-PARA.\n           SET PTR TO ADDRESS OF FLAG\n" + main
    elif case == "external":
        working = "       01  FLAG PIC X VALUE 'N' EXTERNAL.\n"
    elif case == "extra":
        kwargs["extra_inputs"] = ["FLAG"]
    elif case == "budget":
        monkeypatch.setattr(_values, "MAX_STEPS", 1)
    elif case == "comparisons":
        monkeypatch.setattr(_values, "MAX_COMPARISONS", -1)
    elif case == "sync":
        working = "       01  REC.\n           02 FLAG PIC X VALUE 'N' SYNC.\n"
    source = _program(procedure, working, extra)
    if case == "declaratives":
        source = source.replace(
            "       DATA DIVISION.\n",
            "       DATA DIVISION.\n       FILE SECTION.\n"
            "       FD  IN-FILE.\n       01  IN-REC PIC X(10).\n",
        )
    report, lines = _analyze(source, **kwargs)
    assert not _infeasible(report).get(_line(lines, "IF FLAG = 'Y'"))


def test_a_recursive_perform_gives_up() -> None:
    source = _program(
        "       MAIN-PARA.\n"
        "           PERFORM LOOP-PARA\n"
        "           STOP RUN.\n"
        "       LOOP-PARA.\n"
        "           IF FLAG = 'Y'\n"
        "               DISPLAY 'Y'\n"
        "           END-IF\n"
        "           PERFORM LOOP-PARA.\n",
        "       01  FLAG PIC X VALUE 'N'.\n",
    )
    report, _ = _analyze(source)
    assert report._infeasible == {}


def test_helpers() -> None:
    assert _values._expand_picture("-9(3).99") == "-999.99"
    assert _values._expand_picture("9(3)V99") == "99999"
    assert _values._expand_picture("ZZ9CR") == "ZZ9CR"
    assert _values._expand_picture("9(X)") is None
    assert _values._expand_picture("N(3)") is None
    assert _values._text_fill("ALL SPACES", 3) == "   "
    assert _values._text_fill("ALL ''", 3) is None
    assert _values._text_fill("WS-NAME", 3) is None
    assert _values._render_num(_values.Decimal("1.25"), 3, 1, exact=False) == "012"
    assert _values._render_num(_values.Decimal("1.25"), 3, 1, exact=True) is None
    assert _values._text_equal("A" + _values.DIGIT, "AB") is False
    assert _values._text_equal("A" + _values.DIGIT, "A1") is None
    assert _values._compare("EQUAL", ("zero", "0"), ("num", _values.Decimal(0)))
    assert _values._compare("EQUAL", ("fill", " "), ("text", "  ")) is True
    assert _values._compare("EQUAL", ("fill", " "), ("text", "")) is None
    assert _values._compare("EQUAL", ("fill", " "), ("fill", " ")) is None


def test_a_variable_records_length_is_set_by_its_read() -> None:
    source = (
        "       IDENTIFICATION DIVISION.\n"
        "       PROGRAM-ID. P.\n"
        "       ENVIRONMENT DIVISION.\n"
        "       INPUT-OUTPUT SECTION.\n"
        "       FILE-CONTROL.\n"
        "           SELECT IN-FILE ASSIGN TO INDD.\n"
        "       DATA DIVISION.\n"
        "       FILE SECTION.\n"
        "       FD  IN-FILE\n"
        "           RECORD VARYING DEPENDING ON REC-LEN.\n"
        "       01  IN-REC PIC X(10).\n"
        "       WORKING-STORAGE SECTION.\n"
        "       01  REC-LEN PIC 99 VALUE 0.\n"
        "       PROCEDURE DIVISION.\n"
        "       MAIN-PARA.\n"
        "           OPEN INPUT IN-FILE\n"
        "           MOVE 5 TO REC-LEN\n"
        "           READ IN-FILE\n"
        "           IF REC-LEN = 5\n"
        "               DISPLAY 'FIVE'\n"
        "           END-IF\n"
        "           STOP RUN.\n"
    )
    report, lines = _analyze(source)
    line = _line(lines, "IF REC-LEN = 5")
    assert _infeasible(report)[line] == set()
    decision = report.decision("IF", line)
    assert decision is not None and decision.input_dependent
