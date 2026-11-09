"""Bug-pattern lint rules (analysis/bug_patterns.py) and lint's call-check rule.

Each rule gets a program that holds the bug and one that holds the look-alike
the rule must stay quiet on, so a rule that starts over-reporting fails here
before it floods a real codebase.
"""

from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from cobolparser import parse_cobol
from cobolparser.analysis.bug_patterns import (
    BUG_PATTERN_DESCRIPTIONS,
    BUG_PATTERN_RULES,
    BugPatternAnalyzer,
)
from cobolparser.analysis.call_interface import CalleeResolver, find_callee_file
from cobolparser.analysis.lint import (
    ALL_RULES,
    CALL_CHECK_RULE,
    RULES,
    LintAnalyzer,
    LintReport,
    add_call_check_findings,
)
from cobolparser.analysis.sarif import RULE_DESCRIPTIONS
from cobolparser.models.statements.control import IfStatement


def _program(data: str, procedure: str, *, env: str = "", name: str = "T") -> str:
    def block(text: str, indent: int) -> str:
        return textwrap.indent(textwrap.dedent(text).strip("\n"), " " * indent)

    parts = [
        "       IDENTIFICATION DIVISION.",
        f"       PROGRAM-ID. {name}.",
    ]
    if env:
        parts += [
            "       ENVIRONMENT DIVISION.",
            "       INPUT-OUTPUT SECTION.",
            "       FILE-CONTROL.",
            block(env, 11),
        ]
    parts += ["       DATA DIVISION.", block(data, 7), "       PROCEDURE DIVISION."]
    parts.append(block(procedure, 7))
    return "\n".join(parts) + "\n"


def _findings(source: str, rule: str) -> list:
    result = parse_cobol(source)
    assert result.ast is not None, result.errors
    return BugPatternAnalyzer([rule]).analyze(result.ast).findings


def _kinds(source: str, rule: str) -> list[str]:
    return [f.kind for f in _findings(source, rule)]


WS = """\
WORKING-STORAGE SECTION.
01  WS-LONG       PIC X(20).
01  WS-SHORT      PIC X(5).
01  WS-BIG        PIC 9(9).
01  WS-SMALL      PIC 9(3).
01  WS-WIDE       PIC 9(9).
01  WS-CONST      PIC X(8) VALUE 'ABCDE'.
01  WS-FLAG       PIC X VALUE 'N'.
"""


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def test_every_bug_rule_is_a_lint_rule_with_a_description():
    for rule in BUG_PATTERN_RULES:
        assert rule in RULES
        assert rule in BUG_PATTERN_DESCRIPTIONS
        assert RULE_DESCRIPTIONS[rule] == BUG_PATTERN_DESCRIPTIONS[rule]
    assert CALL_CHECK_RULE in ALL_RULES
    assert CALL_CHECK_RULE not in RULES  # run by the caller, like line-length
    assert RULE_DESCRIPTIONS[CALL_CHECK_RULE]


def test_unknown_rule_is_rejected():
    with pytest.raises(ValueError):
        BugPatternAnalyzer(["no-such-rule"])


def test_program_without_procedure_division_is_quiet():
    source = (
        "       IDENTIFICATION DIVISION.\n       PROGRAM-ID. T.\n"
        "       DATA DIVISION.\n       WORKING-STORAGE SECTION.\n"
        "       01 A PIC X.\n"
    )
    result = parse_cobol(source)
    assert BugPatternAnalyzer().analyze(result.ast).findings == []


# ---------------------------------------------------------------------------
# truncation
# ---------------------------------------------------------------------------


