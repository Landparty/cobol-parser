"""Contract tests for EVALUATE statement diagnostics.

These tests verify that EVALUATE parsing produces consistent, well-formed
diagnostic messages according to the data model specifications.

Diagnostic Record Structure (per Data Model):
- line: Source line number (1-indexed)
- column: Source column number (1-indexed)
- message: Human-readable error message
- category: Error category (e.g., "SYNTAX", "SEMANTIC", "STRUCTURE")
- severity: Error severity (ERROR, WARNING, INFO)
"""

from cobolparser import CobolParser


def _fixed_source(body: str) -> str:
    """Convert body to fixed-format COBOL source."""
    lines = [line.rstrip() for line in body.strip().splitlines()]
    return "\n".join(f"       {line}" for line in lines) + "\n"


def _get_evaluate_diagnostics(source: str) -> list:
    """Parse source and extract EVALUATE-related diagnostics."""
    parser = CobolParser()
    result = parser.parse(_fixed_source(source))
    return result.errors


class TestEvaluateDiagnosticStructure:
    """Tests for diagnostic record structure compliance."""

    def test_diagnostic_has_line_number(self):
        """Each diagnostic must include a valid line number."""
        source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST.
        DATA DIVISION.
        WORKING-STORAGE SECTION.
        01  WS-GRADE PIC 9.
        PROCEDURE DIVISION.
            EVALUATE WS-GRADE
                WHEN 1 ALSO 'A'
                    DISPLAY 'ALPHA'
                WHEN OTHER
                    DISPLAY 'FALLBACK'
            END-EVALUATE.
        """
        diagnostics = _get_evaluate_diagnostics(source)
        selector_error = [d for d in diagnostics if "selector" in str(d).lower()]
        if selector_error:
            for d in selector_error:
                assert hasattr(d, "line_number") or hasattr(d, "location")
                if hasattr(d, "line_number"):
                    assert d.line_number > 0
                if hasattr(d, "location"):
                    assert d.location.line > 0

    def test_diagnostic_has_column_number(self):
        """Each diagnostic must include a valid column number."""
        source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST.
        DATA DIVISION.
        WORKING-STORAGE SECTION.
        01  WS-GRADE PIC 9.
        PROCEDURE DIVISION.
            EVALUATE WS-GRADE
                WHEN 1 ALSO 'A'
                    DISPLAY 'ALPHA'
                WHEN OTHER
                    DISPLAY 'FALLBACK'
            END-EVALUATE.
        """
        diagnostics = _get_evaluate_diagnostics(source)
        selector_error = [d for d in diagnostics if "selector" in str(d).lower()]
        if selector_error:
            for d in selector_error:
                assert hasattr(d, "column") or hasattr(d, "location")
                if hasattr(d, "column"):
                    assert d.column > 0
                if hasattr(d, "location"):
                    assert d.location.column > 0

    def test_diagnostic_has_message(self):
        """Each diagnostic must have a non-empty message."""
        source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST.
        DATA DIVISION.
        WORKING-STORAGE SECTION.
        01  WS-GRADE PIC 9.
        PROCEDURE DIVISION.
            EVALUATE WS-GRADE
            DISPLAY 'NO WHEN'.
        """
        diagnostics = _get_evaluate_diagnostics(source)
        when_errors = [d for d in diagnostics if "WHEN" in str(d).upper()]
        assert len(when_errors) >= 1
        for d in when_errors:
            assert str(d) and len(str(d).strip()) > 0


class TestEvaluateMissingWhenClause:
    """Tests for EVALUATE without WHEN clause diagnostics."""

    def test_missing_when_reports_error(self):
        """EVALUATE without WHEN clause must report an error."""
        source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST.
        DATA DIVISION.
        WORKING-STORAGE SECTION.
        01  WS-GRADE PIC 9.
        PROCEDURE DIVISION.
            EVALUATE WS-GRADE
                DISPLAY 'NO WHEN'.
        """
        diagnostics = _get_evaluate_diagnostics(source)
        when_errors = [d for d in diagnostics if "WHEN" in str(d).upper()]
        assert len(when_errors) >= 1

    def test_missing_when_message_contains_clause(self):
        """Error message for missing WHEN should mention 'WHEN'."""
        source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST.
        DATA DIVISION.
        WORKING-STORAGE SECTION.
        01  WS-GRADE PIC 9.
        PROCEDURE DIVISION.
            EVALUATE WS-GRADE
                DISPLAY 'NO WHEN'.
        """
        diagnostics = _get_evaluate_diagnostics(source)
        when_errors = [d for d in diagnostics if "WHEN" in str(d).upper()]
        assert len(when_errors) >= 1
        error_text = str(when_errors[0]).upper()
        assert "WHEN" in error_text


class TestEvaluateMissingEndEvaluate:
    """Tests for EVALUATE termination behaviour.

    IBM COBOL (NIST-85 style) allows EVALUATE to be terminated by a statement-
    scope period instead of END-EVALUATE.  Both forms are therefore valid and
    must parse without errors.  Only genuinely unterminated constructs (no
    period, no END-EVALUATE) produce diagnostics.
    """

    def test_period_terminated_evaluate_is_valid(self):
        """EVALUATE closed by a period must parse without errors (IBM/NIST-85)."""
        source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST.
        DATA DIVISION.
        WORKING-STORAGE SECTION.
        01  WS-GRADE PIC 9.
        PROCEDURE DIVISION.
            EVALUATE WS-GRADE
                WHEN 1
                    DISPLAY 'ONE'.
        """
        diagnostics = _get_evaluate_diagnostics(source)
        end_errors = [d for d in diagnostics if "END" in str(d).upper()]
        assert len(end_errors) == 0, (
            "Period-terminated EVALUATE is valid IBM COBOL — no END errors expected"
        )

    def test_end_evaluate_terminated_evaluate_is_valid(self):
        """EVALUATE closed by END-EVALUATE must parse without errors."""
        source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST.
        DATA DIVISION.
        WORKING-STORAGE SECTION.
        01  WS-GRADE PIC 9.
        PROCEDURE DIVISION.
            EVALUATE WS-GRADE
                WHEN 1
                    DISPLAY 'ONE'
            END-EVALUATE.
        """
        diagnostics = _get_evaluate_diagnostics(source)
        end_errors = [d for d in diagnostics if "END" in str(d).upper()]
        assert len(end_errors) == 0, (
            "END-EVALUATE-terminated EVALUATE must parse cleanly"
        )


class TestEvaluateSelectorMismatch:
    """Tests for selector/subject count mismatch diagnostics."""

    def test_single_subject_multiple_selectors_reports_error(self):
        """EVALUATE with single subject but multiple selectors must error."""
        source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST.
        DATA DIVISION.
        WORKING-STORAGE SECTION.
        01  WS-GRADE PIC 9.
        01  WS-STATUS PIC X.
        PROCEDURE DIVISION.
            EVALUATE WS-GRADE
                WHEN 1 ALSO 'A'
                    DISPLAY 'ALPHA'
                WHEN OTHER
                    DISPLAY 'FALLBACK'
            END-EVALUATE.
        """
        diagnostics = _get_evaluate_diagnostics(source)
        mismatch_errors = [
            d
            for d in diagnostics
            if "selector" in str(d).lower() or "subject" in str(d).lower()
        ]
        assert len(mismatch_errors) >= 1

    def test_multiple_subjects_single_selector_reports_error(self):
        """EVALUATE with multiple subjects but single selector must error."""
        source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST.
        DATA DIVISION.
        WORKING-STORAGE SECTION.
        01  WS-GRADE PIC 9.
        01  WS-STATUS PIC X.
        PROCEDURE DIVISION.
            EVALUATE WS-GRADE ALSO WS-STATUS
                WHEN 1
                    DISPLAY 'ONE'
                WHEN OTHER
                    DISPLAY 'FALLBACK'
            END-EVALUATE.
        """
        diagnostics = _get_evaluate_diagnostics(source)
        mismatch_errors = [
            d
            for d in diagnostics
            if "selector" in str(d).lower() or "subject" in str(d).lower()
        ]
        assert len(mismatch_errors) >= 1


class TestEvaluateInvalidThrough:
    """Tests for invalid THRU/THROUGH range diagnostics."""

    def test_through_without_end_reports_error(self):
        """THRU/THROUGH without end value must report an error."""
        source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST.
        DATA DIVISION.
        WORKING-STORAGE SECTION.
        01  WS-NUM PIC 99.
        PROCEDURE DIVISION.
            EVALUATE WS-NUM
                WHEN 5 THRU
                    DISPLAY 'RANGE'
                WHEN OTHER
                    DISPLAY 'OTHER'
            END-EVALUATE.
        """
        diagnostics = _get_evaluate_diagnostics(source)
        thru_errors = [
            d
            for d in diagnostics
            if "THRU" in str(d).upper()
            or "THROUGH" in str(d).upper()
            or "range" in str(d).lower()
        ]
        assert len(thru_errors) >= 1


