"""Tests for EVALUATE statement diagnostics and error handling.

Tests cover:
- Missing WHEN clause
- Missing END-EVALUATE
- Selector count mismatch between subjects and WHEN selectors
- Invalid THRU/THROUGH range syntax
- WHEN OTHER placement errors
- Invalid condition syntax in EVALUATE TRUE
"""

from cobolparser import CobolParser, ParseResult


def _fixed_source(body: str) -> str:
    """Convert body to fixed-format COBOL source."""
    lines = [line.rstrip() for line in body.strip().splitlines()]
    return "\n".join(f"       {line}" for line in lines) + "\n"


def _parse_with_errors(source: str) -> ParseResult:
    """Parse source and return result (errors expected)."""
    parser = CobolParser()
    result = parser.parse(source)
    return result


def test_evaluate_missing_when_clause():
    """EVALUATE without any WHEN clause should report diagnostic."""
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
    result = _parse_with_errors(_fixed_source(source))
    assert len(result.errors) >= 1
    error_messages = [str(e) for e in result.errors]
    when_error = [e for e in error_messages if "WHEN" in e.upper()]
    assert len(when_error) >= 1, f"Expected WHEN-related error, got: {error_messages}"


def test_evaluate_missing_end_evaluate():
    """EVALUATE without END-EVALUATE should report diagnostic."""
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
    """
    result = _parse_with_errors(_fixed_source(source))
    assert len(result.errors) >= 1
    error_messages = [str(e) for e in result.errors]
    end_error = [e for e in error_messages if "END" in e.upper()]
    assert len(end_error) >= 1, f"Expected END-EVALUATE error, got: {error_messages}"


def test_evaluate_selector_mismatch_single_subject():
    """EVALUATE with multiple selectors but single subject should error."""
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
    result = _parse_with_errors(_fixed_source(source))
    assert len(result.errors) >= 1
    error_messages = [str(e) for e in result.errors]
    mismatch_error = [
        e for e in error_messages if "selector" in e.lower() or "subject" in e.lower()
    ]
    assert (
        len(mismatch_error) >= 1
    ), f"Expected selector/subject mismatch error, got: {error_messages}"


def test_evaluate_selector_mismatch_multiple_subjects():
    """EVALUATE with single selector but multiple subjects should error."""
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
    result = _parse_with_errors(_fixed_source(source))
    assert len(result.errors) >= 1
    error_messages = [str(e) for e in result.errors]
    mismatch_error = [
        e for e in error_messages if "selector" in e.lower() or "subject" in e.lower()
    ]
    assert (
        len(mismatch_error) >= 1
    ), f"Expected selector/subject mismatch error, got: {error_messages}"


def test_evaluate_invalid_through_range():
    """EVALUATE with invalid THRU/THROUGH range should error."""
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
    result = _parse_with_errors(_fixed_source(source))
    assert len(result.errors) >= 1
    error_messages = [str(e) for e in result.errors]
    thru_error = [
        e
        for e in error_messages
        if "THRU" in e.upper() or "THROUGH" in e.upper() or "range" in e.lower()
    ]
    assert len(thru_error) >= 1, f"Expected THRU/THROUGH error, got: {error_messages}"


def test_evaluate_through_without_end_value():
    """EVALUATE with THRU but missing end value should error."""
    source = """
    IDENTIFICATION DIVISION.
    PROGRAM-ID. TEST.
    DATA DIVISION.
    WORKING-STORAGE SECTION.
    01  WS-NUM PIC 99.
    PROCEDURE DIVISION.
        EVALUATE WS-NUM
            WHEN 1 THRU
                DISPLAY 'INCOMPLETE'
            WHEN OTHER
                DISPLAY 'OTHER'
        END-EVALUATE.
    """
    result = _parse_with_errors(_fixed_source(source))
    assert len(result.errors) >= 1


def test_evaluate_when_other_must_be_last():
    """WHEN OTHER not as last WHEN clause should warn or error."""
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
    result = _parse_with_errors(_fixed_source(source))
    assert len(result.errors) >= 1 or len(result.warnings) >= 1


def test_evaluate_true_without_condition():
    """EVALUATE TRUE without WHEN condition should error."""
    source = """
    IDENTIFICATION DIVISION.
    PROGRAM-ID. TEST.
    DATA DIVISION.
    WORKING-STORAGE SECTION.
    PROCEDURE DIVISION.
        EVALUATE TRUE
            WHEN
                DISPLAY 'EMPTY'
            WHEN OTHER
                DISPLAY 'OTHER'
        END-EVALUATE.
    """
    result = _parse_with_errors(_fixed_source(source))
    assert len(result.errors) >= 1


def test_evaluate_empty_when_selector():
    """EVALUATE with empty WHEN selector should error."""
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
    result = _parse_with_errors(_fixed_source(source))
    assert len(result.errors) >= 1


def test_evaluate_error_location_tracked():
    """EVALUATE errors should include line and column information."""
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
    result = _parse_with_errors(_fixed_source(source))
    assert len(result.errors) >= 1
    for error in result.errors:
        assert hasattr(error, "line_number") or hasattr(error, "location")
        if hasattr(error, "line_number"):
            assert error.line_number > 0
        if hasattr(error, "location"):
            assert error.location.line > 0


def test_evaluate_multiple_errors_collected():
    """Multiple EVALUATE errors should all be collected."""
    source = """
    IDENTIFICATION DIVISION.
    PROGRAM-ID. TEST.
    DATA DIVISION.
    WORKING-STORAGE SECTION.
    01  WS-GRADE PIC 9.
    01  WS-STATUS PIC X.
    PROCEDURE DIVISION.
        EVALUATE WS-GRADE
            WHEN 1 ALSO 'A' ALSO 'B'
                DISPLAY 'TOO MANY'
            WHEN
        END-EVALUATE.
    """
    result = _parse_with_errors(_fixed_source(source))
    assert len(result.errors) >= 2


def test_evaluate_parser_stays_stable():
    """Parser should remain stable after EVALUATE errors."""
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
        MOVE 5 TO WS-GRADE.
        EVALUATE TRUE
            WHEN WS-GRADE = 10
                DISPLAY 'TEN'
            WHEN OTHER
                DISPLAY 'OTHER'
        END-EVALUATE.
    """
    result = _parse_with_errors(_fixed_source(source))
    assert result.ast is not None
    assert len(result.ast.divisions) >= 1