class TestTruncation:
    def test_numeric_move_losing_digits_is_a_warning(self):
        found = _findings(
            _program(WS, "MOVE WS-BIG TO WS-SMALL\nGOBACK."), "truncation"
        )
        assert [(f.kind, f.severity) for f in found] == [
            ("MOVE_LOSES_DIGITS", "warning")
        ]
        assert found[0].symbol == "WS-SMALL"
        assert "high-order digits" in found[0].message

    def test_variable_text_move_is_info(self):
        found = _findings(
            _program(WS, "MOVE WS-LONG TO WS-SHORT\nGOBACK."), "truncation"
        )
        assert [(f.kind, f.severity) for f in found] == [
            ("MOVE_LOSES_CHARACTERS", "info")
        ]

    def test_literal_too_long_is_a_warning(self):
        found = _findings(
            _program(WS, "MOVE 'TOO LONG TEXT' TO WS-SHORT\nGOBACK."), "truncation"
        )
        assert [(f.kind, f.severity) for f in found] == [
            ("MOVE_LOSES_CHARACTERS", "warning")
        ]

    def test_constant_judged_by_its_value(self):
        # PIC X(8) VALUE 'ABCDE' fits a 5-byte receiver.
        assert (
            _kinds(_program(WS, "MOVE WS-CONST TO WS-SHORT\nGOBACK."), "truncation")
            == []
        )

    def test_constant_that_is_changed_is_a_variable(self):
        source = _program(
            WS, "MOVE WS-LONG TO WS-CONST\nMOVE WS-CONST TO WS-SHORT\nGOBACK."
        )
        assert "MOVE_LOSES_CHARACTERS" in _kinds(source, "truncation")

    def test_fitting_moves_are_quiet(self):
        source = _program(
            WS,
            """\
            MOVE WS-SMALL TO WS-BIG
            MOVE WS-SHORT TO WS-LONG
            MOVE 'ABC' TO WS-SHORT
            MOVE 123 TO WS-SMALL
            MOVE 0000123 TO WS-SMALL
            MOVE SPACES TO WS-SHORT
            MOVE WS-LONG(1:5) TO WS-SHORT
            GOBACK.
            """,
        )
        assert _kinds(source, "truncation") == []

    def test_numeric_literal_too_big(self):
        assert _kinds(_program(WS, "MOVE 1000 TO WS-SMALL\nGOBACK."), "truncation") == [
            "MOVE_LOSES_DIGITS"
        ]

    def test_redefined_sender_is_not_judged_by_digits(self):
        data = """\
        WORKING-STORAGE SECTION.
        01  TWO-BYTES-BINARY  PIC 9(4) BINARY.
        01  TWO-BYTES-ALPHA REDEFINES TWO-BYTES-BINARY.
            05 TWO-BYTES-LEFT  PIC X.
            05 TWO-BYTES-RIGHT PIC X.
        01  IO-STATUS-0403    PIC 999.
        """
        source = _program(data, "MOVE TWO-BYTES-BINARY TO IO-STATUS-0403\nGOBACK.")
        assert _kinds(source, "truncation") == []

    def test_alphanumeric_to_numeric_is_left_to_move_type_check(self):
        assert (
            _kinds(_program(WS, "MOVE WS-LONG TO WS-SMALL\nGOBACK."), "truncation")
            == []
        )

    def test_ambiguous_name_is_skipped(self):
        data = """\
        WORKING-STORAGE SECTION.
        01  REC-A.
            05 AMT PIC 9(9).
        01  REC-B.
            05 AMT PIC 9(9).
        01  SMALL PIC 9(3).
        """
        assert _kinds(_program(data, "MOVE AMT TO SMALL\nGOBACK."), "truncation") == []
        qualified = _program(data, "MOVE AMT OF REC-A TO SMALL\nGOBACK.")
        assert _kinds(qualified, "truncation") == ["MOVE_LOSES_DIGITS"]

    def test_add_into_smaller_field_without_size_error(self):
        source = _program(WS, "ADD WS-BIG TO WS-SMALL\nGOBACK.")
        found = _findings(source, "truncation")
        assert [f.kind for f in found] == ["ARITHMETIC_LOSES_DIGITS"]
        assert "ON SIZE ERROR" in found[0].message

    def test_add_giving_and_subtract(self):
        source = _program(
            WS,
            """\
            ADD WS-BIG WS-SMALL GIVING WS-SMALL
            SUBTRACT WS-BIG FROM WS-SMALL
            GOBACK.
            """,
        )
        assert _kinds(source, "truncation") == [
            "ARITHMETIC_LOSES_DIGITS",
            "ARITHMETIC_LOSES_DIGITS",
        ]

    def test_size_error_phrase_and_literals_are_quiet(self):
        source = _program(
            WS,
            """\
            ADD WS-BIG TO WS-SMALL ON SIZE ERROR DISPLAY 'X' END-ADD
            ADD 1000 TO WS-SMALL
            ADD WS-SMALL TO WS-BIG
            ADD WS-BIG TO WS-WIDE
            GOBACK.
            """,
        )
        assert _kinds(source, "truncation") == []

    def test_compute_sum_and_other_expressions(self):
        source = _program(
            WS,
            """\
            COMPUTE WS-SMALL = WS-BIG + 1
            COMPUTE WS-SMALL = WS-BIG / 1000
            GOBACK.
            """,
        )
        found = _findings(source, "truncation")
        assert [f.kind for f in found] == ["ARITHMETIC_LOSES_DIGITS"]
        assert found[0].message.startswith("COMPUTE")


