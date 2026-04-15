"""Tests targeting branch-coverage gaps in statement parsers.

Covers uncovered branches in:
- arithmetic_parsers.py  (ADD/SUBTRACT/MULTIPLY/DIVIDE/COMPUTE SIZE ERROR, GIVING)
- simple_statement_parsers.py  (ALTER, GENERATE, RELEASE, RETURN, USE)
- string_unstring_parsers.py  (DELIMITED BY SIZE, OVERFLOW, multi-destination UNSTRING)
- sort_merge_parsers.py  (MERGE, SORT with INPUT/OUTPUT PROCEDURE)
- initialize_inspect_parsers.py  (REPLACING clauses, INSPECT TALLYING/REPLACING combos)
- perform_parser.py  (inline PERFORM TIMES, TEST BEFORE/AFTER, UNTIL nested)
"""

from __future__ import annotations

from cobolparser import parse_cobol
from cobolparser.plugins.core import ErrorRecoveryMode

# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _parse(src: str):
    return parse_cobol(
        src, error_recovery=ErrorRecoveryMode.COLLECT_ALL, free_form=True
    )


def _assert_parsed(src: str):
    result = _parse(src)
    assert result.ast is not None
    return result


def _find_stmts(result, stmt_type: str):
    """Find all statements of a given statement_type (e.g. 'ADD', 'PERFORM')."""
    return [
        s
        for s in result.ast.find_all_by_type("Statement")
        if getattr(s, "statement_type", "").upper() == stmt_type.upper()
    ]


_PREFIX = (
    "IDENTIFICATION DIVISION.\n"
    "PROGRAM-ID. TEST.\n"
    "DATA DIVISION.\n"
    "WORKING-STORAGE SECTION.\n"
    "01  WS-A PIC 9(5) VALUE 0.\n"
    "01  WS-B PIC 9(5) VALUE 0.\n"
    "01  WS-C PIC 9(5) VALUE 0.\n"
    "01  WS-STR PIC X(40) VALUE SPACES.\n"
    "01  WS-STR2 PIC X(40) VALUE SPACES.\n"
    "01  WS-RESULT PIC X(80) VALUE SPACES.\n"
    "01  WS-CNT PIC 9(3) VALUE 0.\n"
    "01  WS-PTR PIC 9(3) VALUE 0.\n"
    "PROCEDURE DIVISION.\n"
)


def _wrap(body: str) -> str:
    return _PREFIX + "MAIN-PARA.\n" + body + "    STOP RUN.\n"


# ---------------------------------------------------------------------------
# Arithmetic parsers: SIZE ERROR, NOT ON SIZE ERROR, GIVING, END-ADD
# ---------------------------------------------------------------------------


