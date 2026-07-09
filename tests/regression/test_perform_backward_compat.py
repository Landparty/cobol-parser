"""
Regression tests for PERFORM statement backward compatibility.

These tests validate that all existing PERFORM variants continue to work
correctly after the Phase 2 parser enhancements (WITH TEST support,
variable TIMES support).
"""

from cobolparser import CobolParser, ErrorRecoveryMode
from cobolparser.models.statements import PerformStatement


class TestPerformBackwardCompatibilityRegression:
    """Test backward compatibility of all PERFORM variants."""

    def _parse_cobol(self, cobol_text):
        """Helper to parse COBOL code."""
        parser = CobolParser(error_recovery=ErrorRecoveryMode.COLLECT_ALL)
        return parser.parse(cobol_text)

    def _find_perform_statements(self, ast, perform_type=None):
        """Find PERFORM statements in AST by type."""
        if not ast:
            return []

        proc_div = ast.get_division("PROCEDURE")
        if not proc_div:
            return []

        performs = []
        for section in proc_div.sections:
            # Check direct children (old architecture)
            if hasattr(section, "children"):
                for child in section.children:
                    if isinstance(child, PerformStatement):
                        if perform_type is None or child.perform_type == perform_type:
                            performs.append(child)

            # Check statements in paragraphs (new architecture)
            # Handle both CobolSection (has .paragraphs) and CobolParagraph (has .statements directly)
            if hasattr(section, "paragraphs"):
                for para in section.paragraphs:
                    for stmt in para.statements:
                        if isinstance(stmt, PerformStatement):
                            if (
                                perform_type is None
                                or stmt.perform_type == perform_type
                            ):
                                performs.append(stmt)
            elif hasattr(section, "statements"):
                # If section is a CobolParagraph, statements are directly on it
                for stmt in section.statements:
                    if isinstance(stmt, PerformStatement):
                        if perform_type is None or stmt.perform_type == perform_type:
                            performs.append(stmt)

        return performs

    def test_perform_simple_paragraph_only(self):
        """Test PERFORM paragraph-name (simple, no options)."""
        cobol = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. TEST-SIMPLE-PERFORM.
       PROCEDURE DIVISION.
           PERFORM CALCULATE-TOTAL.
           STOP RUN.
       CALCULATE-TOTAL.
           MOVE 100 TO TOTAL.
       """
        result = self._parse_cobol(cobol)
        assert result.ast is not None

        performs = self._find_perform_statements(result.ast, "SIMPLE")
        assert len(performs) >= 1
        perf = performs[0]

        # Verify target paragraph is set
        assert perf.target_paragraph == "CALCULATE-TOTAL"
        # Verify no THRU clause
        assert perf.thru_paragraph is None
        # Verify test_timing defaults to BEFORE
        assert perf.test_timing == "BEFORE"

    def test_perform_paragraph_thru_paragraph(self):
        """Test PERFORM paragraph-name THRU paragraph-name."""
        cobol = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. TEST-THRU-PERFORM.
       PROCEDURE DIVISION.
           PERFORM PROCESS-RECORDS THRU END-PROCESS.
           STOP RUN.
       PROCESS-RECORDS.
           MOVE 0 TO RECORD-COUNT.
       END-PROCESS.
           MOVE RECORD-COUNT TO OUTPUT-COUNT.
       """
        result = self._parse_cobol(cobol)
        assert result.ast is not None

        performs = self._find_perform_statements(result.ast, "SIMPLE")
        assert len(performs) >= 1
        perf = performs[0]

        # Verify both paragraphs are set
        assert perf.target_paragraph == "PROCESS-RECORDS"
        assert perf.thru_paragraph == "END-PROCESS"

    def test_perform_until_condition(self):
        """Test PERFORM paragraph UNTIL condition."""
        cobol = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. TEST-UNTIL-SIMPLE.
       PROCEDURE DIVISION.
           PERFORM CHECK-DONE UNTIL DONE-FLAG = Y.
           STOP RUN.
       CHECK-DONE.
           MOVE Y TO DONE-FLAG.
       """
        result = self._parse_cobol(cobol)
        assert result.ast is not None

        performs = self._find_perform_statements(result.ast, "UNTIL")
        assert len(performs) >= 1
        perf = performs[0]

        # Verify until_condition is set
        assert perf.until_condition is not None
        # Verify perform_type is UNTIL
        assert perf.perform_type == "UNTIL"

    def test_perform_varying_until_inline(self):
        """Test PERFORM VARYING ... UNTIL (inline END-PERFORM)."""
        cobol = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. TEST-VARYING-INLINE.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 I PIC 9(3).
       PROCEDURE DIVISION.
           PERFORM VARYING I FROM 1 BY 1 UNTIL I > 5
               DISPLAY I
           END-PERFORM.
           STOP RUN.
       """
        result = self._parse_cobol(cobol)
        assert result.ast is not None

        performs = self._find_perform_statements(result.ast, "VARYING")
        assert len(performs) >= 1
        perf = performs[0]

        # Verify it's a VARYING statement
        assert perf.perform_type == "VARYING"
        # Verify varying_clause is set
        assert perf.varying_clause is not None
        # Verify until_condition is set
        assert perf.until_condition is not None

    def test_perform_backward_compat_test_timing_not_breaking(self):
        """Verify that adding WITH TEST support doesn't break existing PERFORM."""
        cobol = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. TEST-COMPAT.
       PROCEDURE DIVISION.
           PERFORM MY-PARA.
           STOP RUN.
       MY-PARA.
           MOVE 1 TO X.
       """
        result = self._parse_cobol(cobol)
        assert result.ast is not None

        performs = self._find_perform_statements(result.ast, "SIMPLE")
        assert len(performs) >= 1
        perf = performs[0]

        # Verify test_timing still defaults to BEFORE even for old-style PERFORM
        assert perf.test_timing == "BEFORE"
        # Verify to_dict() includes test_timing
        perf_dict = perf.to_dict()
        assert "test_timing" in perf_dict
        assert perf_dict["test_timing"] == "BEFORE"

    def test_perform_variable_times_count_not_breaking(self):
        """Verify that adding variable TIMES support doesn't break numeric TIMES.

        This is also the out-of-line PERFORM ... THRU ... VARYING ... form
        (target paragraph + VARYING, no inline body). Previously this
        assertion only checked `len(performs) >= 1`, which passed even
        though the VARYING clause was silently dropped and `perform_type`
        stayed the default "SIMPLE" -- see
        `TestPerformVaryingOutOfLine` below for the dedicated regression
        coverage of that bug.
        """
        cobol = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. TEST-VAR-TIMES.
       PROCEDURE DIVISION.
           PERFORM MY-LOOP THRU MY-LOOP-END
               VARYING WS-COUNT FROM 1 BY 1 UNTIL WS-COUNT > 5.
           STOP RUN.
       MY-LOOP.
           DISPLAY "LOOP".
       MY-LOOP-END.
           DISPLAY "END".
       """
        result = self._parse_cobol(cobol)
        assert result.ast is not None

        performs = self._find_perform_statements(result.ast)
        # Should find at least one perform statement
        assert len(performs) >= 1
        perf = performs[0]

        assert perf.perform_type == "VARYING"
        assert perf.target_paragraph == "MY-LOOP"
        assert perf.thru_paragraph == "MY-LOOP-END"
        assert perf.varying_clause == {
            "variable": "WS-COUNT",
            "from_value": "1",
            "by_value": "1",
        }
        assert perf.until_condition is not None


