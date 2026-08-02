"""Regression tests for CALL...USING comma and OMITTED handling.

Covers two bugs previously found in ``CallStatementParser._parse_using_clause``
(cobolparser/parsers/statements/call_parser.py):

1. Comma truncation: ``CALL "X" USING A, B, C`` only captured the first
   parameter (``A``) because ``TokenType.COMMA`` was not tolerated by the
   boundary check, so the loop ended at the first comma.
2. OMITTED breaking the list: ``TokenType.OMITTED`` was not accepted by
   either the boundary check or the parameter-name check, so any USING
   clause containing ``OMITTED`` lost every parameter, not just the
   omitted one.
"""

from cobolparser import parse_cobol


class TestCallUsingCommaOmitted:
    """Regression coverage for USING clause comma/OMITTED handling."""

    def test_comma_separated_parameters_all_present(self):
        """CALL "X" USING A, B, C must capture all three parameters."""
        source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST.
        PROCEDURE DIVISION.
            CALL "X" USING A, B, C.
            STOP RUN.
        """
        result = parse_cobol(source)
        assert result.success
        assert result.errors == []

        calls = result.ast.find_statements("CALL")
        assert len(calls) == 1
        call_stmt = calls[0]

        assert [p.name for p in call_stmt.using_parameters] == ["A", "B", "C"]
        assert [p.passing_mode for p in call_stmt.using_parameters] == [
            "REFERENCE",
            "REFERENCE",
            "REFERENCE",
        ]

    def test_omitted_parameters_preserved_with_mode(self):
        """OMITTED must be captured as a parameter, not drop the whole list."""
        source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST.
        PROCEDURE DIVISION.
            CALL "X" USING OMITTED, A, BY REFERENCE OMITTED.
            STOP RUN.
        """
        result = parse_cobol(source)
        assert result.success
        assert result.errors == []

        calls = result.ast.find_statements("CALL")
        assert len(calls) == 1
        call_stmt = calls[0]

        assert len(call_stmt.using_parameters) == 3
        assert [p.name for p in call_stmt.using_parameters] == [
            "OMITTED",
            "A",
            "OMITTED",
        ]
        # First OMITTED has no explicit BY phrase -> defaults to REFERENCE.
        assert call_stmt.using_parameters[0].passing_mode == "REFERENCE"
        assert call_stmt.using_parameters[1].passing_mode == "REFERENCE"
        # Trailing OMITTED explicitly tagged BY REFERENCE.
        assert call_stmt.using_parameters[2].passing_mode == "REFERENCE"

    def test_omitted_in_middle_does_not_drop_trailing_parameter(self):
        """A well-formed trailing parameter after OMITTED must survive.

        BY REFERENCE governs OMITTED; the parser resets to the (REFERENCE)
        default for the next parameter when no new BY phrase is given, which
        coincides with REFERENCE here since that is also the default mode.
        """
        source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST.
        PROCEDURE DIVISION.
            CALL "X" USING A BY REFERENCE OMITTED B.
            STOP RUN.
        """
        result = parse_cobol(source)
        assert result.success
        assert result.errors == []

        calls = result.ast.find_statements("CALL")
        assert len(calls) == 1
        call_stmt = calls[0]

        assert [p.name for p in call_stmt.using_parameters] == ["A", "OMITTED", "B"]
        assert call_stmt.using_parameters[0].passing_mode == "REFERENCE"
        assert call_stmt.using_parameters[1].passing_mode == "REFERENCE"
        assert call_stmt.using_parameters[2].passing_mode == "REFERENCE"

    def test_mixed_by_modes_across_comma_separated_parameters(self):
        """No regression: BY CONTENT/REFERENCE/VALUE still tracked per-param."""
        source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST.
        PROCEDURE DIVISION.
            CALL "X" USING BY REFERENCE A, BY CONTENT B, BY VALUE C.
            STOP RUN.
        """
        result = parse_cobol(source)
        assert result.success
        assert result.errors == []

        calls = result.ast.find_statements("CALL")
        assert len(calls) == 1
        call_stmt = calls[0]

        assert [p.name for p in call_stmt.using_parameters] == ["A", "B", "C"]
        assert [p.passing_mode for p in call_stmt.using_parameters] == [
            "REFERENCE",
            "CONTENT",
            "VALUE",
        ]