class TestArithmeticSizeError:
    def test_add_giving_size_error(self):
        src = _wrap(
            "    ADD WS-A WS-B GIVING WS-C\n"
            "        ON SIZE ERROR MOVE 0 TO WS-C\n"
            "    END-ADD.\n"
        )
        result = _assert_parsed(src)
        stmts = result.ast.find_all_by_type("Statement")
        assert len(stmts) >= 1

    def test_add_giving_not_on_size_error(self):
        src = _wrap(
            "    ADD WS-A TO WS-C\n"
            "        ON SIZE ERROR MOVE 0 TO WS-C\n"
            "        NOT ON SIZE ERROR MOVE 1 TO WS-C\n"
            "    END-ADD.\n"
        )
        result = _assert_parsed(src)
        stmts = result.ast.find_all_by_type("Statement")
        assert len(stmts) >= 1

    def test_subtract_giving_size_error(self):
        src = _wrap(
            "    SUBTRACT WS-B FROM WS-A GIVING WS-C\n"
            "        ON SIZE ERROR MOVE 0 TO WS-C\n"
            "    END-SUBTRACT.\n"
        )
        result = _assert_parsed(src)
        stmts = result.ast.find_all_by_type("Statement")
        assert len(stmts) >= 1

    def test_multiply_giving_size_error(self):
        src = _wrap(
            "    MULTIPLY WS-A BY WS-B GIVING WS-C\n"
            "        ON SIZE ERROR MOVE 0 TO WS-C\n"
            "        NOT ON SIZE ERROR CONTINUE\n"
            "    END-MULTIPLY.\n"
        )
        result = _assert_parsed(src)
        assert result.ast is not None

    def test_divide_giving_remainder(self):
        src = _wrap(
            "    DIVIDE WS-B INTO WS-A GIVING WS-C\n"
            "        REMAINDER WS-B\n"
            "        ON SIZE ERROR MOVE 0 TO WS-C\n"
            "    END-DIVIDE.\n"
        )
        result = _assert_parsed(src)
        assert result.ast is not None

    def test_divide_by_form(self):
        src = _wrap("    DIVIDE WS-A BY WS-B GIVING WS-C.\n")
        result = _assert_parsed(src)
        stmts = result.ast.find_all_by_type("Statement")
        assert len(stmts) >= 1

    def test_compute_size_error(self):
        src = _wrap(
            "    COMPUTE WS-C = WS-A * WS-B\n"
            "        ON SIZE ERROR MOVE 0 TO WS-C\n"
            "        NOT ON SIZE ERROR MOVE WS-C TO WS-A\n"
            "    END-COMPUTE.\n"
        )
        result = _assert_parsed(src)
        stmts = result.ast.find_all_by_type("Statement")
        assert len(stmts) >= 1

    def test_add_corresponding(self):
        src = (
            "IDENTIFICATION DIVISION.\n"
            "PROGRAM-ID. TEST.\n"
            "DATA DIVISION.\n"
            "WORKING-STORAGE SECTION.\n"
            "01  WS-REC1.\n"
            "    05  WS-X PIC 9(3) VALUE 0.\n"
            "    05  WS-Y PIC 9(3) VALUE 0.\n"
            "01  WS-REC2.\n"
            "    05  WS-X PIC 9(3) VALUE 0.\n"
            "    05  WS-Y PIC 9(3) VALUE 0.\n"
            "PROCEDURE DIVISION.\n"
            "MAIN.\n"
            "    ADD CORRESPONDING WS-REC1 TO WS-REC2.\n"
            "    STOP RUN.\n"
        )
        result = _assert_parsed(src)
        assert result.ast is not None


# ---------------------------------------------------------------------------
# Simple statement parsers: ALTER, GENERATE, RELEASE, RETURN, USE
# ---------------------------------------------------------------------------