# ---------------------------------------------------------------------------
# subscript-range
# ---------------------------------------------------------------------------


TABLES = """\
WORKING-STORAGE SECTION.
01  WS-TABLE.
    05 WS-ENT     PIC X(4) OCCURS 10 TIMES.
01  WS-GRID.
    05 WS-ROW     OCCURS 5 TIMES.
       10 WS-CELL PIC X OCCURS 3 TIMES.
01  WS-I          PIC 99 VALUE 1.
01  WS-OUT        PIC X(4).
"""


class TestSubscriptRange:
    def test_literal_past_bound_is_an_error(self):
        found = _findings(
            _program(TABLES, "MOVE 'X' TO WS-ENT(11)\nGOBACK."), "subscript-range"
        )
        assert [(f.kind, f.severity) for f in found] == [
            ("SUBSCRIPT_OUT_OF_RANGE", "error")
        ]
        assert "11 is outside OCCURS 1 to 10" in found[0].message

    def test_zero_and_condition_operands(self):
        source = _program(
            TABLES,
            """\
            IF WS-ENT(0) = SPACES
                DISPLAY WS-ENT (12)
            END-IF
            GOBACK.
            """,
        )
        assert _kinds(source, "subscript-range") == [
            "SUBSCRIPT_OUT_OF_RANGE",
            "SUBSCRIPT_OUT_OF_RANGE",
        ]

    def test_two_dimensions(self):
        source = _program(TABLES, "MOVE 'A' TO WS-CELL(5, 4)\nGOBACK.")
        found = _findings(source, "subscript-range")
        assert len(found) == 1 and "subscript 2 4" in found[0].message

    def test_in_range_variable_and_refmod_are_quiet(self):
        source = _program(
            TABLES,
            """\
            MOVE WS-ENT(10) TO WS-OUT
            MOVE WS-ENT(WS-I) TO WS-OUT
            MOVE WS-ENT(WS-I + 1) TO WS-OUT
            MOVE WS-OUT(1:4) TO WS-ENT(1)
            MOVE WS-CELL(5, 3) TO WS-OUT
            MOVE WS-CELL(5) TO WS-OUT
            DISPLAY 'WS-ENT(99)'
            GOBACK.
            """,
        )
        assert _kinds(source, "subscript-range") == []


# ---------------------------------------------------------------------------
# next-sentence
# ---------------------------------------------------------------------------


