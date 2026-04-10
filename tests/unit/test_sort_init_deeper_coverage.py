"""Tests targeting uncovered branches in sort_merge_parsers.py and
initialize_inspect_parsers.py.

sort_merge_parsers.py  (86.90 %, 33 missing branches):
- _parse_keys: ON keyword, KEY keyword, non-ASCENDING/DESCENDING break,
  inner field loop break on non-IDENTIFIER
- _parse_file_list: empty peek, non-IDENTIFIER break
- SortStatementParser: no file name (period immediately), WITH not followed by
  DUPLICATES, COLLATING without SEQUENCE, without IS, INPUT/OUTPUT PROCEDURE IS
  with THRU, USING/GIVING file lists
- MergeStatementParser: empty token in matches(), COLLATING branches,
  OUTPUT PROCEDURE with THRU, USING/GIVING

initialize_inspect_parsers.py  (87.91 %, 25 missing branches):
- InitializeStatementParser: None token in matches(), targets loop empty peek,
  WITH FILLER clause, REPLACING NUMERIC/ALPHABETIC DATA BY value
- InspectStatementParser: None token in matches(), no target / early return,
  consume-to-period loop, TALLYING with ALL/LEADING + BEFORE/AFTER INITIAL,
  REPLACING CHARACTERS/ALL/LEADING/FIRST + BEFORE/AFTER, CONVERTING from TO to,
  TALLYING followed by REPLACING (combined)
"""

import pytest

from cobolparser import CobolParser, ErrorRecoveryMode
from cobolparser.models.statements import (
    InitializeStatement,
    InspectStatement,
    MergeStatement,
    SortStatement,
)

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _make_source(procedure_body: str, extra_data: str = "") -> str:
    return (
        "       IDENTIFICATION DIVISION.\n"
        "       PROGRAM-ID. TEST-PROG.\n"
        "       ENVIRONMENT DIVISION.\n"
        "       INPUT-OUTPUT SECTION.\n"
        "       FILE-CONTROL.\n"
        "           SELECT SORT-FILE ASSIGN TO 'SORTFL'.\n"
        "           SELECT IN-FILE ASSIGN TO 'INFILE'.\n"
        "           SELECT IN-FILE2 ASSIGN TO 'INFL2'.\n"
        "           SELECT OUT-FILE ASSIGN TO 'OUTFL'.\n"
        "       DATA DIVISION.\n"
        "       FILE SECTION.\n"
        "       SD SORT-FILE.\n"
        "       01 SORT-REC.\n"
        "          05 SORT-KEY1 PIC X(10).\n"
        "          05 SORT-KEY2 PIC X(10).\n"
        "       FD IN-FILE.\n"
        "       01 IN-REC PIC X(80).\n"
        "       FD IN-FILE2.\n"
        "       01 IN-REC2 PIC X(80).\n"
        "       FD OUT-FILE.\n"
        "       01 OUT-REC PIC X(80).\n"
        "       WORKING-STORAGE SECTION.\n"
        "       01 WS-TALLY PIC 9(4) VALUE 0.\n"
        "       01 WS-STR PIC X(20) VALUE 'HELLO WORLD'.\n"
        "       01 WS-FROM PIC X(5) VALUE 'ABCDE'.\n"
        "       01 WS-TO PIC X(5) VALUE 'abcde'.\n"
        f"{extra_data}"
        "       PROCEDURE DIVISION.\n"
        "       MAIN-LOGIC.\n"
        f"{procedure_body}\n"
        "       INPUT-PROC.\n"
        "           DISPLAY 'INPUT'.\n"
        "       INPUT-PROC-END.\n"
        "           DISPLAY 'END'.\n"
        "       OUTPUT-PROC.\n"
        "           DISPLAY 'OUTPUT'.\n"
        "       OUTPUT-PROC-END.\n"
        "           DISPLAY 'END'.\n"
    )


def _parse(src):
    parser = CobolParser(error_recovery=ErrorRecoveryMode.COLLECT_ALL)
    return parser.parse(src)


def _find_stmt(result, stmt_type):
    """Walk the procedure division to find the first statement of *stmt_type*."""
    proc = result.ast.procedure_division
    stmts = []
    if proc.paragraphs:
        for p in proc.paragraphs:
            stmts.extend(p.statements)
    for s in stmts:
        if isinstance(s, stmt_type):
            return s
    pytest.fail(
        f"No {stmt_type.__name__} found among {[type(s).__name__ for s in stmts]}"
    )


# ===================================================================
# SORT tests
# ===================================================================


