"""Error-path and lesser-used-syntax coverage for InvokeStatementParser.

Existing INVOKE tests (test_invoke_allocate_free_statements.py and friends)
exercise the happy path -- a well-formed INVOKE with a literal or identifier
method name. This file targets the branches those tests never reach: the
two required-operand validations (missing object identifier, missing method
name), the END-INVOKE terminator, and the BY REFERENCE/CONTENT/VALUE
modifiers in the USING clause.
"""

from cobolparser import ErrorRecoveryMode, parse_cobol


def _parse_collect_all(src: str):
    return parse_cobol(src, error_recovery=ErrorRecoveryMode.COLLECT_ALL)


class TestInvokeMissingOperands:
    def test_missing_object_identifier_reports_error(self):
        src = """IDENTIFICATION DIVISION.
PROGRAM-ID. T1.
PROCEDURE DIVISION.
MAIN.
    INVOKE 'literal-not-an-object' 'getName'.
    STOP RUN.
"""
        result = _parse_collect_all(src)
        assert any(
            "object identifier" in str(e).lower() for e in result.errors
        ), result.errors

    def test_missing_method_name_reports_error(self):
        src = """IDENTIFICATION DIVISION.
PROGRAM-ID. T1.
DATA DIVISION.
WORKING-STORAGE SECTION.
01 WS-OBJ PIC X(8).
PROCEDURE DIVISION.
MAIN.
    INVOKE WS-OBJ.
    STOP RUN.
"""
        result = _parse_collect_all(src)
        assert any(
            "method name" in str(e).lower() for e in result.errors
        ), result.errors


class TestInvokeEndInvokeTerminator:
    def test_end_invoke_terminates_and_a_following_statement_is_not_swallowed(self):
        src = """IDENTIFICATION DIVISION.
PROGRAM-ID. T1.
DATA DIVISION.
WORKING-STORAGE SECTION.
01 WS-OBJ PIC X(8).
PROCEDURE DIVISION.
MAIN.
    INVOKE WS-OBJ 'run' END-INVOKE
    DISPLAY 'AFTER-INVOKE'.
    STOP RUN.
"""
        result = parse_cobol(src)
        assert result.success, result.errors
        invokes = result.ast.find_all_by_type("InvokeStatement")
        assert len(invokes) == 1
        displays = result.ast.find_all_by_type("DisplayStatement")
        assert len(displays) == 1


class TestInvokeUsingByModifiers:
    def test_by_reference_content_value_modifiers_apply_per_phase(self):
        src = """IDENTIFICATION DIVISION.
PROGRAM-ID. T1.
DATA DIVISION.
WORKING-STORAGE SECTION.
01 WS-OBJ PIC X(8).
01 WS-A PIC X(4).
01 WS-B PIC X(4).
01 WS-C PIC X(4).
PROCEDURE DIVISION.
MAIN.
    INVOKE WS-OBJ 'run' USING BY REFERENCE WS-A BY CONTENT WS-B BY VALUE WS-C.
    STOP RUN.
"""
        result = parse_cobol(src)
        assert result.success, result.errors
        stmt = result.ast.find_all_by_type("InvokeStatement")[0]
        modes = {p.name: p.passing_mode for p in stmt.using_parameters}
        assert modes["WS-A"] == "REFERENCE"
        assert modes["WS-B"] == "CONTENT"
        assert modes["WS-C"] == "VALUE"

    def test_using_clause_defaults_to_reference_with_no_by_phrase(self):
        src = """IDENTIFICATION DIVISION.
PROGRAM-ID. T1.
DATA DIVISION.
WORKING-STORAGE SECTION.
01 WS-OBJ PIC X(8).
01 WS-A PIC X(4).
PROCEDURE DIVISION.
MAIN.
    INVOKE WS-OBJ 'run' USING WS-A.
    STOP RUN.
"""
        result = parse_cobol(src)
        assert result.success, result.errors
        stmt = result.ast.find_all_by_type("InvokeStatement")[0]
        assert stmt.using_parameters[0].passing_mode == "REFERENCE"

    def test_using_clause_accepts_comma_separated_parameters(self):
        src = """IDENTIFICATION DIVISION.
PROGRAM-ID. T1.
DATA DIVISION.
WORKING-STORAGE SECTION.
01 WS-OBJ PIC X(8).
01 WS-A PIC X(4).
01 WS-B PIC X(4).
PROCEDURE DIVISION.
MAIN.
    INVOKE WS-OBJ 'run' USING WS-A, WS-B.
    STOP RUN.
"""
        result = parse_cobol(src)
        assert result.success, result.errors
        stmt = result.ast.find_all_by_type("InvokeStatement")[0]
        names = [p.name for p in stmt.using_parameters]
        assert names == ["WS-A", "WS-B"]

    def test_returning_with_no_target_identifier_is_ignored_gracefully(self):
        src = """IDENTIFICATION DIVISION.
PROGRAM-ID. T1.
DATA DIVISION.
WORKING-STORAGE SECTION.
01 WS-OBJ PIC X(8).
PROCEDURE DIVISION.
MAIN.
    INVOKE WS-OBJ 'run' RETURNING.
    STOP RUN.
"""
        result = parse_cobol(src)
        assert result.success, result.errors
        stmt = result.ast.find_all_by_type("InvokeStatement")[0]
        assert stmt.returning_target is None