class TestNextSentence:
    def test_inside_end_if_with_statements_after(self):
        source = _program(
            WS,
            """\
            IF WS-FLAG = 'Y'
                NEXT SENTENCE
            END-IF
            DISPLAY 'SKIPPED'.
            GOBACK.
            """,
        )
        found = _findings(source, "next-sentence")
        assert [f.kind for f in found] == ["NEXT_SENTENCE_IN_END_IF"]
        assert "DISPLAY" in found[0].message

    def test_nested_inner_if_is_last_in_outer(self):
        source = _program(
            WS,
            """\
            IF WS-FLAG = 'Y'
                IF WS-SHORT = SPACES
                    NEXT SENTENCE
                END-IF
            END-IF
            DISPLAY 'SKIPPED'.
            GOBACK.
            """,
        )
        assert _kinds(source, "next-sentence") == ["NEXT_SENTENCE_IN_END_IF"]

    def test_in_else_branch(self):
        source = _program(
            WS,
            """\
            IF WS-FLAG = 'Y'
                DISPLAY 'Y'
            ELSE
                NEXT SENTENCE
            END-IF
            DISPLAY 'SKIPPED'.
            GOBACK.
            """,
        )
        assert _kinds(source, "next-sentence") == ["NEXT_SENTENCE_IN_END_IF"]

    def test_period_terminated_if_is_the_idiom(self):
        source = _program(
            WS,
            """\
            IF WS-FLAG = 'Y'
                NEXT SENTENCE
            ELSE
                DISPLAY 'N'.
            DISPLAY 'NEXT'.
            GOBACK.
            """,
        )
        assert _kinds(source, "next-sentence") == []

    def test_end_if_followed_by_period_skips_nothing(self):
        source = _program(
            WS,
            """\
            IF WS-FLAG = 'Y'
                NEXT SENTENCE
            END-IF.
            DISPLAY 'NEXT'.
            GOBACK.
            """,
        )
        assert _kinds(source, "next-sentence") == []

    def test_parser_records_how_an_if_ended(self):
        source = _program(
            WS,
            """\
            IF WS-FLAG = 'Y' DISPLAY 'A' END-IF
            IF WS-FLAG = 'N' DISPLAY 'B' END-IF.
            IF WS-FLAG = 'X' DISPLAY 'C'.
            GOBACK.
            """,
        )
        ifs = [
            s
            for s in parse_cobol(source).ast.get_all_statements()
            if isinstance(s, IfStatement)
        ]
        assert [(i.ended_by_end_if, i.period_after_end_if) for i in ifs] == [
            (True, False),
            (True, True),
            (False, False),
        ]


# ---------------------------------------------------------------------------
# perform-range
# ---------------------------------------------------------------------------


class TestPerformRange:
    def test_thru_backwards(self):
        source = _program(
            WS,
            """\
            MAIN-PARA.
                PERFORM B-PARA THRU A-PARA
                STOP RUN.
            A-PARA.
                DISPLAY 'A'.
            B-PARA.
                DISPLAY 'B'.
            """,
        )
        found = _findings(source, "perform-range")
        assert [(f.kind, f.severity) for f in found] == [
            ("PERFORM_THRU_BACKWARDS", "error")
        ]

    def test_go_to_out_of_simple_perform(self):
        source = _program(
            WS,
            """\
            MAIN-PARA.
                PERFORM P1
                STOP RUN.
            P1.
                IF WS-FLAG = 'Y'
                    GO TO P1-EXIT
                END-IF.
            P1-EXIT.
                EXIT.
            """,
        )
        found = _findings(source, "perform-range")
        assert [f.kind for f in found] == ["GO_TO_OUT_OF_PERFORM"]
        assert found[0].symbol == "P1-EXIT"

    def test_go_to_inside_thru_range_is_fine(self):
        source = _program(
            WS,
            """\
            MAIN-PARA.
                PERFORM P1 THRU P1-EXIT
                STOP RUN.
            P1.
                IF WS-FLAG = 'Y'
                    GO TO P1-EXIT
                END-IF.
            P1-EXIT.
                EXIT.
            """,
        )
        assert _kinds(source, "perform-range") == []

    def test_go_to_a_terminating_paragraph_is_an_exit(self):
        source = _program(
            WS,
            """\
            MAIN-PARA.
                PERFORM P1 THRU P1-EXIT
                STOP RUN.
            P1.
                IF WS-FLAG = 'Y'
                    GO TO ABEND-PARA
                END-IF.
            P1-EXIT.
                EXIT.
            ABEND-PARA.
                DISPLAY 'FATAL'
                PERFORM CLOSE-DOWN.
            CLOSE-DOWN.
                GOBACK.
            """,
        )
        assert _kinds(source, "perform-range") == []

    def test_section_range(self):
        source = _program(
            WS,
            """\
            MAIN-SEC SECTION.
            M1.
                PERFORM A-SEC
                STOP RUN.
            A-SEC SECTION.
            A1.
                GO TO A-EXIT.
            A-EXIT.
                EXIT.
            B-SEC SECTION.
            B1.
                DISPLAY 'B'.
            """,
        )
        assert _kinds(source, "perform-range") == []

    def test_falls_into_performed_paragraph(self):
        source = _program(
            WS,
            """\
            MAIN-PARA.
                PERFORM INIT-PARA
                DISPLAY 'DONE'.
            INIT-PARA.
                DISPLAY 'INIT'.
            """,
        )
        found = _findings(source, "perform-range")
        assert [f.kind for f in found] == ["FALLS_INTO_PERFORMED"]
        assert found[0].symbol == "MAIN-PARA"

    def test_main_line_that_ends_is_quiet(self):
        for ending in (
            "STOP RUN.",
            "GOBACK.",
            "GO TO END-PARA.",
            "PERFORM END-PARA.",
            "IF WS-FLAG = 'Y' STOP RUN ELSE GOBACK END-IF.",
        ):
            source = _program(
                WS,
                f"""\
                MAIN-PARA.
                    PERFORM INIT-PARA
                    {ending}
                INIT-PARA.
                    DISPLAY 'INIT'.
                END-PARA.
                    STOP RUN.
                """,
            )
            assert _kinds(source, "perform-range") == [], ending

    def test_perform_n_times_then_into_it_is_deliberate(self):
        source = _program(
            WS,
            """\
            OPEN-FILES.
                PERFORM INIT-ONE 9 TIMES.
            INIT-ONE.
                DISPLAY 'X'.
            INIT-EXIT.
                STOP RUN.
            """,
        )
        assert _kinds(source, "perform-range") == []


