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
        assert analyzer.get_variable_values(
            "prog-name"
        ) == analyzer.get_variable_values("PROG-NAME")

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

    def test_value_clause_figurative_constant_matches_move_of_same_constant(self):
        """Regression: a variable initialized ``VALUE SPACES`` and later also
        ``MOVE``d SPACES must collapse to one canonical value (" "), not
        survive as both the raw VALUE-clause keyword text ("SPACES") and the
        MOVE-resolved value (" "). Mirrors the real-world pattern in
        examples/cobol/legacy-application/cobol/JOBDISP.cbl, where
        WS-CALL-PROGRAM is declared ``VALUE SPACES`` and a later
        ``WHEN OTHER MOVE SPACES TO WS-CALL-PROGRAM`` branch feeds a dynamic
        CALL -- both routes into possible_values must agree.
        """
        source = (
            BOILERPLATE_HEADER
            + "       01 WS-CALL-PROGRAM PIC X(8) VALUE SPACES.\n"
            + BOILERPLATE_PROC
            + "           IF 1 = 2\n"
            + "               MOVE 'PROGA' TO WS-CALL-PROGRAM\n"
            + "           ELSE\n"
            + "               MOVE SPACES TO WS-CALL-PROGRAM\n"
            + "           END-IF\n"
            + "           CALL WS-CALL-PROGRAM.\n"
            + "           STOP RUN.\n"
        )
        analyzer = DynamicCallAnalyzer()
        ast = _parse(source)
        analyzer.analyze(ast)
        values = analyzer.get_variable_values("WS-CALL-PROGRAM")
        assert " " in values
        assert "SPACES" not in values

        calls = [
            stmt for stmt in ast.find_all_by_type("CallStatement") if stmt.is_dynamic
        ]
        assert len(calls) == 1
        assert " " in calls[0].possible_values
        assert "SPACES" not in calls[0].possible_values


class TestRedefinesOverlap:
    """Regression for #257: a write through a REDEFINES overlay changes the
    bytes a dynamic CALL reads, so its possible_values are not exhaustive."""

    ISSUE_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. ANA7.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-AREA     PIC X(8).
       01 WS-PGMN REDEFINES WS-AREA PIC X(8).
       01 WS-REC.
          05 WS-HDR   PIC X(2).
          05 WS-NM    PIC X(8).
       01 WS-REC2 REDEFINES WS-REC.
          05 FILLER   PIC X(2).
          05 WS-NM2   PIC X(8).
       PROCEDURE DIVISION.
           MOVE 'PGMY' TO WS-PGMN
           MOVE 'PGMZ' TO WS-AREA
           CALL WS-PGMN
           MOVE 'PGMA' TO WS-NM2
           MOVE 'XXPGMB' TO WS-REC
           CALL WS-NM2
           STOP RUN.