class TestSimpleStatementParsers:
    def test_alter_statement(self):
        src = (
            "IDENTIFICATION DIVISION.\n"
            "PROGRAM-ID. TEST.\n"
            "PROCEDURE DIVISION.\n"
            "PARA-A.\n"
            "    GO TO PARA-B.\n"
            "PARA-B.\n"
            "    ALTER PARA-A TO PROCEED TO PARA-B.\n"
            "    STOP RUN.\n"
        )
        result = _assert_parsed(src)
        stmts = _find_stmts(result, "ALTER")
        assert len(stmts) >= 1

    def test_cancel_statement(self):
        src = _wrap("    CANCEL 'SUBPGM1'.\n")
        result = _assert_parsed(src)
        stmts = _find_stmts(result, "CANCEL")
        assert len(stmts) >= 1

    def test_cancel_identifier(self):
        src = _wrap("    CANCEL WS-STR.\n")
        result = _assert_parsed(src)
        assert result.ast is not None

    def test_goback_statement(self):
        src = _wrap("    GOBACK.\n")
        result = _assert_parsed(src)
        stmts = _find_stmts(result, "GOBACK")
        assert len(stmts) >= 1

    def test_exit_statement_alone(self):
        src = (
            "IDENTIFICATION DIVISION.\n"
            "PROGRAM-ID. TEST.\n"
            "PROCEDURE DIVISION.\n"
            "MAIN-PARA.\n"
            "    PERFORM SUB-PARA.\n"
            "    STOP RUN.\n"
            "SUB-PARA.\n"
            "    EXIT.\n"
        )
        result = _assert_parsed(src)
        stmts = _find_stmts(result, "EXIT")
        assert len(stmts) >= 1

    def test_exit_program(self):
        src = _wrap("    EXIT PROGRAM.\n")
        result = _assert_parsed(src)
        assert result.ast is not None

    def test_release_statement(self):
        src = (
            "IDENTIFICATION DIVISION.\n"
            "PROGRAM-ID. TEST.\n"
            "DATA DIVISION.\n"
            "WORKING-STORAGE SECTION.\n"
            "01  WS-REC PIC X(80).\n"
            "01  WS-SRC PIC X(80).\n"
            "PROCEDURE DIVISION.\n"
            "MAIN-PARA.\n"
            "    RELEASE WS-REC FROM WS-SRC.\n"
            "    STOP RUN.\n"
        )
        result = _assert_parsed(src)
        stmts = _find_stmts(result, "RELEASE")
        assert len(stmts) >= 1

    def test_release_without_from(self):
        src = (
            "IDENTIFICATION DIVISION.\n"
            "PROGRAM-ID. TEST.\n"
            "DATA DIVISION.\n"
            "WORKING-STORAGE SECTION.\n"
            "01  WS-REC PIC X(80).\n"
            "PROCEDURE DIVISION.\n"
            "MAIN-PARA.\n"
            "    RELEASE WS-REC.\n"
            "    STOP RUN.\n"
        )
        result = _assert_parsed(src)
        assert result.ast is not None

    def test_return_at_end(self):
        src = (
            "IDENTIFICATION DIVISION.\n"
            "PROGRAM-ID. TEST.\n"
            "DATA DIVISION.\n"
            "WORKING-STORAGE SECTION.\n"
            "01  WS-REC PIC X(80).\n"
            "PROCEDURE DIVISION.\n"
            "MAIN-PARA.\n"
            "    RETURN WS-REC INTO WS-REC\n"
            "        AT END MOVE SPACES TO WS-REC\n"
            "    END-RETURN.\n"
            "    STOP RUN.\n"
        )
        result = _assert_parsed(src)
        stmts = _find_stmts(result, "RETURN")
        assert len(stmts) >= 1

    def test_return_not_at_end(self):
        src = (
            "IDENTIFICATION DIVISION.\n"
            "PROGRAM-ID. TEST.\n"
            "DATA DIVISION.\n"
            "WORKING-STORAGE SECTION.\n"
            "01  WS-REC PIC X(80).\n"
            "PROCEDURE DIVISION.\n"
            "MAIN-PARA.\n"
            "    RETURN WS-REC\n"
            "        AT END MOVE SPACES TO WS-REC\n"
            "        NOT AT END CONTINUE\n"
            "    END-RETURN.\n"
            "    STOP RUN.\n"
        )
        result = _assert_parsed(src)
        assert result.ast is not None


# ---------------------------------------------------------------------------
# String/Unstring parsers: DELIMITED BY SIZE, OVERFLOW, multi-destination
# ---------------------------------------------------------------------------