class TestPerformVaryingOutOfLine:
    """Regression tests for the out-of-line PERFORM ... VARYING ... form
    (a target paragraph followed by VARYING, as opposed to the inline
    `PERFORM VARYING ... END-PERFORM` form). Previously this shape was not
    handled at all: the VARYING token matched none of the out-of-line
    branches (TIMES/WITH TEST/UNTIL), so the clause was left unconsumed for
    the generic "unparsed tokens" recovery to discard, and `perform_type`
    stayed the default "SIMPLE" -- indistinguishable from a genuine plain
    `PERFORM MY-LOOP.` to any caller keyed off `perform_type`.
    """

    def _parse_cobol(self, cobol_text):
        parser = CobolParser(error_recovery=ErrorRecoveryMode.COLLECT_ALL)
        return parser.parse(cobol_text)

    def _first_perform(self, ast):
        proc_div = ast.get_division("PROCEDURE")
        for section in proc_div.sections:
            if hasattr(section, "children"):
                for child in section.children:
                    if isinstance(child, PerformStatement):
                        return child
            if hasattr(section, "paragraphs"):
                for paragraph in section.paragraphs:
                    if hasattr(paragraph, "statements"):
                        for stmt in paragraph.statements:
                            if isinstance(stmt, PerformStatement):
                                return stmt
            if hasattr(section, "statements"):
                for stmt in section.statements:
                    if isinstance(stmt, PerformStatement):
                        return stmt
        return None

    def test_out_of_line_varying_fully_parsed(self):
        """PERFORM para VARYING i FROM x BY y UNTIL cond -- the well-formed
        case: perform_type is "VARYING", the clause data is captured, and
        no warning is emitted."""
        cobol = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. TEST-OOL-VARYING.
       PROCEDURE DIVISION.
       MAIN-PARA.
           PERFORM VARY-PARA VARYING WS-I FROM 1 BY 1 UNTIL WS-I > 10.
           STOP RUN.
       VARY-PARA.
           DISPLAY WS-I.
       """
        result = self._parse_cobol(cobol)
        assert result.ast is not None
        assert result.errors == []
        assert result.warnings == []

        perf = self._first_perform(result.ast)
        assert perf is not None
        assert perf.target_paragraph == "VARY-PARA"
        assert perf.perform_type == "VARYING"
        assert perf.varying_clause == {
            "variable": "WS-I",
            "from_value": "1",
            "by_value": "1",
        }
        assert perf.until_condition is not None

    def test_out_of_line_varying_missing_until_still_tagged_varying(self):
        """PERFORM para VARYING i FROM x BY y. (no UNTIL) is a malformed/
        incomplete VARYING clause -- `varying_clause` correctly stays
        unset, but `perform_type` must still be "VARYING", not silently
        fall back to the default "SIMPLE" the way a genuine plain PERFORM
        would report. This is the assertion that pins the actual bug: the
        keyword's presence, not a fully successful sub-parse, is what
        determines the tag."""
        cobol = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. TEST-OOL-VARYING-NO-UNTIL.
       PROCEDURE DIVISION.
       MAIN-PARA.
           PERFORM VARY-PARA VARYING WS-I FROM 1 BY 1.
           STOP RUN.
       VARY-PARA.
           DISPLAY WS-I.
       """
        result = self._parse_cobol(cobol)
        assert result.ast is not None

        perf = self._first_perform(result.ast)
        assert perf is not None
        assert perf.target_paragraph == "VARY-PARA"
        assert perf.perform_type == "VARYING"
        assert perf.varying_clause is None
        # The degraded clause is now surfaced via a warning instead of
        # being fully silent.
        assert any("VARYING" in w for w in result.warnings)

    def test_out_of_line_varying_not_confused_with_simple_perform(self):
        """A genuine plain `PERFORM para.` (no VARYING at all) must still
        report perform_type "SIMPLE" -- guards against a fix that tags
        every out-of-line PERFORM as VARYING regardless of the source."""
        cobol = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. TEST-PLAIN-PERFORM.
       PROCEDURE DIVISION.
       MAIN-PARA.
           PERFORM SOME-PARA.
           STOP RUN.
       SOME-PARA.
           DISPLAY "HELLO".
       """
        result = self._parse_cobol(cobol)
        assert result.ast is not None

        perf = self._first_perform(result.ast)
        assert perf is not None
        assert perf.target_paragraph == "SOME-PARA"
        assert perf.perform_type == "SIMPLE"
        assert perf.varying_clause is None


class TestPerformEdgeCasesRegression:
    """Test edge cases and error conditions in PERFORM statements."""

    def _parse_cobol(self, cobol_text):
        """Helper to parse COBOL code."""
        parser = CobolParser(error_recovery=ErrorRecoveryMode.COLLECT_ALL)
        return parser.parse(cobol_text)

    def _find_perform_statements(self, ast, perform_type=None):
        """Find PERFORM statements in AST by type."""
        if not ast:
            return []

        proc_div = ast.get_division("PROCEDURE")
        if not proc_div:
            return []

        performs = []
        for section in proc_div.sections:
            # Check direct children (old architecture)
            if hasattr(section, "children"):
                for child in section.children:
                    if isinstance(child, PerformStatement):
                        if perform_type is None or child.perform_type == perform_type:
                            performs.append(child)

            # Check statements in paragraphs (new architecture)
            # Handle both CobolSection (has .paragraphs) and CobolParagraph (has .statements directly)
            if hasattr(section, "paragraphs"):
                for para in section.paragraphs:
                    for stmt in para.statements:
                        if isinstance(stmt, PerformStatement):
                            if (
                                perform_type is None
                                or stmt.perform_type == perform_type
                            ):
                                performs.append(stmt)
            elif hasattr(section, "statements"):
                # If section is a CobolParagraph, statements are directly on it
                for stmt in section.statements:
                    if isinstance(stmt, PerformStatement):
                        if perform_type is None or stmt.perform_type == perform_type:
                            performs.append(stmt)

        return performs

    def test_perform_serialization_preserves_attributes(self):
        """Test that to_dict() preserves all PERFORM attributes."""
        cobol = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. TEST-SER.
       PROCEDURE DIVISION.
           PERFORM MY-PARA THRU END-PARA.
           STOP RUN.
       MY-PARA.
           MOVE 1 TO X.
       END-PARA.
           MOVE 2 TO Y.
       """
        result = self._parse_cobol(cobol)
        assert result.ast is not None

        performs = self._find_perform_statements(result.ast, "SIMPLE")
        assert len(performs) >= 1
        perf = performs[0]

        # Serialize and verify structure
        perf_dict = perf.to_dict()
        assert perf_dict["node_type"] == "Statement"
        assert perf_dict["target_paragraph"] == "MY-PARA"
        assert perf_dict["thru_paragraph"] == "END-PARA"
        assert perf_dict["test_timing"] == "BEFORE"  # Default value

    def test_perform_two_in_sequence(self):
        """Test two PERFORM statements in sequence."""
        cobol = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. TEST-TWO-PERFORM.
       PROCEDURE DIVISION.
           PERFORM PARA-ONE.
           PERFORM PARA-TWO THRU PARA-TWO-END.
           STOP RUN.
       PARA-ONE.
           DISPLAY "ONE".
       PARA-TWO.
           DISPLAY "TWO".
       PARA-TWO-END.
           DISPLAY "TWO-END".
       """
        result = self._parse_cobol(cobol)
        assert result.ast is not None

        # Should find both PERFORM statements
        all_performs = self._find_perform_statements(result.ast)
        assert len(all_performs) >= 2

        # Verify types
        simple_performs = self._find_perform_statements(result.ast, "SIMPLE")
        assert (
            len(simple_performs) >= 2
        )  # Both PERFORM statements should be SIMPLE type