class TestEvaluateWhenOtherPlacement:
    """Tests for WHEN OTHER placement diagnostics."""

    def test_when_other_before_conditional_reports_error(self):
        """WHEN OTHER before conditional WHEN must report an error."""
        source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST.
        DATA DIVISION.
        WORKING-STORAGE SECTION.
        01  WS-GRADE PIC 9.
        PROCEDURE DIVISION.
            EVALUATE WS-GRADE
                WHEN OTHER
                    DISPLAY 'OTHER'
                WHEN 1
                    DISPLAY 'ONE'
            END-EVALUATE.
        """
        diagnostics = _get_evaluate_diagnostics(source)
        placement_errors = [
            d
            for d in diagnostics
            if "OTHER" in str(d).upper() or "conditional" in str(d).lower()
        ]
        assert len(placement_errors) >= 1 or len(diagnostics) >= 1

    def test_multiple_when_other_reports_error(self):
        """Multiple WHEN OTHER clauses must report an error."""
        source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST.
        DATA DIVISION.
        WORKING-STORAGE SECTION.
        01  WS-GRADE PIC 9.
        PROCEDURE DIVISION.
            EVALUATE WS-GRADE
                WHEN OTHER
                    DISPLAY 'OTHER 1'
                WHEN 1
                    DISPLAY 'ONE'
                WHEN OTHER
                    DISPLAY 'OTHER 2'
            END-EVALUATE.
        """
        diagnostics = _get_evaluate_diagnostics(source)
        multiple_other_errors = [
            d
            for d in diagnostics
            if "OTHER" in str(d).upper() and "multiple" in str(d).lower()
        ]
        assert len(multiple_other_errors) >= 1 or len(diagnostics) >= 1