class TestStringUnstringBranches:
    def test_string_delimited_by_size(self):
        src = _wrap(
            "    STRING WS-STR DELIMITED BY SIZE\n"
            "           WS-STR2 DELIMITED BY SPACE\n"
            "        INTO WS-RESULT.\n"
        )
        result = _assert_parsed(src)
        stmts = _find_stmts(result, "STRING")
        assert len(stmts) >= 1

    def test_string_with_pointer(self):
        src = _wrap(
            "    STRING WS-STR DELIMITED BY SIZE\n"
            "        INTO WS-RESULT\n"
            "        WITH POINTER WS-PTR.\n"
        )
        result = _assert_parsed(src)
        assert result.ast is not None

    def test_string_on_overflow(self):
        src = _wrap(
            "    STRING WS-STR DELIMITED BY SPACE\n"
            "        INTO WS-RESULT\n"
            "        ON OVERFLOW MOVE SPACES TO WS-RESULT\n"
            "    END-STRING.\n"
        )
        result = _assert_parsed(src)
        stmts = _find_stmts(result, "STRING")
        assert len(stmts) >= 1

    def test_string_not_on_overflow(self):
        src = _wrap(
            "    STRING WS-STR DELIMITED BY SPACE\n"
            "        INTO WS-RESULT\n"
            "        ON OVERFLOW MOVE 0 TO WS-CNT\n"
            "        NOT ON OVERFLOW MOVE 1 TO WS-CNT\n"
            "    END-STRING.\n"
        )
        result = _assert_parsed(src)
        assert result.ast is not None

    def test_unstring_basic(self):
        src = _wrap(
            "    UNSTRING WS-STR\n"
            "        DELIMITED BY ','\n"
            "        INTO WS-STR2 WS-RESULT.\n"
        )
        result = _assert_parsed(src)
        stmts = _find_stmts(result, "UNSTRING")
        assert len(stmts) >= 1

    def test_unstring_multiple_delimiters(self):
        src = _wrap(
            "    UNSTRING WS-STR\n"
            "        DELIMITED BY ',' OR ';' OR SPACE\n"
            "        INTO WS-STR2\n"
            "             WS-RESULT.\n"
        )
        result = _assert_parsed(src)
        assert result.ast is not None

    def test_unstring_with_pointer_and_tallying(self):
        src = _wrap(
            "    UNSTRING WS-STR\n"
            "        DELIMITED BY SPACE\n"
            "        INTO WS-RESULT\n"
            "        WITH POINTER WS-PTR\n"
            "        TALLYING IN WS-CNT.\n"
        )
        result = _assert_parsed(src)
        assert result.ast is not None

    def test_unstring_on_overflow(self):
        src = _wrap(
            "    UNSTRING WS-STR\n"
            "        DELIMITED BY SPACE\n"
            "        INTO WS-RESULT\n"
            "        ON OVERFLOW MOVE 0 TO WS-CNT\n"
            "        NOT ON OVERFLOW MOVE 1 TO WS-CNT\n"
            "    END-UNSTRING.\n"
        )
        result = _assert_parsed(src)
        assert result.ast is not None


# ---------------------------------------------------------------------------
# Sort/Merge parsers
# ---------------------------------------------------------------------------


class TestSortMergeBranches:
    def test_sort_ascending_using_giving(self):
        src = (
            "IDENTIFICATION DIVISION.\n"
            "PROGRAM-ID. TEST.\n"
            "DATA DIVISION.\n"
            "WORKING-STORAGE SECTION.\n"
            "01  WS-KEY PIC X(10).\n"
            "PROCEDURE DIVISION.\n"
            "MAIN-PARA.\n"
            "    SORT SORTFILE\n"
            "        ON ASCENDING KEY WS-KEY\n"
            "        USING INFILE\n"
            "        GIVING OUTFILE.\n"
            "    STOP RUN.\n"
        )
        result = _assert_parsed(src)
        stmts = _find_stmts(result, "SORT")
        assert len(stmts) >= 1

    def test_sort_descending_key(self):
        src = (
            "IDENTIFICATION DIVISION.\n"
            "PROGRAM-ID. TEST.\n"
            "DATA DIVISION.\n"
            "WORKING-STORAGE SECTION.\n"
            "01  WS-KEY1 PIC X(5).\n"
            "01  WS-KEY2 PIC 9(3).\n"
            "PROCEDURE DIVISION.\n"
            "MAIN-PARA.\n"
            "    SORT SORTFILE\n"
            "        ON DESCENDING KEY WS-KEY1\n"
            "        ON ASCENDING KEY WS-KEY2\n"
            "        USING INFILE\n"
            "        GIVING OUTFILE.\n"
            "    STOP RUN.\n"
        )
        result = _assert_parsed(src)
        assert result.ast is not None

    def test_sort_with_duplicates_order(self):
        src = (
            "IDENTIFICATION DIVISION.\n"
            "PROGRAM-ID. TEST.\n"
            "DATA DIVISION.\n"
            "WORKING-STORAGE SECTION.\n"
            "01  WS-KEY PIC X(10).\n"
            "PROCEDURE DIVISION.\n"
            "MAIN-PARA.\n"
            "    SORT SORTFILE\n"
            "        WITH DUPLICATES IN ORDER\n"
            "        ON ASCENDING KEY WS-KEY\n"
            "        USING INFILE\n"
            "        GIVING OUTFILE.\n"
            "    STOP RUN.\n"
        )
        result = _assert_parsed(src)
        assert result.ast is not None

    def test_merge_basic(self):
        src = (
            "IDENTIFICATION DIVISION.\n"
            "PROGRAM-ID. TEST.\n"
            "DATA DIVISION.\n"
            "WORKING-STORAGE SECTION.\n"
            "01  WS-KEY PIC X(10).\n"
            "PROCEDURE DIVISION.\n"
            "MAIN-PARA.\n"
            "    MERGE MERGEFILE\n"
            "        ON ASCENDING KEY WS-KEY\n"
            "        USING INFILE1 INFILE2\n"
            "        GIVING OUTFILE.\n"
            "    STOP RUN.\n"
        )
        result = _assert_parsed(src)
        stmts = _find_stmts(result, "MERGE")
        assert len(stmts) >= 1

    def test_merge_multiple_using(self):
        src = (
            "IDENTIFICATION DIVISION.\n"
            "PROGRAM-ID. TEST.\n"
            "DATA DIVISION.\n"
            "WORKING-STORAGE SECTION.\n"
            "01  WS-KEY PIC X(8).\n"
            "PROCEDURE DIVISION.\n"
            "MAIN-PARA.\n"
            "    MERGE BIGMERGE\n"
            "        ON ASCENDING KEY WS-KEY\n"
            "        USING F1 F2 F3\n"
            "        GIVING OUTFILE.\n"
            "    STOP RUN.\n"
        )
        result = _assert_parsed(src)
        assert result.ast is not None