"""

    @staticmethod
    def _calls(source: str) -> dict:
        ast = _parse(source)
        DynamicCallAnalyzer().analyze(ast)
        return {
            c.called_program: c
            for c in ast.find_all_by_type("CallStatement")
            if c.is_dynamic
        }

    def test_move_to_the_redefined_item_marks_the_redefiner_incomplete(self):
        call = self._calls(self.ISSUE_SOURCE)["WS-PGMN"]
        assert call.possible_values == ["PGMY"]
        assert call.get_metadata("possible_values_incomplete") is True

    def test_move_to_a_redefined_group_marks_an_overlay_child_incomplete(self):
        call = self._calls(self.ISSUE_SOURCE)["WS-NM2"]
        assert call.possible_values == ["PGMA"]
        assert call.get_metadata("possible_values_incomplete") is True

    def test_move_to_the_redefiner_marks_the_redefined_item_incomplete(self):
        source = (
            BOILERPLATE_HEADER
            + "       01 WS-AREA     PIC X(8) VALUE 'PGMA'.\n"
            + "       01 WS-ALT REDEFINES WS-AREA.\n"
            + "          05 WS-ALT-1 PIC X(4).\n"
            + "          05 WS-ALT-2 PIC X(4).\n"
            + BOILERPLATE_PROC
            + "           MOVE 'ZZZZ' TO WS-ALT-2\n"
            + "           CALL WS-AREA\n"
            + "           STOP RUN.\n"
        )
        call = self._calls(source)["WS-AREA"]
        assert call.possible_values == ["PGMA"]
        assert call.get_metadata("possible_values_incomplete") is True

    def test_unrelated_redefines_leaves_the_call_complete(self):
        source = (
            BOILERPLATE_HEADER
            + "       01 WS-PROG     PIC X(8) VALUE 'PGMA'.\n"
            + "       01 WS-AREA     PIC X(8).\n"
            + "       01 WS-ALT REDEFINES WS-AREA PIC X(8).\n"
            + BOILERPLATE_PROC
            + "           MOVE 'ZZZZ' TO WS-ALT\n"
            + "           CALL WS-PROG\n"
            + "           STOP RUN.\n"
        )
        call = self._calls(source)["WS-PROG"]
        assert call.possible_values == ["PGMA"]
        assert not call.get_metadata("possible_values_incomplete")


class TestConditionSetAndMoveSources:
    """Regression for #511: ``SET cond TO TRUE`` writes the CALL variable,
    and an untracked write to a MOVE *source* reaches the CALL as well."""

    @staticmethod
    def _resolve(working_storage: str, procedure: str, name: str = "WS-PGM"):
        ast = _parse(
            BOILERPLATE_HEADER + working_storage + BOILERPLATE_PROC + procedure
        )
        analyzer = DynamicCallAnalyzer()
        analyzer.analyze(ast)
        return analyzer.resolve_variable(name)

    def test_set_condition_to_true_adds_its_value(self):
        ws = (
            "       01 WS-PGM PIC X(8) VALUE 'PGMB'.\n"
            "          88 USE-PGMA VALUE 'PGMA'.\n"
        )
        proc = "           SET USE-PGMA TO TRUE\n           CALL WS-PGM\n           GOBACK.\n"
        assert self._resolve(ws, proc) == (["PGMA", "PGMB"], False)

    def test_set_to_true_moves_the_first_literal(self):
        ws = (
            "       01 WS-PGM PIC X(8).\n"
            "          88 USE-ANY VALUE 'PGMA' 'PGMB'.\n"
            "          88 USE-RNG VALUE 'PGMC' THRU 'PGMD'.\n"
        )
        proc = (
            "           SET USE-ANY TO TRUE\n"
            "           SET USE-RNG TO TRUE\n"
            "           CALL WS-PGM\n"
            "           GOBACK.\n"
        )
        assert self._resolve(ws, proc) == (["PGMA", "PGMC"], False)

    def test_set_to_false(self):
        ws = (
            "       01 WS-PGM PIC X(8).\n"
            "          88 USE-PGMA VALUE 'PGMA' WHEN SET TO FALSE 'PGMF'.\n"
        )
        proc = "           SET USE-PGMA TO FALSE\n           CALL WS-PGM\n           GOBACK.\n"
        assert self._resolve(ws, proc) == (["PGMF"], False)

        ws = "       01 WS-PGM PIC X(8).\n          88 USE-PGMA VALUE 'PGMA'.\n"
        assert self._resolve(ws, proc) == ([], True)

    def test_set_condition_on_an_overlapping_item_is_incomplete(self):
        ws = (
            "       01 WS-CTL.\n"
            "          88 CTL-RESET VALUE 'PGMAPGMB'.\n"
            "          05 WS-PGM PIC X(4) VALUE 'PGMC'.\n"
            "          05 WS-OTHER PIC X(4).\n"
        )
        proc = "           SET CTL-RESET TO TRUE\n           CALL WS-PGM\n           GOBACK.\n"
        assert self._resolve(ws, proc) == (["PGMC"], True)

    def test_condition_name_declared_twice_is_incomplete(self):
        ws = (
            "       01 WS-PGM PIC X(8).\n"
            "          88 USE-IT VALUE 'PGMA'.\n"
            "       01 WS-OTHER PIC X(8).\n"
            "          88 USE-IT VALUE 'PGMZ'.\n"
        )
        proc = "           SET USE-IT TO TRUE\n           CALL WS-PGM\n           GOBACK.\n"
        assert self._resolve(ws, proc) == ([], True)

    def test_accepted_move_source_is_incomplete(self):
        ws = (
            "       01 WS-DEFAULT PIC X(8) VALUE 'PGMC'.\n"
            "       01 WS-MID PIC X(8).\n"
            "       01 WS-PGM PIC X(8).\n"
        )
        proc = (
            "           ACCEPT WS-DEFAULT FROM SYSIN\n"
            "           MOVE WS-DEFAULT TO WS-MID\n"
            "           MOVE WS-MID TO WS-PGM\n"
            "           CALL WS-PGM\n"
            "           GOBACK.\n"
        )
        assert self._resolve(ws, proc) == (["PGMC"], True)

    def test_untracked_move_to_a_source_group_is_incomplete(self):
        ws = (
            "       01 WS-IN PIC X(8).\n"
            "       01 WS-PGM PIC X(8).\n"
            "       01 WS-CTL.\n"
            "          05 WS-CTL-PGM PIC X(8) VALUE 'PGMD'.\n"
        )
        proc = (
            "           MOVE WS-IN TO WS-CTL\n"
            "           MOVE WS-CTL-PGM TO WS-PGM\n"
            "           CALL WS-PGM\n"
            "           GOBACK.\n"
        )
        assert self._resolve(ws, proc) == (["PGMD"], True)

    def test_literal_move_to_a_source_group_adds_its_slice(self):
        ws = (
            "       01 WS-PGM PIC X(8).\n"
            "       01 WS-CTL.\n"
            "          05 WS-CTL-HDR PIC X(2).\n"
            "          05 WS-CTL-PGM PIC X(8) VALUE 'PGMD'.\n"
        )
        proc = (
            "           MOVE 'XXPGMX' TO WS-CTL\n"
            "           MOVE WS-CTL-PGM TO WS-PGM\n"
            "           CALL WS-PGM\n"
            "           GOBACK.\n"
        )
        assert self._resolve(ws, proc) == (["PGMD", "PGMX"], False)

    def test_literal_move_to_a_table_group_is_incomplete(self):
        ws = (
            "       01 WS-PGM PIC X(8).\n"
            "       01 WS-CTL.\n"
            "          05 WS-ENT OCCURS 2 TIMES.\n"
            "             10 WS-CTL-PGM PIC X(8).\n"
        )
        proc = (
            "           MOVE 'PGMX' TO WS-CTL\n"
            "           MOVE WS-CTL-PGM (1) TO WS-PGM\n"
            "           CALL WS-PGM\n"
            "           GOBACK.\n"
        )
        values, incomplete = self._resolve(ws, proc)
        assert incomplete is True
        assert "PGMX" not in values

    def test_issue_repro_two(self):
        ws = (
            "       01 WS-DEFAULT PIC X(8) VALUE 'PGMC'.\n"
            "       01 WS-PGM PIC X(8).\n"
            "       01 WS-CTL.\n"
            "          05 WS-CTL-PGM PIC X(8) VALUE 'PGMD'.\n"
        )
        proc = (
            "           ACCEPT WS-DEFAULT FROM SYSIN\n"
            "           MOVE WS-DEFAULT TO WS-PGM\n"
            "           CALL WS-PGM\n"
            "           MOVE 'PGMX' TO WS-CTL\n"
            "           MOVE WS-CTL-PGM TO WS-PGM\n"
            "           CALL WS-PGM\n"
            "           GOBACK.\n"
        )
        assert self._resolve(ws, proc) == (["PGMC", "PGMD", "PGMX"], True)