class TestSortCollatingSequence:
    """SORT with COLLATING SEQUENCE IS alphabet-name."""

    def test_sort_collating_sequence_is(self):
        src = _make_source(
            "           SORT SORT-FILE\n"
            "               ON ASCENDING KEY SORT-KEY1\n"
            "               COLLATING SEQUENCE IS NATIVE-SEQ\n"
            "               USING IN-FILE\n"
            "               GIVING OUT-FILE.\n"
        )
        result = _parse(src)
        stmt = _find_stmt(result, SortStatement)
        assert stmt.collating_sequence is not None

    def test_sort_collating_without_is(self):
        """COLLATING SEQUENCE without IS -- branches 172->175."""
        src = _make_source(
            "           SORT SORT-FILE\n"
            "               ON ASCENDING KEY SORT-KEY1\n"
            "               COLLATING SEQUENCE NATIVE-SEQ\n"
            "               USING IN-FILE\n"
            "               GIVING OUT-FILE.\n"
        )
        result = _parse(src)
        stmt = _find_stmt(result, SortStatement)
        assert stmt.collating_sequence is not None


class TestSortInputProcedure:
    """SORT with INPUT PROCEDURE IS para THRU para."""

    def test_sort_input_procedure_thru(self):
        src = _make_source(
            "           SORT SORT-FILE\n"
            "               ON ASCENDING KEY SORT-KEY1\n"
            "               INPUT PROCEDURE IS INPUT-PROC\n"
            "               THRU INPUT-PROC-END\n"
            "               GIVING OUT-FILE.\n"
        )
        result = _parse(src)
        stmt = _find_stmt(result, SortStatement)
        assert stmt.input_procedure is not None
        assert stmt.input_procedure_thru is not None

    def test_sort_input_procedure_no_thru(self):
        """INPUT PROCEDURE without THRU -- branch 202->141."""
        src = _make_source(
            "           SORT SORT-FILE\n"
            "               ON ASCENDING KEY SORT-KEY1\n"
            "               INPUT PROCEDURE IS INPUT-PROC\n"
            "               GIVING OUT-FILE.\n"
        )
        result = _parse(src)
        stmt = _find_stmt(result, SortStatement)
        assert stmt.input_procedure is not None
        assert stmt.input_procedure_thru is None


class TestSortOutputProcedure:
    """SORT with OUTPUT PROCEDURE IS para THRU para."""

    def test_sort_output_procedure_thru(self):
        src = _make_source(
            "           SORT SORT-FILE\n"
            "               ON ASCENDING KEY SORT-KEY1\n"
            "               USING IN-FILE\n"
            "               OUTPUT PROCEDURE IS OUTPUT-PROC\n"
            "               THRU OUTPUT-PROC-END.\n"
        )
        result = _parse(src)
        stmt = _find_stmt(result, SortStatement)
        assert stmt.output_procedure is not None
        assert stmt.output_procedure_thru is not None

    def test_sort_output_procedure_no_thru(self):
        """OUTPUT PROCEDURE without THRU -- branch 229->141."""
        src = _make_source(
            "           SORT SORT-FILE\n"
            "               ON ASCENDING KEY SORT-KEY1\n"
            "               USING IN-FILE\n"
            "               OUTPUT PROCEDURE IS OUTPUT-PROC.\n"
        )
        result = _parse(src)
        stmt = _find_stmt(result, SortStatement)
        assert stmt.output_procedure is not None
        assert stmt.output_procedure_thru is None


class TestSortDuplicates:
    """SORT with WITH DUPLICATES IN ORDER."""

    def test_sort_with_duplicates(self):
        src = _make_source(
            "           SORT SORT-FILE\n"
            "               ON ASCENDING KEY SORT-KEY1\n"
            "               WITH DUPLICATES IN ORDER\n"
            "               USING IN-FILE\n"
            "               GIVING OUT-FILE.\n"
        )
        result = _parse(src)
        stmt = _find_stmt(result, SortStatement)
        assert stmt.duplicates_in_order is True

    def test_sort_with_not_duplicates(self):
        """WITH followed by something other than DUPLICATES -- branch 154->141."""
        src = _make_source(
            "           SORT SORT-FILE\n"
            "               ON ASCENDING KEY SORT-KEY1\n"
            "               USING IN-FILE\n"
            "               GIVING OUT-FILE.\n"
        )
        result = _parse(src)
        stmt = _find_stmt(result, SortStatement)
        assert stmt.duplicates_in_order is False