# ---------------------------------------------------------------------------
# file-status
# ---------------------------------------------------------------------------


FILE_DATA = """\
FILE SECTION.
FD  IN-FILE.
01  IN-REC            PIC X(80).
WORKING-STORAGE SECTION.
01  WS-STATUS         PIC XX.
    88 WS-OK          VALUE '00'.
"""
FILE_ENV = """\
SELECT IN-FILE ASSIGN TO INFILE
    FILE STATUS IS WS-STATUS.
"""


class TestFileStatus:
    def test_status_never_read(self):
        source = _program(
            FILE_DATA,
            "OPEN INPUT IN-FILE\nREAD IN-FILE\nCLOSE IN-FILE\nGOBACK.",
            env=FILE_ENV,
        )
        found = _findings(source, "file-status")
        assert [f.kind for f in found] == ["FILE_STATUS_NOT_CHECKED"]
        assert found[0].symbol == "IN-FILE"

    @pytest.mark.parametrize(
        "check",
        [
            "IF WS-STATUS NOT = '00' DISPLAY 'ERR' END-IF",
            "IF NOT WS-OK DISPLAY 'ERR' END-IF",
            "DISPLAY WS-STATUS",
            "CALL 'ERRLOG' USING WS-STATUS",
        ],
    )
    def test_any_read_counts(self, check):
        source = _program(
            FILE_DATA,
            f"OPEN INPUT IN-FILE\n{check}\nCLOSE IN-FILE\nGOBACK.",
            env=FILE_ENV,
        )
        assert _kinds(source, "file-status") == []

    def test_file_without_io_is_quiet(self):
        source = _program(FILE_DATA, "GOBACK.", env=FILE_ENV)
        assert _kinds(source, "file-status") == []

    def test_declaratives_handle_errors(self):
        source = _program(
            FILE_DATA,
            """\
            DECLARATIVES.
            IN-ERR SECTION.
                USE AFTER ERROR PROCEDURE ON IN-FILE.
            IN-ERR-PARA.
                DISPLAY 'IO ERROR'.
            END DECLARATIVES.
            MAIN SECTION.
            M1.
                OPEN INPUT IN-FILE
                GOBACK.
            """,
            env=FILE_ENV,
        )
        assert _kinds(source, "file-status") == []


# ---------------------------------------------------------------------------
# uninitialized
# ---------------------------------------------------------------------------


NUMS = """\
WORKING-STORAGE SECTION.
01  WS-UNSET   PIC 9(4).
01  WS-COUNT   PIC 9(4) VALUE 0.
01  WS-GROUP.
    05 WS-PART PIC 9(4).
01  WS-TEXT    PIC X(4).
01  WS-PTR     USAGE POINTER.
"""


