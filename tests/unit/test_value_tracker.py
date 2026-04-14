"""Unit tests for DynamicCallAnalyzer (value_tracker.py).

Covers:
- Initial VALUE clause collection from data items
- MOVE statement tracking (literal -> variable)
- MOVE statement tracking (variable -> variable propagation)
- Figurative constant handling (ZERO, SPACE, LOW-VALUE, HIGH-VALUE)
- Dynamic CALL possible_values population
- Multiple MOVE assignments accumulate values
- get_variable_values() and get_all_tracked_variables() public API
- Analyze resets state between calls
"""

from cobolparser import parse_cobol
from cobolparser.analysis import DynamicCallAnalyzer


def _parse(source: str):
    result = parse_cobol(source)
    return result.ast


BOILERPLATE_HEADER = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TEST.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
"""

BOILERPLATE_PROC = """\
       PROCEDURE DIVISION.
       MAIN-PARA.
"""


class TestDynamicCallAnalyzerInit:
    """Tests for analyzer initialization and state reset."""

    def test_fresh_analyzer_has_no_tracked_vars(self):
        analyzer = DynamicCallAnalyzer()
        assert analyzer.get_all_tracked_variables() == []

    def test_get_variable_values_unknown_var(self):
        analyzer = DynamicCallAnalyzer()
        assert analyzer.get_variable_values("NO-SUCH-VAR") == []

    def test_analyze_resets_state_between_calls(self):
        source1 = (
            BOILERPLATE_HEADER
            + "       01 PROG-NAME PIC X(8) VALUE 'FIRST'.\n"
            + BOILERPLATE_PROC
            + "           CALL PROG-NAME.\n"
            + "           STOP RUN.\n"
        )
        source2 = (
            BOILERPLATE_HEADER
            + "       01 PROG-NAME PIC X(8) VALUE 'SECOND'.\n"
            + BOILERPLATE_PROC
            + "           CALL PROG-NAME.\n"
            + "           STOP RUN.\n"
        )
        analyzer = DynamicCallAnalyzer()
        ast1 = _parse(source1)
        analyzer.analyze(ast1)

        ast2 = _parse(source2)
        analyzer.analyze(ast2)
        vals_second = analyzer.get_variable_values("PROG-NAME")

        # After the second analyze() call the state must be fully reset:
        # only "SECOND" should be present, "FIRST" must be gone.
        assert "SECOND" in vals_second
        assert "FIRST" not in vals_second


class TestInitialValueCollection:
    """Tests for VALUE clause collection from data items."""

    def test_single_value_clause_collected(self):
        source = (
            BOILERPLATE_HEADER
            + "       01 PROG-NAME PIC X(8) VALUE 'MYPROG'.\n"
            + BOILERPLATE_PROC
            + "           CALL PROG-NAME.\n"
            + "           STOP RUN.\n"
        )
        analyzer = DynamicCallAnalyzer()
        ast = _parse(source)
        analyzer.analyze(ast)
        values = analyzer.get_variable_values("PROG-NAME")
        assert "MYPROG" in values

    def test_value_clause_uppercase_lookup(self):
        """Variable name lookup should be case-insensitive."""
        source = (
            BOILERPLATE_HEADER
            + "       01 PROG-NAME PIC X(8) VALUE 'MYPROG'.\n"
            + BOILERPLATE_PROC
            + "           CALL PROG-NAME.\n"
            + "           STOP RUN.\n"
        )
        analyzer = DynamicCallAnalyzer()
        ast = _parse(source)
        analyzer.analyze(ast)
        assert analyzer.get_variable_values("prog-name") == analyzer.get_variable_values(
            "PROG-NAME"
        )

    def test_get_all_tracked_variables_after_value_clause(self):
        source = (
            BOILERPLATE_HEADER
            + "       01 PROG-NAME PIC X(8) VALUE 'MYPROG'.\n"
            + "       01 OTHER-VAR PIC X(8) VALUE 'OTHER'.\n"
            + BOILERPLATE_PROC
            + "           CALL PROG-NAME.\n"
            + "           STOP RUN.\n"
        )
        analyzer = DynamicCallAnalyzer()
        ast = _parse(source)
        analyzer.analyze(ast)
        tracked = analyzer.get_all_tracked_variables()
        assert "PROG-NAME" in tracked
        assert "OTHER-VAR" in tracked


class TestMoveStatementTracking:
    """Tests for MOVE statement value tracking."""

    def test_move_literal_to_variable_tracked(self):
        source = (
            BOILERPLATE_HEADER
            + "       01 PROG-NAME PIC X(8).\n"
            + BOILERPLATE_PROC
            + "           MOVE 'SUBPROG' TO PROG-NAME.\n"
            + "           CALL PROG-NAME.\n"
            + "           STOP RUN.\n"
        )
        analyzer = DynamicCallAnalyzer()
        ast = _parse(source)
        analyzer.analyze(ast)
        values = analyzer.get_variable_values("PROG-NAME")
        assert "SUBPROG" in values

    def test_multiple_moves_accumulate_values(self):
        source = (
            BOILERPLATE_HEADER
            + "       01 PROG-NAME PIC X(8).\n"
            + "       01 FLAG PIC 9.\n"
            + BOILERPLATE_PROC
            + "           MOVE 'PROG-A' TO PROG-NAME.\n"
            + "           CALL PROG-NAME.\n"
            + "           MOVE 'PROG-B' TO PROG-NAME.\n"
            + "           CALL PROG-NAME.\n"
            + "           STOP RUN.\n"
        )
        analyzer = DynamicCallAnalyzer()
        ast = _parse(source)
        analyzer.analyze(ast)
        values = analyzer.get_variable_values("PROG-NAME")
        assert "PROG-A" in values
        assert "PROG-B" in values

    def test_move_variable_to_variable_propagates(self):
        source = (
            BOILERPLATE_HEADER
            + "       01 SOURCE-VAR PIC X(8) VALUE 'ORIG-PROG'.\n"
            + "       01 DEST-VAR PIC X(8).\n"
            + BOILERPLATE_PROC
            + "           MOVE SOURCE-VAR TO DEST-VAR.\n"
            + "           CALL DEST-VAR.\n"
            + "           STOP RUN.\n"
        )
        analyzer = DynamicCallAnalyzer()
        ast = _parse(source)
        analyzer.analyze(ast)
        values = analyzer.get_variable_values("DEST-VAR")
        assert "ORIG-PROG" in values


class TestDynamicCallPopulation:
    """Tests for dynamic CALL possible_values population."""

    def test_dynamic_call_populated_from_value_clause(self):
        source = (
            BOILERPLATE_HEADER
            + "       01 PROG-NAME PIC X(8) VALUE 'MYPROG'.\n"
            + BOILERPLATE_PROC
            + "           CALL PROG-NAME.\n"
            + "           STOP RUN.\n"
        )
        analyzer = DynamicCallAnalyzer()
        ast = _parse(source)
        analyzer.analyze(ast)

        calls = ast.find_statements("CALL")
        dynamic_calls = [c for c in calls if c.is_dynamic]
        assert len(dynamic_calls) >= 1
        assert "MYPROG" in dynamic_calls[0].possible_values

    def test_dynamic_call_populated_from_move(self):
        source = (
            BOILERPLATE_HEADER
            + "       01 PROG-NAME PIC X(8).\n"
            + BOILERPLATE_PROC
            + "           MOVE 'CALLED-PROG' TO PROG-NAME.\n"
            + "           CALL PROG-NAME.\n"
            + "           STOP RUN.\n"
        )
        analyzer = DynamicCallAnalyzer()
        ast = _parse(source)
        analyzer.analyze(ast)

        calls = ast.find_statements("CALL")
        dynamic_calls = [c for c in calls if c.is_dynamic]
        assert len(dynamic_calls) >= 1
        assert "CALLED-PROG" in dynamic_calls[0].possible_values

    def test_static_call_not_affected(self):
        source = (
            BOILERPLATE_HEADER
            + "       01 DUMMY PIC X.\n"
            + BOILERPLATE_PROC
            + "           CALL 'STATIC-PROG'.\n"
            + "           STOP RUN.\n"
        )
        analyzer = DynamicCallAnalyzer()
        ast = _parse(source)
        analyzer.analyze(ast)

        calls = ast.find_statements("CALL")
        static_calls = [c for c in calls if not c.is_dynamic]
        assert len(static_calls) >= 1
        # Static calls should have empty possible_values
        assert static_calls[0].possible_values == []


class TestExtractLiteralValue:
    """Tests for _extract_literal_value internal logic via public API."""

    def test_figurative_zero_tracked(self):
        source = (
            BOILERPLATE_HEADER
            + "       01 PROG-NAME PIC X(8).\n"
            + BOILERPLATE_PROC
            + "           MOVE ZERO TO PROG-NAME.\n"
            + "           CALL PROG-NAME.\n"
            + "           STOP RUN.\n"
        )
        analyzer = DynamicCallAnalyzer()
        ast = _parse(source)
        analyzer.analyze(ast)
        values = analyzer.get_variable_values("PROG-NAME")
        assert "0" in values

    def test_figurative_space_tracked(self):
        source = (
            BOILERPLATE_HEADER
            + "       01 PROG-NAME PIC X(8).\n"
            + BOILERPLATE_PROC
            + "           MOVE SPACE TO PROG-NAME.\n"
            + "           CALL PROG-NAME.\n"
            + "           STOP RUN.\n"
        )
        analyzer = DynamicCallAnalyzer()
        ast = _parse(source)
        analyzer.analyze(ast)
        values = analyzer.get_variable_values("PROG-NAME")
        assert " " in values