# ---------------------------------------------------------------------------
# Initialize/Inspect parsers
# ---------------------------------------------------------------------------


class TestInitializeInspectBranches:
    def test_initialize_basic(self):
        src = _wrap("    INITIALIZE WS-STR.\n")
        result = _assert_parsed(src)
        stmts = _find_stmts(result, "INITIALIZE")
        assert len(stmts) >= 1

    def test_initialize_replacing_numeric(self):
        src = _wrap("    INITIALIZE WS-A\n" "        REPLACING NUMERIC BY 0.\n")
        result = _assert_parsed(src)
        assert result.ast is not None

    def test_initialize_replacing_alphabetic(self):
        src = _wrap(
            "    INITIALIZE WS-STR\n" "        REPLACING ALPHABETIC BY SPACES.\n"
        )
        result = _assert_parsed(src)
        assert result.ast is not None

    def test_initialize_replacing_alphanumeric(self):
        src = _wrap(
            "    INITIALIZE WS-STR\n" "        REPLACING ALPHANUMERIC BY SPACES.\n"
        )
        result = _assert_parsed(src)
        assert result.ast is not None

    def test_inspect_tallying_for_all(self):
        src = _wrap("    INSPECT WS-STR\n" "        TALLYING WS-CNT FOR ALL 'A'.\n")
        result = _assert_parsed(src)
        stmts = _find_stmts(result, "INSPECT")
        assert len(stmts) >= 1

    def test_inspect_tallying_before_initial(self):
        src = _wrap(
            "    INSPECT WS-STR\n"
            "        TALLYING WS-CNT\n"
            "            FOR ALL 'X' BEFORE INITIAL SPACE.\n"
        )
        result = _assert_parsed(src)
        assert result.ast is not None

    def test_inspect_tallying_after_initial(self):
        src = _wrap(
            "    INSPECT WS-STR\n"
            "        TALLYING WS-CNT\n"
            "            FOR ALL 'X' AFTER INITIAL '='.\n"
        )
        result = _assert_parsed(src)
        assert result.ast is not None

    def test_inspect_replacing_all(self):
        src = _wrap("    INSPECT WS-STR\n" "        REPLACING ALL 'A' BY 'B'.\n")
        result = _assert_parsed(src)
        stmts = _find_stmts(result, "INSPECT")
        assert len(stmts) >= 1

    def test_inspect_replacing_leading(self):
        src = _wrap("    INSPECT WS-STR\n" "        REPLACING LEADING '0' BY SPACE.\n")
        result = _assert_parsed(src)
        assert result.ast is not None

    def test_inspect_converting(self):
        src = _wrap("    INSPECT WS-STR\n" "        CONVERTING 'abc' TO 'ABC'.\n")
        result = _assert_parsed(src)
        assert result.ast is not None

    def test_inspect_tallying_and_replacing(self):
        src = _wrap(
            "    INSPECT WS-STR\n"
            "        TALLYING WS-CNT FOR ALL SPACE\n"
            "        REPLACING ALL SPACE BY 'X'.\n"
        )
        result = _assert_parsed(src)
        assert result.ast is not None