class TestUninitialized:
    def test_numeric_read_never_set(self):
        found = _findings(
            _program(NUMS, "ADD WS-UNSET TO WS-COUNT\nGOBACK."), "uninitialized"
        )
        assert [f.kind for f in found] == ["NUMERIC_NEVER_SET"]
        assert found[0].symbol == "WS-UNSET"
        assert found[0].location.line > 0

    @pytest.mark.parametrize(
        "setter",
        [
            "MOVE 1 TO WS-UNSET",
            "INITIALIZE WS-UNSET",
            "ACCEPT WS-UNSET",
            "CALL 'SUBPROG' USING WS-UNSET",
            "SET WS-PTR TO ADDRESS OF WS-UNSET",
        ],
    )
    def test_any_store_counts(self, setter):
        source = _program(NUMS, f"{setter}\nADD WS-UNSET TO WS-COUNT\nGOBACK.")
        assert _kinds(source, "uninitialized") == []

    def test_group_store_counts(self):
        source = _program(
            NUMS, "MOVE SPACES TO WS-GROUP\nADD WS-PART TO WS-COUNT\nGOBACK."
        )
        assert _kinds(source, "uninitialized") == []
        unset = _program(NUMS, "ADD WS-PART TO WS-COUNT\nGOBACK.")
        assert _kinds(unset, "uninitialized") == ["NUMERIC_NEVER_SET"]

    def test_alphanumeric_value_and_unread_items_are_quiet(self):
        source = _program(NUMS, "DISPLAY WS-TEXT WS-COUNT\nGOBACK.")
        assert _kinds(source, "uninitialized") == []

    def test_linkage_items_are_not_judged(self):
        data = """\
        LINKAGE SECTION.
        01  LS-AMT PIC 9(4).
        """
        source = _program(data, "DISPLAY LS-AMT\nGOBACK.").replace(
            "PROCEDURE DIVISION.", "PROCEDURE DIVISION USING LS-AMT."
        )
        assert _kinds(source, "uninitialized") == []


# ---------------------------------------------------------------------------
# obsolete-verb
# ---------------------------------------------------------------------------


def test_alter_is_reported():
    source = _program(
        WS,
        """\
        MAIN-PARA.
            ALTER SWITCH-PARA TO PROCEED TO OUT-PARA
            GO TO SWITCH-PARA.
        SWITCH-PARA.
            GO TO MAIN-PARA.
        OUT-PARA.
            STOP RUN.
        """,
    )
    found = _findings(source, "obsolete-verb")
    assert [(f.kind, f.symbol) for f in found] == [("ALTER", "SWITCH-PARA")]


# ---------------------------------------------------------------------------
# Through LintAnalyzer
# ---------------------------------------------------------------------------


MISS = _program(
    """\
    WORKING-STORAGE SECTION.
    01  WS-LONG    PIC X(20) VALUE 'ABCDEFGHIJKLMNOPQRST'.
    01  WS-SHORT   PIC X(5).
    01  WS-TABLE.
        05 WS-ENT  PIC X(4) OCCURS 10 TIMES.
    01  WS-UNSET   PIC 9(4).
    01  WS-COUNT   PIC 9(4) VALUE 0.
    """,
    """\
    MAIN-PARA.
        MOVE 'TRUNCATED TEXT' TO WS-SHORT
        MOVE 'X' TO WS-ENT(11)
        ADD WS-UNSET TO WS-COUNT
        STOP RUN.
    """,
)


def test_lint_runs_the_bug_rules_by_default():
    report = LintAnalyzer().analyze(parse_cobol(MISS).ast)
    by_rule = {f.rule for f in report.findings}
    assert {"truncation", "subscript-range", "uninitialized"} <= by_rule
    for rule in BUG_PATTERN_RULES:
        assert rule in report.rules_run


def test_lint_rule_selection_runs_one_bug_rule():
    report = LintAnalyzer(["subscript-range"]).analyze(parse_cobol(MISS).ast)
    assert {f.rule for f in report.findings} == {"subscript-range"}
    assert report.rules_run == ["subscript-range"]


def test_lint_covers_contained_programs():
    outer = MISS.replace("STOP RUN.", "GOBACK.")
    inner = _program(
        "WORKING-STORAGE SECTION.\n01 INNER-T.\n    05 INNER-E PIC X OCCURS 2.",
        "MOVE 'A' TO INNER-E(3)\nGOBACK.",
        name="INNER",
    )
    source = outer + inner + "       END PROGRAM INNER.\n       END PROGRAM T.\n"
    report = LintAnalyzer(["subscript-range"]).analyze(parse_cobol(source).ast)
    assert {f.symbol for f in report.findings} == {"WS-ENT", "INNER-E"}