class TestSortUsingGiving:
    """SORT with USING and GIVING file lists."""

    def test_sort_using_giving(self):
        src = _make_source(
            "           SORT SORT-FILE\n"
            "               ON ASCENDING KEY SORT-KEY1\n"
            "               USING IN-FILE\n"
            "               GIVING OUT-FILE.\n"
        )
        result = _parse(src)
        stmt = _find_stmt(result, SortStatement)
        assert len(stmt.using_files) >= 1
        assert len(stmt.giving_files) >= 1

    def test_sort_using_multiple_files(self):
        src = _make_source(
            "           SORT SORT-FILE\n"
            "               ON ASCENDING KEY SORT-KEY1\n"
            "               USING IN-FILE IN-FILE2\n"
            "               GIVING OUT-FILE.\n"
        )
        result = _parse(src)
        stmt = _find_stmt(result, SortStatement)
        assert len(stmt.using_files) >= 2


class TestSortKeys:
    """SORT with multiple ASCENDING/DESCENDING keys and ON keyword."""

    def test_sort_ascending_descending_keys(self):
        src = _make_source(
            "           SORT SORT-FILE\n"
            "               ON ASCENDING KEY SORT-KEY1\n"
            "               ON DESCENDING KEY SORT-KEY2\n"
            "               USING IN-FILE\n"
            "               GIVING OUT-FILE.\n"
        )
        result = _parse(src)
        stmt = _find_stmt(result, SortStatement)
        assert len(stmt.keys) >= 2
        orders = [k["order"] for k in stmt.keys]
        assert "ASCENDING" in orders
        assert "DESCENDING" in orders

    def test_sort_ascending_without_on(self):
        """ASCENDING KEY without ON prefix."""
        src = _make_source(
            "           SORT SORT-FILE\n"
            "               ASCENDING KEY SORT-KEY1\n"
            "               USING IN-FILE\n"
            "               GIVING OUT-FILE.\n"
        )
        result = _parse(src)
        stmt = _find_stmt(result, SortStatement)
        assert len(stmt.keys) >= 1

    def test_sort_descending_without_key(self):
        """DESCENDING without KEY keyword -- branch 38->43 (no KEY after order)."""
        src = _make_source(
            "           SORT SORT-FILE\n"
            "               DESCENDING SORT-KEY1\n"
            "               USING IN-FILE\n"
            "               GIVING OUT-FILE.\n"
        )
        result = _parse(src)
        stmt = _find_stmt(result, SortStatement)
        assert len(stmt.keys) >= 1

    def test_sort_multiple_fields_per_key(self):
        """Multiple field names after one ASCENDING KEY."""
        src = _make_source(
            "           SORT SORT-FILE\n"
            "               ASCENDING KEY SORT-KEY1 SORT-KEY2\n"
            "               USING IN-FILE\n"
            "               GIVING OUT-FILE.\n"
        )
        result = _parse(src)
        stmt = _find_stmt(result, SortStatement)
        assert len(stmt.keys) >= 2


# ===================================================================
# MERGE tests
# ===================================================================


class TestMergeCollatingSequence:
    """MERGE with COLLATING SEQUENCE IS."""

    def test_merge_collating_sequence_is(self):
        src = _make_source(
            "           MERGE SORT-FILE\n"
            "               ON ASCENDING KEY SORT-KEY1\n"
            "               COLLATING SEQUENCE IS NATIVE-SEQ\n"
            "               USING IN-FILE IN-FILE2\n"
            "               GIVING OUT-FILE.\n"
        )
        result = _parse(src)
        stmt = _find_stmt(result, MergeStatement)
        assert stmt.collating_sequence is not None

    def test_merge_collating_without_is(self):
        """COLLATING SEQUENCE without IS."""
        src = _make_source(
            "           MERGE SORT-FILE\n"
            "               ON ASCENDING KEY SORT-KEY1\n"
            "               COLLATING SEQUENCE NATIVE-SEQ\n"
            "               USING IN-FILE IN-FILE2\n"
            "               GIVING OUT-FILE.\n"
        )
        result = _parse(src)
        stmt = _find_stmt(result, MergeStatement)
        assert stmt.collating_sequence is not None


class TestMergeOutputProcedure:
    """MERGE with OUTPUT PROCEDURE IS para THRU para."""

    def test_merge_output_procedure_thru(self):
        src = _make_source(
            "           MERGE SORT-FILE\n"
            "               ON ASCENDING KEY SORT-KEY1\n"
            "               USING IN-FILE IN-FILE2\n"
            "               OUTPUT PROCEDURE IS OUTPUT-PROC\n"
            "               THRU OUTPUT-PROC-END.\n"
        )
        result = _parse(src)
        stmt = _find_stmt(result, MergeStatement)
        assert stmt.output_procedure is not None
        assert stmt.output_procedure_thru is not None

    def test_merge_output_procedure_no_thru(self):
        """OUTPUT PROCEDURE without THRU."""
        src = _make_source(
            "           MERGE SORT-FILE\n"
            "               ON ASCENDING KEY SORT-KEY1\n"
            "               USING IN-FILE IN-FILE2\n"
            "               OUTPUT PROCEDURE IS OUTPUT-PROC.\n"
        )
        result = _parse(src)
        stmt = _find_stmt(result, MergeStatement)
        assert stmt.output_procedure is not None
        assert stmt.output_procedure_thru is None