def test_evaluate_invalid_also_chain():
    """EVALUATE with consecutive ALSO should error."""
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
    result = _parse_with_errors(_fixed_source(source))
    assert len(result.errors) >= 1


def test_evaluate_mixed_thru_through():
    """EVALUATE with mixed THRU/THROUGH should be accepted."""
    source = """
    IDENTIFICATION DIVISION.
    PROGRAM-ID. TEST.
    DATA DIVISION.
    WORKING-STORAGE SECTION.
    01  WS-NUM PIC 99.
    PROCEDURE DIVISION.
        EVALUATE WS-NUM
            WHEN 1 THRU 5
                DISPLAY 'LOW'
            WHEN 6 THROUGH 10
                DISPLAY 'MEDIUM'
            WHEN OTHER
                DISPLAY 'HIGH'
        END-EVALUATE.
    """
    result = _parse_with_errors(_fixed_source(source))
    assert len(result.errors) == 0


def test_evaluate_any_with_also():
    """EVALUATE with ANY selector combined with ALSO should work."""
    source = """
    IDENTIFICATION DIVISION.
    PROGRAM-ID. TEST.
    DATA DIVISION.
    WORKING-STORAGE SECTION.
    01  WS-GRADE PIC 9.
    01  WS-STATUS PIC X.
    PROCEDURE DIVISION.
        EVALUATE WS-GRADE ALSO WS-STATUS
            WHEN ANY ALSO 'A'
                DISPLAY 'A-ANY'
            WHEN OTHER
                DISPLAY 'OTHER'
        END-EVALUATE.
    """
    result = _parse_with_errors(_fixed_source(source))
    assert len(result.errors) == 0