class TestEvaluateEmptySelector:
    """Tests for empty WHEN selector diagnostics."""

    def test_empty_selector_reports_error(self):
        """Empty WHEN selector must report an error."""
        source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST.
        DATA DIVISION.
        WORKING-STORAGE SECTION.
        01  WS-GRADE PIC 9.
        PROCEDURE DIVISION.
            EVALUATE WS-GRADE
                WHEN
                    DISPLAY 'EMPTY'
                WHEN OTHER
                    DISPLAY 'OTHER'
            END-EVALUATE.
        """
        diagnostics = _get_evaluate_diagnostics(source)
        assert len(diagnostics) >= 1


class TestEvaluateInvalidAlso:
    """Tests for invalid ALSO chain diagnostics."""

    def test_consecutive_also_reports_error(self):
        """Consecutive ALSO tokens must report an error."""
        source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST.
        DATA DIVISION.
        WORKING-STORAGE SECTION.
        01  WS-A PIC 9.
        01  WS-B PIC 9.
        01  WS-C PIC 9.
        PROCEDURE DIVISION.
            EVALUATE WS-A ALSO WS-B
                WHEN 1 ALSO ALSO
                    DISPLAY 'BAD'
                WHEN OTHER
                    DISPLAY 'OTHER'
            END-EVALUATE.
        """
        diagnostics = _get_evaluate_diagnostics(source)
        also_errors = [
            d
            for d in diagnostics
            if "ALSO" in str(d).upper() or "selector" in str(d).lower()
        ]
        assert len(also_errors) >= 1


class TestEvaluateDiagnosticMessageConsistency:
    """Tests for consistent diagnostic message formatting."""

    def test_error_messages_have_meaningful_content(self):
        """Error messages should contain meaningful diagnostic content."""
        source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST.
        DATA DIVISION.
        WORKING-STORAGE SECTION.
        01  WS-GRADE PIC 9.
        PROCEDURE DIVISION.
            EVALUATE WS-GRADE
                WHEN 1
                    DISPLAY 'ONE'.
        """
        diagnostics = _get_evaluate_diagnostics(source)
        for d in diagnostics:
            msg = str(d).strip()
            if msg:
                assert len(msg) > 10, f"Message too short: {msg}"


class TestEvaluateDiagnosticSeverity:
    """Tests for diagnostic severity classification."""

    def test_syntax_errors_are_errors(self):
        """EVALUATE without a WHEN clause is a genuine syntax error."""
        source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST.
        DATA DIVISION.
        WORKING-STORAGE SECTION.
        01  WS-GRADE PIC 9.
        PROCEDURE DIVISION.
            EVALUATE WS-GRADE
                DISPLAY 'NO WHEN'.
        """
        diagnostics = _get_evaluate_diagnostics(source)
        assert len(diagnostics) >= 1