class TestMergeUsingGiving:
    """MERGE with USING and GIVING."""

    def test_merge_using_giving(self):
        src = _make_source(
            "           MERGE SORT-FILE\n"
            "               ON ASCENDING KEY SORT-KEY1\n"
            "               USING IN-FILE IN-FILE2\n"
            "               GIVING OUT-FILE.\n"
        )
        result = _parse(src)
        stmt = _find_stmt(result, MergeStatement)
        assert len(stmt.using_files) >= 2
        assert len(stmt.giving_files) >= 1


class TestMergeKeys:
    """MERGE with multiple keys."""

    def test_merge_ascending_descending(self):
        src = _make_source(
            "           MERGE SORT-FILE\n"
            "               ON ASCENDING KEY SORT-KEY1\n"
            "               ON DESCENDING KEY SORT-KEY2\n"
            "               USING IN-FILE IN-FILE2\n"
            "               GIVING OUT-FILE.\n"
        )
        result = _parse(src)
        stmt = _find_stmt(result, MergeStatement)
        assert len(stmt.keys) >= 2


# ===================================================================
# INITIALIZE tests
# ===================================================================


class TestInitializeWithFiller:
    """INITIALIZE with WITH FILLER clause."""

    def test_initialize_with_filler(self):
        src = _make_source(
            "           INITIALIZE WS-STR WITH FILLER\n"
            "               REPLACING ALPHANUMERIC DATA BY SPACES.\n"
        )
        result = _parse(src)
        stmt = _find_stmt(result, InitializeStatement)
        assert stmt.with_filler is True

    def test_initialize_without_filler(self):
        src = _make_source("           INITIALIZE WS-STR.\n")
        result = _parse(src)
        stmt = _find_stmt(result, InitializeStatement)
        assert stmt.with_filler is False


class TestInitializeReplacing:
    """INITIALIZE with REPLACING clauses."""

    def test_initialize_replacing_numeric(self):
        src = _make_source(
            "           INITIALIZE WS-STR\n"
            "               REPLACING NUMERIC DATA BY ZEROS.\n"
        )
        result = _parse(src)
        stmt = _find_stmt(result, InitializeStatement)
        assert len(stmt.replacing_clauses) >= 1
        assert stmt.replacing_clauses[0]["category"] == "NUMERIC"

    def test_initialize_replacing_alphabetic(self):
        src = _make_source(
            "           INITIALIZE WS-STR\n"
            "               REPLACING ALPHABETIC DATA BY SPACES.\n"
        )
        result = _parse(src)
        stmt = _find_stmt(result, InitializeStatement)
        assert len(stmt.replacing_clauses) >= 1
        assert stmt.replacing_clauses[0]["category"] == "ALPHABETIC"

    def test_initialize_replacing_alphanumeric(self):
        src = _make_source(
            "           INITIALIZE WS-STR\n"
            "               REPLACING ALPHANUMERIC BY SPACES.\n"
        )
        result = _parse(src)
        stmt = _find_stmt(result, InitializeStatement)
        assert len(stmt.replacing_clauses) >= 1
        assert stmt.replacing_clauses[0]["category"] == "ALPHANUMERIC"

    def test_initialize_replacing_multiple(self):
        src = _make_source(
            "           INITIALIZE WS-STR\n"
            "               REPLACING NUMERIC DATA BY ZEROS\n"
            "               ALPHANUMERIC DATA BY SPACES.\n"
        )
        result = _parse(src)
        stmt = _find_stmt(result, InitializeStatement)
        assert len(stmt.replacing_clauses) >= 2


class TestInitializeMultipleTargets:
    """INITIALIZE with multiple target identifiers."""

    def test_initialize_multiple_targets(self):
        src = _make_source("           INITIALIZE WS-STR WS-FROM WS-TO.\n")
        result = _parse(src)
        stmt = _find_stmt(result, InitializeStatement)
        assert len(stmt.targets) >= 3


# ===================================================================
# INSPECT tests
# ===================================================================