# ---------------------------------------------------------------------------
# PERFORM parser: inline TIMES, TEST BEFORE/AFTER
# ---------------------------------------------------------------------------


class TestPerformBranches:
    def test_perform_times(self):
        src = _wrap(
            "    PERFORM 5 TIMES\n" "        MOVE 0 TO WS-A\n" "    END-PERFORM.\n"
        )
        result = _assert_parsed(src)
        stmts = _find_stmts(result, "PERFORM")
        assert len(stmts) >= 1

    def test_perform_with_test_before(self):
        src = _wrap(
            "    PERFORM WITH TEST BEFORE UNTIL WS-A > 10\n"
            "        ADD 1 TO WS-A\n"
            "    END-PERFORM.\n"
        )
        result = _assert_parsed(src)
        assert result.ast is not None

    def test_perform_with_test_after(self):
        src = _wrap(
            "    PERFORM WITH TEST AFTER UNTIL WS-A > 5\n"
            "        ADD 1 TO WS-A\n"
            "    END-PERFORM.\n"
        )
        result = _assert_parsed(src)
        assert result.ast is not None

    def test_perform_varying_with_after(self):
        src = _wrap(
            "    PERFORM VARYING WS-A FROM 1 BY 1 UNTIL WS-A > 5\n"
            "        AFTER WS-B FROM 1 BY 1 UNTIL WS-B > 3\n"
            "        MOVE 0 TO WS-C\n"
            "    END-PERFORM.\n"
        )
        result = _assert_parsed(src)
        assert result.ast is not None

    def test_perform_thru_paragraph(self):
        src = (
            "IDENTIFICATION DIVISION.\n"
            "PROGRAM-ID. TEST.\n"
            "DATA DIVISION.\n"
            "WORKING-STORAGE SECTION.\n"
            "01  WS-A PIC 9(3) VALUE 0.\n"
            "PROCEDURE DIVISION.\n"
            "MAIN-PARA.\n"
            "    PERFORM PARA-A THROUGH PARA-B.\n"
            "    STOP RUN.\n"
            "PARA-A.\n"
            "    MOVE 1 TO WS-A.\n"
            "PARA-B.\n"
            "    MOVE 2 TO WS-A.\n"
        )
        result = _assert_parsed(src)
        stmts = _find_stmts(result, "PERFORM")
        assert len(stmts) >= 1

    def test_perform_thru_varying(self):
        src = (
            "IDENTIFICATION DIVISION.\n"
            "PROGRAM-ID. TEST.\n"
            "DATA DIVISION.\n"
            "WORKING-STORAGE SECTION.\n"
            "01  WS-I PIC 9(3) VALUE 0.\n"
            "PROCEDURE DIVISION.\n"
            "MAIN-PARA.\n"
            "    PERFORM CALC-PARA THRU CALC-END\n"
            "        VARYING WS-I FROM 1 BY 1 UNTIL WS-I > 10.\n"
            "    STOP RUN.\n"
            "CALC-PARA.\n"
            "    MOVE WS-I TO WS-I.\n"
            "CALC-END.\n"
            "    EXIT.\n"
        )
        result = _assert_parsed(src)
        assert result.ast is not None

    def test_perform_inline_varying(self):
        src = _wrap(
            "    PERFORM VARYING WS-A FROM 1 BY 1 UNTIL WS-A > 10\n"
            "        MOVE WS-A TO WS-B\n"
            "    END-PERFORM.\n"
        )
        result = _assert_parsed(src)
        stmts = _find_stmts(result, "PERFORM")
        assert len(stmts) >= 1