class TestInvokeUsingClauseEdgeCases:
    def test_by_with_unrecognized_mode_word_falls_back_to_reference(self):
        # "BY XYZ" -- XYZ isn't REFERENCE/CONTENT/VALUE, so the BY phrase is
        # left un-consumed past the BY token itself and the loop re-examines
        # XYZ as an ordinary USING parameter under the still-default mode.
        src = """IDENTIFICATION DIVISION.
PROGRAM-ID. T1.
DATA DIVISION.
WORKING-STORAGE SECTION.
01 WS-OBJ PIC X(8).
01 XYZ PIC X(4).
PROCEDURE DIVISION.
MAIN.
    INVOKE WS-OBJ 'run' USING BY XYZ.
    STOP RUN.
"""
        result = parse_cobol(src)
        assert result.success, result.errors
        stmt = result.ast.find_all_by_type("InvokeStatement")[0]
        assert [p.name for p in stmt.using_parameters] == ["XYZ"]
        assert stmt.using_parameters[0].passing_mode == "REFERENCE"

    def test_statement_keyword_with_no_period_stops_using_clause(self):
        # A following statement verb (MOVE) with no separating period must
        # end the USING clause rather than being swallowed as a parameter.
        src = """IDENTIFICATION DIVISION.
PROGRAM-ID. T1.
DATA DIVISION.
WORKING-STORAGE SECTION.
01 WS-OBJ PIC X(8).
01 WS-A PIC X(4).
01 WS-B PIC X(4).
PROCEDURE DIVISION.
MAIN.
    INVOKE WS-OBJ 'run' USING WS-A
    MOVE WS-A TO WS-B.
    STOP RUN.
"""
        result = parse_cobol(src)
        assert result.success, result.errors
        invokes = result.ast.find_all_by_type("InvokeStatement")
        moves = result.ast.find_all_by_type("MoveStatement")
        assert len(invokes) == 1
        assert len(moves) == 1
        assert [p.name for p in invokes[0].using_parameters] == ["WS-A"]


class TestInvokeUnrecognizedTrailingToken:
    def test_unrecognized_token_after_method_name_stops_parsing_without_consuming(self):
        # A stray keyword-shaped token that is neither USING/RETURNING/
        # END-INVOKE/a scope terminator/a statement keyword falls through
        # to the final "unrecognized token" break -- this pins that the
        # loop stops cleanly rather than looping or raising.
        src = """IDENTIFICATION DIVISION.
PROGRAM-ID. T1.
DATA DIVISION.
WORKING-STORAGE SECTION.
01 WS-OBJ PIC X(8).
PROCEDURE DIVISION.
MAIN.
    INVOKE WS-OBJ 'run' 99.
    STOP RUN.
"""
        result = _parse_collect_all(src)
        invokes = result.ast.find_all_by_type("InvokeStatement")
        assert len(invokes) == 1