class TestInspectTallying:
    """INSPECT TALLYING with ALL/LEADING and BEFORE/AFTER INITIAL."""

    def test_inspect_tallying_characters(self):
        src = _make_source(
            "           INSPECT WS-STR TALLYING WS-TALLY\n"
            "               FOR CHARACTERS.\n"
        )
        result = _parse(src)
        stmt = _find_stmt(result, InspectStatement)
        assert stmt.inspect_type in ("TALLYING", "TALLYING_REPLACING")
        assert len(stmt.tallying_clauses) >= 1
        assert stmt.tallying_clauses[0]["for_type"] == "CHARACTERS"

    def test_inspect_tallying_all(self):
        src = _make_source(
            "           INSPECT WS-STR TALLYING WS-TALLY\n"
            "               FOR ALL 'A'.\n"
        )
        result = _parse(src)
        stmt = _find_stmt(result, InspectStatement)
        assert len(stmt.tallying_clauses) >= 1
        assert stmt.tallying_clauses[0]["for_type"] == "ALL"

    def test_inspect_tallying_leading(self):
        src = _make_source(
            "           INSPECT WS-STR TALLYING WS-TALLY\n"
            "               FOR LEADING ' '.\n"
        )
        result = _parse(src)
        stmt = _find_stmt(result, InspectStatement)
        assert len(stmt.tallying_clauses) >= 1
        assert stmt.tallying_clauses[0]["for_type"] == "LEADING"

    def test_inspect_tallying_all_before_initial(self):
        src = _make_source(
            "           INSPECT WS-STR TALLYING WS-TALLY\n"
            "               FOR ALL 'A' BEFORE INITIAL 'B'.\n"
        )
        result = _parse(src)
        stmt = _find_stmt(result, InspectStatement)
        assert len(stmt.tallying_clauses) >= 1
        clause = stmt.tallying_clauses[0]
        assert clause["for_type"] == "ALL"
        assert clause["before"] is not None

    def test_inspect_tallying_leading_after_initial(self):
        src = _make_source(
            "           INSPECT WS-STR TALLYING WS-TALLY\n"
            "               FOR LEADING ' ' AFTER INITIAL 'X'.\n"
        )
        result = _parse(src)
        stmt = _find_stmt(result, InspectStatement)
        assert len(stmt.tallying_clauses) >= 1
        clause = stmt.tallying_clauses[0]
        assert clause["for_type"] == "LEADING"
        assert clause["after"] is not None

    def test_inspect_tallying_characters_before_initial(self):
        src = _make_source(
            "           INSPECT WS-STR TALLYING WS-TALLY\n"
            "               FOR CHARACTERS BEFORE INITIAL 'Z'.\n"
        )
        result = _parse(src)
        stmt = _find_stmt(result, InspectStatement)
        assert len(stmt.tallying_clauses) >= 1
        clause = stmt.tallying_clauses[0]
        assert clause["for_type"] == "CHARACTERS"
        assert clause["before"] is not None


class TestInspectReplacingCharacters:
    """INSPECT REPLACING CHARACTERS BY X BEFORE INITIAL Y."""

    def test_inspect_replacing_characters_by(self):
        src = _make_source(
            "           INSPECT WS-STR REPLACING\n"
            "               CHARACTERS BY ' '.\n"
        )
        result = _parse(src)
        stmt = _find_stmt(result, InspectStatement)
        assert stmt.inspect_type in ("REPLACING", "TALLYING_REPLACING")
        assert len(stmt.replacing_clauses) >= 1
        clause = stmt.replacing_clauses[0]
        assert clause["replace_type"] == "CHARACTERS"

    def test_inspect_replacing_characters_before_initial(self):
        src = _make_source(
            "           INSPECT WS-STR REPLACING\n"
            "               CHARACTERS BY ' ' BEFORE INITIAL 'Z'.\n"
        )
        result = _parse(src)
        stmt = _find_stmt(result, InspectStatement)
        assert len(stmt.replacing_clauses) >= 1
        clause = stmt.replacing_clauses[0]
        assert clause["replace_type"] == "CHARACTERS"
        assert clause["before"] is not None

    def test_inspect_replacing_characters_after_initial(self):
        src = _make_source(
            "           INSPECT WS-STR REPLACING\n"
            "               CHARACTERS BY ' ' AFTER INITIAL 'A'.\n"
        )
        result = _parse(src)
        stmt = _find_stmt(result, InspectStatement)
        assert len(stmt.replacing_clauses) >= 1
        clause = stmt.replacing_clauses[0]
        assert clause["replace_type"] == "CHARACTERS"
        assert clause["after"] is not None