# ---------------------------------------------------------------------------
# call-check through lint
# ---------------------------------------------------------------------------


CALLER = _program(
    """\
    WORKING-STORAGE SECTION.
    01  WS-DATE     PIC X(8).
    """,
    "CALL 'DATESUB' USING WS-DATE\nCALL 'NOWHERE' USING WS-DATE\nGOBACK.",
    name="CALLER",
)
CALLEE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. DATESUB.
       DATA DIVISION.
       LINKAGE SECTION.
       01  LS-DATE     PIC X(10).
       PROCEDURE DIVISION USING LS-DATE.
           GOBACK.
"""


def test_find_callee_file(tmp_path):
    (tmp_path / "datesub.cbl").write_text(CALLEE)
    assert find_callee_file("DATESUB", [str(tmp_path)]) == str(tmp_path / "datesub.cbl")
    assert find_callee_file("NOPE", [str(tmp_path), str(tmp_path / "missing")]) is None


def test_add_call_check_findings(tmp_path):
    (tmp_path / "DATESUB.cbl").write_text(CALLEE)
    caller = tmp_path / "CALLER.cbl"
    caller.write_text(CALLER)
    resolver = CalleeResolver([str(tmp_path)])
    report = add_call_check_findings(
        LintReport(), str(caller), parse_cobol(CALLER).ast, resolver
    )
    assert [(f.rule, f.severity, f.kind, f.symbol) for f in report.findings] == [
        ("call-check", "error", "LENGTH", "DATESUB")
    ]
    assert report.findings[0].location.line > 0
    assert not report.findings[0].column_known
    assert "call-check" in report.rules_run
    assert any("NOWHERE" in c for c in report.caveats)
    # The callee is parsed once per resolver, however many callers ask.
    add_call_check_findings(
        LintReport(), str(caller), parse_cobol(CALLER).ast, resolver
    )
    assert len(resolver._parsed) == 1


def test_callee_that_does_not_parse_is_a_caveat(tmp_path):
    (tmp_path / "DATESUB.cbl").write_bytes(b"")
    report = add_call_check_findings(
        LintReport(),
        "CALLER.cbl",
        parse_cobol(CALLER).ast,
        CalleeResolver([str(tmp_path)]),
    )
    assert report.findings == []
    assert report.caveats


def _cli(*args: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "cobolparser.cli.parse", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.mark.integration
def test_cli_lint_callee_path(tmp_path):
    (tmp_path / "DATESUB.cbl").write_text(CALLEE)
    (tmp_path / "CALLER.cbl").write_text(CALLER)
    run = _cli(
        "lint",
        "CALLER.cbl",
        "--callee-path",
        ".",
        "--rule",
        "call-check",
        "--format",
        "text",
        "--fail-on",
        "error",
        cwd=tmp_path,
    )
    assert run.returncode == 3, run.stderr
    assert "CALLER.cbl:" in run.stdout and "error [call-check]" in run.stdout
    quiet = _cli(
        "lint", "CALLER.cbl", "--rule", "call-check", "--format", "json", cwd=tmp_path
    )
    assert quiet.returncode == 0, quiet.stderr
    assert '"call-check"' not in quiet.stdout.split('"rules_run"')[1].split("]")[0]


def test_comp5_receiver_is_judged_by_native_capacity():
    # #853: PIC 9(2) COMP-5 is a halfword holding 0-65535 on Enterprise COBOL.
    data = """\
    WORKING-STORAGE SECTION.
    01  P5           PIC 9(2) COMP-5.
    01  F5           PIC 9(5) COMP-5.
    01  C2           PIC 9(2) COMP.
    01  N3           PIC 9(3) VALUE 500.
    01  N6           PIC 9(6).
    01  N12          PIC 9(12).
    """
    procedure = """\
    MOVE 500 TO P5
    MOVE N3 TO P5
    COMPUTE P5 = N3 + 1
    MOVE N3 TO C2
    MOVE N6 TO P5
    MOVE N6 TO F5
    MOVE N12 TO F5
    GOBACK.
    """
    found = _findings(_program(data, procedure), "truncation")
    # C2 (plain COMP, TRUNC(STD)) keeps its PICTURE; P5 holds 4 digits, F5 9.
    assert [f.symbol for f in found] == ["C2", "P5", "F5"]