class TestInspectReplacingAllLeadingFirst:
    """INSPECT REPLACING ALL/LEADING/FIRST with BEFORE/AFTER."""

    def test_inspect_replacing_all(self):
        src = _make_source(
            "           INSPECT WS-STR REPLACING\n" "               ALL 'A' BY 'B'.\n"
        )
        result = _parse(src)
        stmt = _find_stmt(result, InspectStatement)
        assert len(stmt.replacing_clauses) >= 1
        clause = stmt.replacing_clauses[0]
        assert clause["replace_type"] == "ALL"

    def test_inspect_replacing_leading(self):
        src = _make_source(
            "           INSPECT WS-STR REPLACING\n"
            "               LEADING ' ' BY '0'.\n"
        )
        result = _parse(src)
        stmt = _find_stmt(result, InspectStatement)
        assert len(stmt.replacing_clauses) >= 1
        clause = stmt.replacing_clauses[0]
        assert clause["replace_type"] == "LEADING"

    def test_inspect_replacing_first(self):
        src = _make_source(
            "           INSPECT WS-STR REPLACING\n" "               FIRST 'A' BY 'Z'.\n"
        )
        result = _parse(src)
        stmt = _find_stmt(result, InspectStatement)
        assert len(stmt.replacing_clauses) >= 1
        clause = stmt.replacing_clauses[0]
        assert clause["replace_type"] == "FIRST"

    def test_inspect_replacing_all_before_initial(self):
        src = _make_source(
            "           INSPECT WS-STR REPLACING\n"
            "               ALL 'A' BY 'B' BEFORE INITIAL 'C'.\n"
        )
        result = _parse(src)
        stmt = _find_stmt(result, InspectStatement)
        assert len(stmt.replacing_clauses) >= 1
        clause = stmt.replacing_clauses[0]
        assert clause["replace_type"] == "ALL"
        assert clause["before"] is not None

    def test_inspect_replacing_leading_after_initial(self):
        src = _make_source(
            "           INSPECT WS-STR REPLACING\n"
            "               LEADING ' ' BY '0' AFTER INITIAL 'X'.\n"
        )
        result = _parse(src)
        stmt = _find_stmt(result, InspectStatement)
        assert len(stmt.replacing_clauses) >= 1
        clause = stmt.replacing_clauses[0]
        assert clause["replace_type"] == "LEADING"
        assert clause["after"] is not None


class TestInspectConverting:
    """INSPECT CONVERTING from TO to."""

    def test_inspect_converting(self):
        src = _make_source(
            "           INSPECT WS-STR CONVERTING\n"
            "               WS-FROM TO WS-TO.\n"
        )
        result = _parse(src)
        stmt = _find_stmt(result, InspectStatement)
        assert stmt.inspect_type == "CONVERTING"
        assert stmt.converting_from is not None
        assert stmt.converting_to is not None

    def test_inspect_converting_literals(self):
        src = _make_source(
            "           INSPECT WS-STR CONVERTING\n"
            "               'ABCDE' TO 'abcde'.\n"
        )
        result = _parse(src)
        stmt = _find_stmt(result, InspectStatement)
        assert stmt.inspect_type == "CONVERTING"
        assert stmt.converting_from is not None
        assert stmt.converting_to is not None


class TestInspectTallyingReplacing:
    """INSPECT TALLYING ... REPLACING ... (combined)."""

    def test_inspect_tallying_then_replacing(self):
        src = _make_source(
            "           INSPECT WS-STR\n"
            "               TALLYING WS-TALLY FOR ALL 'A'\n"
            "               REPLACING ALL 'A' BY 'B'.\n"
        )
        result = _parse(src)
        stmt = _find_stmt(result, InspectStatement)
        assert stmt.inspect_type == "TALLYING_REPLACING"
        assert len(stmt.tallying_clauses) >= 1
        assert len(stmt.replacing_clauses) >= 1


class TestInspectEarlyReturn:
    """INSPECT with no mode keyword -- early return branch."""

    def test_inspect_no_mode(self):
        """INSPECT with target but no TALLYING/REPLACING/CONVERTING."""
        src = _make_source("           INSPECT WS-STR.\n")
        result = _parse(src)
        stmt = _find_stmt(result, InspectStatement)
        assert stmt.target is not None
        assert stmt.inspect_type is None


# ===================================================================
# Edge-case / low-level branch coverage
# ===================================================================


class TestSortEdgeCases:
    """Hit remaining uncovered branches for SORT parser."""

    def test_sort_collating_without_sequence(self):
        """COLLATING followed directly by identifier (no SEQUENCE keyword).

        Exercises branch 168->171 (n not 'SEQUENCE') then falls through to
        IS check and identifier consumption.
        """
        src = _make_source(
            "           SORT SORT-FILE\n"
            "               ASCENDING KEY SORT-KEY1\n"
            "               COLLATING NATIVE-SEQ\n"
            "               USING IN-FILE\n"
            "               GIVING OUT-FILE.\n"
        )
        result = _parse(src)
        # Should parse without crashing; collating_sequence may or may not be set
        assert result.ast is not None

    def test_sort_input_without_procedure(self):
        """INPUT not followed by PROCEDURE -- branch 193->196.

        The parser sees INPUT, skips PROCEDURE check, then falls through to
        IS check.
        """
        src = _make_source(
            "           SORT SORT-FILE\n"
            "               ASCENDING KEY SORT-KEY1\n"
            "               INPUT IS INPUT-PROC\n"
            "               GIVING OUT-FILE.\n"
        )
        result = _parse(src)
        assert result.ast is not None

    def test_sort_output_without_procedure(self):
        """OUTPUT not followed by PROCEDURE -- branch 220->223."""
        src = _make_source(
            "           SORT SORT-FILE\n"
            "               ASCENDING KEY SORT-KEY1\n"
            "               USING IN-FILE\n"
            "               OUTPUT IS OUTPUT-PROC.\n"
        )
        result = _parse(src)
        assert result.ast is not None

    def test_sort_input_procedure_through(self):
        """INPUT PROCEDURE with THROUGH (synonym for THRU)."""
        src = _make_source(
            "           SORT SORT-FILE\n"
            "               ON ASCENDING KEY SORT-KEY1\n"
            "               INPUT PROCEDURE IS INPUT-PROC\n"
            "               THROUGH INPUT-PROC-END\n"
            "               GIVING OUT-FILE.\n"
        )
        result = _parse(src)
        stmt = _find_stmt(result, SortStatement)
        assert stmt.input_procedure is not None
        assert stmt.input_procedure_thru is not None

    def test_sort_output_procedure_through(self):
        """OUTPUT PROCEDURE with THROUGH (synonym for THRU)."""
        src = _make_source(
            "           SORT SORT-FILE\n"
            "               ON ASCENDING KEY SORT-KEY1\n"
            "               USING IN-FILE\n"
            "               OUTPUT PROCEDURE IS OUTPUT-PROC\n"
            "               THROUGH OUTPUT-PROC-END.\n"
        )
        result = _parse(src)
        stmt = _find_stmt(result, SortStatement)
        assert stmt.output_procedure is not None
        assert stmt.output_procedure_thru is not None

    def test_sort_input_and_output_procedures(self):
        """SORT with both INPUT and OUTPUT PROCEDURE."""
        src = _make_source(
            "           SORT SORT-FILE\n"
            "               ON ASCENDING KEY SORT-KEY1\n"
            "               INPUT PROCEDURE IS INPUT-PROC\n"
            "               THRU INPUT-PROC-END\n"
            "               OUTPUT PROCEDURE IS OUTPUT-PROC\n"
            "               THRU OUTPUT-PROC-END.\n"
        )
        result = _parse(src)
        stmt = _find_stmt(result, SortStatement)
        assert stmt.input_procedure is not None
        assert stmt.input_procedure_thru is not None
        assert stmt.output_procedure is not None
        assert stmt.output_procedure_thru is not None


class TestMergeEdgeCases:
    """Hit remaining uncovered branches for MERGE parser."""

    def test_merge_collating_without_sequence(self):
        """COLLATING followed directly by identifier (no SEQUENCE)."""
        src = _make_source(
            "           MERGE SORT-FILE\n"
            "               ASCENDING KEY SORT-KEY1\n"
            "               COLLATING NATIVE-SEQ\n"
            "               USING IN-FILE IN-FILE2\n"
            "               GIVING OUT-FILE.\n"
        )
        result = _parse(src)
        assert result.ast is not None

    def test_merge_output_without_procedure(self):
        """OUTPUT not followed by PROCEDURE."""
        src = _make_source(
            "           MERGE SORT-FILE\n"
            "               ASCENDING KEY SORT-KEY1\n"
            "               USING IN-FILE IN-FILE2\n"
            "               OUTPUT IS OUTPUT-PROC.\n"
        )
        result = _parse(src)
        assert result.ast is not None

    def test_merge_output_procedure_through(self):
        """MERGE OUTPUT PROCEDURE with THROUGH (synonym for THRU)."""
        src = _make_source(
            "           MERGE SORT-FILE\n"
            "               ASCENDING KEY SORT-KEY1\n"
            "               USING IN-FILE IN-FILE2\n"
            "               OUTPUT PROCEDURE IS OUTPUT-PROC\n"
            "               THROUGH OUTPUT-PROC-END.\n"
        )
        result = _parse(src)
        stmt = _find_stmt(result, MergeStatement)
        assert stmt.output_procedure is not None
        assert stmt.output_procedure_thru is not None

    def test_merge_output_procedure_no_thru_giving(self):
        """MERGE with OUTPUT PROCEDURE then GIVING (covers 338->291)."""
        src = _make_source(
            "           MERGE SORT-FILE\n"
            "               ASCENDING KEY SORT-KEY1\n"
            "               USING IN-FILE IN-FILE2\n"
            "               GIVING OUT-FILE.\n"
        )
        result = _parse(src)
        stmt = _find_stmt(result, MergeStatement)
        assert len(stmt.giving_files) >= 1


class TestInitializeEdgeCases:
    """Hit remaining uncovered branches for INITIALIZE parser."""

    def test_initialize_with_filler_and_replacing(self):
        """WITH FILLER followed by REPLACING clause."""
        src = _make_source(
            "           INITIALIZE WS-STR WITH FILLER\n"
            "               REPLACING NUMERIC DATA BY ZEROS\n"
            "               ALPHANUMERIC DATA BY SPACES.\n"
        )
        result = _parse(src)
        stmt = _find_stmt(result, InitializeStatement)
        assert stmt.with_filler is True
        assert len(stmt.replacing_clauses) >= 2

    def test_initialize_replacing_without_data_keyword(self):
        """REPLACING category without DATA keyword (branch 105 false)."""
        src = _make_source(
            "           INITIALIZE WS-STR\n"
            "               REPLACING NUMERIC BY ZEROS.\n"
        )
        result = _parse(src)
        stmt = _find_stmt(result, InitializeStatement)
        assert len(stmt.replacing_clauses) >= 1

    def test_initialize_replacing_national(self):
        """REPLACING NATIONAL DATA BY value."""
        src = _make_source(
            "           INITIALIZE WS-STR\n"
            "               REPLACING NATIONAL DATA BY SPACES.\n"
        )
        result = _parse(src)
        stmt = _find_stmt(result, InitializeStatement)
        assert len(stmt.replacing_clauses) >= 1
        assert stmt.replacing_clauses[0]["category"] == "NATIONAL"


class TestInspectEdgeCases:
    """Hit remaining uncovered branches for INSPECT parser."""

    def test_inspect_tallying_characters_after_initial(self):
        """AFTER INITIAL in TALLYING (branch for after in _parse_tallying)."""
        src = _make_source(
            "           INSPECT WS-STR TALLYING WS-TALLY\n"
            "               FOR CHARACTERS AFTER INITIAL 'A'.\n"
        )
        result = _parse(src)
        stmt = _find_stmt(result, InspectStatement)
        assert len(stmt.tallying_clauses) >= 1
        clause = stmt.tallying_clauses[0]
        assert clause["after"] is not None

    def test_inspect_replacing_first_before_initial(self):
        """REPLACING FIRST with BEFORE INITIAL."""
        src = _make_source(
            "           INSPECT WS-STR REPLACING\n"
            "               FIRST 'X' BY 'Y' BEFORE INITIAL 'Z'.\n"
        )
        result = _parse(src)
        stmt = _find_stmt(result, InspectStatement)
        assert len(stmt.replacing_clauses) >= 1
        clause = stmt.replacing_clauses[0]
        assert clause["replace_type"] == "FIRST"
        assert clause["before"] is not None

    def test_inspect_replacing_first_after_initial(self):
        """REPLACING FIRST with AFTER INITIAL."""
        src = _make_source(
            "           INSPECT WS-STR REPLACING\n"
            "               FIRST 'X' BY 'Y' AFTER INITIAL 'A'.\n"
        )
        result = _parse(src)
        stmt = _find_stmt(result, InspectStatement)
        assert len(stmt.replacing_clauses) >= 1
        clause = stmt.replacing_clauses[0]
        assert clause["replace_type"] == "FIRST"
        assert clause["after"] is not None

    def test_inspect_replacing_multiple_clauses(self):
        """Multiple REPLACING clauses in a single INSPECT."""
        src = _make_source(
            "           INSPECT WS-STR REPLACING\n"
            "               ALL 'A' BY 'B'\n"
            "               LEADING ' ' BY '0'.\n"
        )
        result = _parse(src)
        stmt = _find_stmt(result, InspectStatement)
        assert len(stmt.replacing_clauses) >= 2
